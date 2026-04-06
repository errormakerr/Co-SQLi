"""
Defender Module

Orchestrates the three-step model improvement pipeline for each training round:
1. **Fine-tune** — launch distributed LoRA/QLoRA training via ``accelerate``.
2. **Merge**     — merge LoRA adapter weights into the base model.
3. **Infer**     — run inference on the validation set and collect accuracy metrics.

Each step is executed as a subprocess so that GPU memory is fully released
between steps and CUDA_VISIBLE_DEVICES can be controlled independently.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.json_operation import read_jsonl_file
from utils.yaml_operation import load_yaml_to_dict


# Absolute paths to companion scripts (same directory as this file)
_THIS_DIR = Path(__file__).resolve().parent
FINETUNE_PY = str(_THIS_DIR / "finetune.py")
MERGE_PY = str(_THIS_DIR / "merge_lora.py")
INFER_PY = str(_THIS_DIR / "inference.py")


class Defender:
    """
    Manages fine-tuning, LoRA merging, and inference for one training round.

    Args:
        valid_file:             Path to the validation JSONL file used for
                                inference evaluation.
        training_config_path:   Path to the training configuration YAML file.
        inference_config_path:  Path to the inference configuration YAML file.
    """

    def __init__(
        self,
        valid_file: str,
        training_config_path: str,
        inference_config_path: str,
    ) -> None:
        self.valid_file = valid_file
        self.training_config_path = training_config_path
        self.inference_config_path = inference_config_path
        self.training_cfg: Dict[str, Any] = load_yaml_to_dict(training_config_path)
        self.inference_cfg: Dict[str, Any] = load_yaml_to_dict(inference_config_path)

    # ------------------------------------------------------------------
    # Step 1 — Fine-tune
    # ------------------------------------------------------------------

    def run_finetune(
        self, base_model: str, train_file: str, output_root: str
    ) -> Optional[str]:
        """
        Launch multi-GPU LoRA fine-tuning via ``accelerate launch``.

        Args:
            base_model:   Path to the base (or previously merged) model.
            train_file:   Path to the training JSONL file.
            output_root:  Root directory for this round's outputs; the LoRA
                          adapter is saved to ``{output_root}/adapter/``.

        Returns:
            Path to the LoRA adapter directory on success, or ``None`` on
            failure.
        """
        cfg = self.training_cfg
        # Auto-detect num_gpus from CUDA_VISIBLE_DEVICES (config comment says
        # "removed from YAML, auto-detected"), fall back to config if present.
        if "num_gpus" in cfg:
            num_gpus = cfg["num_gpus"]
        else:
            cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
            if cuda_visible:
                num_gpus = len([d for d in cuda_visible.split(",") if d.strip()])
            else:
                try:
                    import torch
                    num_gpus = torch.cuda.device_count() or 1
                except Exception:
                    num_gpus = 1
        lora_output_dir = os.path.join(output_root, "adapter")
        os.makedirs(lora_output_dir, exist_ok=True)

        print(
            f"*** Fine-tuning {base_model} "
            f"(GPUs={num_gpus}, batch={cfg['batch_size_per_gpu']}, "
            f"grad_accum={cfg['gradient_accumulation_steps']}) ***"
        )
        print(f"*** Training data: {train_file} ***")
        print(f"*** Data proportion: {cfg['data_prop']}  Seed: {cfg['random_seed']} ***")

        cmd = [
            "accelerate", "launch",
            "--num_machines", "1",
            "--mixed_precision", cfg["mixed_precision"],
            "--num_processes", str(num_gpus),
            "--config_file", cfg["accelerate_config_file"],
            "--main_process_port", str(cfg["main_process_port"]),
            FINETUNE_PY,
            "--model_name_or_path", base_model,
            "--tokenizer_name", base_model,
            "--train_file", train_file,
            "--max_seq_length", str(cfg["max_seq_length"]),
            "--preprocessing_num_workers", "16",
            "--checkpointing_steps", str(cfg["checkpointing_steps"]),
            "--per_device_train_batch_size", str(cfg["batch_size_per_gpu"]),
            "--gradient_accumulation_steps", str(cfg["gradient_accumulation_steps"]),
            "--learning_rate", str(cfg["learning_rate"]),
            "--lr_scheduler_type", cfg["lr_scheduler_type"],
            "--warmup_ratio", str(cfg["warmup_ratio"]),
            "--weight_decay", str(cfg["weight_decay"]),
            "--num_train_epochs", str(cfg["num_train_epochs"]),
            "--output_dir", lora_output_dir,
            "--logging_steps", str(cfg["logging_steps"]),
            "--token_select_pattern", cfg["token_select_pattern"],
            "--data_prop", str(cfg["data_prop"]),
            "--seed", str(cfg["random_seed"]),
            "--with_prompt_token", str(cfg["with_prompt_token"]),
            "--gradient_checkpointing",
            "--use_lora",
            "--lora_rank", str(cfg["lora_rank"]),
            "--lora_alpha", str(cfg["lora_alpha"]),
            "--lora_dropout", str(cfg["lora_dropout"]),
        ]

        if cfg.get("use_qlora", False):
            cmd.append("--use_qlora")
        if cfg.get("with_tracking", False):
            cmd.extend(["--with_tracking", "--report_to", cfg.get("report_to", "tensorboard")])

        env = os.environ.copy()
        if cfg.get("cuda_visible_devices"):
            env["CUDA_VISIBLE_DEVICES"] = cfg["cuda_visible_devices"]

        cmd = [str(x) for x in cmd]
        print("Running command:\n" + " ".join(cmd))
        result = subprocess.run(cmd, env=env, stdout=sys.stdout, stderr=sys.stderr)

        if result.returncode != 0:
            print(f"Fine-tuning failed with return code {result.returncode}.")
            return None

        adapter_config = os.path.join(lora_output_dir, "adapter_config.json")
        if not os.path.exists(adapter_config):
            print(
                f"No adapter_config.json found in {lora_output_dir}. "
                "Fine-tuning did not produce LoRA weights."
            )
            return None

        return lora_output_dir

    # ------------------------------------------------------------------
    # Step 2 — Merge
    # ------------------------------------------------------------------

    def run_merge(
        self, base_model: str, output_root: str, lora_output_dir: str
    ) -> str:
        """
        Merge the LoRA adapter into the base model and save the result.

        Args:
            base_model:       Path to the base model.
            output_root:      Root directory for this round's outputs; the
                              merged model is saved to
                              ``{output_root}/merged_model/``.
            lora_output_dir:  Path to the LoRA adapter produced by
                              :meth:`run_finetune`.

        Returns:
            Path to the merged model directory.
        """
        cfg = self.training_cfg
        merged_output_dir = os.path.join(output_root, "merged_model")
        os.makedirs(merged_output_dir, exist_ok=True)

        print(f"*** Merging LoRA from {lora_output_dir} → {merged_output_dir} ***")

        cmd = [
            sys.executable, MERGE_PY,
            "--lora_model_name_or_path", lora_output_dir,
            "--base_model_name_or_path", base_model,
            "--output_dir", merged_output_dir,
        ]

        qlora_flag = cfg.get("merge", {}).get("qlora", cfg.get("use_qlora", False))
        if qlora_flag:
            cmd.append("--qlora")
        if cfg.get("merge", {}).get("save_tokenizer", True):
            cmd.append("--save_tokenizer")
        if cfg.get("merge", {}).get("use_fast_tokenizer", True):
            cmd.append("--use_fast_tokenizer")

        merge_device = cfg.get("merge", {}).get("device", "auto")
        cmd.extend(["--device", str(merge_device)])

        env = os.environ.copy()
        merge_visible = cfg.get("merge", {}).get("cuda_visible_devices")
        if merge_visible:
            env["CUDA_VISIBLE_DEVICES"] = merge_visible

        print("Running command:\n" + " ".join(str(x) for x in cmd))
        subprocess.run(
            [str(x) for x in cmd],
            env=env,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print("*** Merge complete. ***")
        return merged_output_dir

    # ------------------------------------------------------------------
    # Step 3 — Inference
    # ------------------------------------------------------------------

    def run_inference(
        self, model_path: str, output_root: str
    ) -> Tuple[Optional[float], List[Dict]]:
        """
        Run inference on the validation set and return accuracy + results.

        Inference is executed as a subprocess.  The script writes two files:
        - ``{output_root}/inference/results.jsonl`` — per-sample predictions.
        - ``{output_root}/inference/metrics.json``  — aggregate metrics.

        Args:
            model_path:  Path to the (merged) model to evaluate.
            output_root: Root directory for this round's outputs.

        Returns:
            A tuple ``(accuracy, results)`` where *accuracy* is the overall
            classification accuracy (``None`` if ``metrics.json`` is missing)
            and *results* is the list of per-sample result dicts.

        Raises:
            ValueError: If *model_path* or ``valid_file`` is not set.
        """
        if not model_path:
            raise ValueError("run_inference requires a valid model_path.")
        if not self.valid_file:
            raise ValueError("run_inference requires a valid_file to be set.")

        infer_cfg = self.inference_cfg
        inference_output_dir = os.path.join(output_root, "inference")
        os.makedirs(inference_output_dir, exist_ok=True)
        output_file = os.path.join(inference_output_dir, "results.jsonl")

        device = infer_cfg.get("device", "cuda:0")
        cmd = [
            sys.executable, INFER_PY,
            "--model_path", model_path,
            "--test_file", self.valid_file,
            "--output_file", output_file,
            "--batch_size", str(infer_cfg.get("batch_size", 1)),
            "--max_new_tokens", str(infer_cfg.get("max_new_tokens", 128)),
            "--max_seq_length", str(infer_cfg.get("max_seq_length", 2048)),
            "--temperature", str(infer_cfg.get("temperature", 0.1)),
            "--top_p", str(infer_cfg.get("top_p", 0.9)),
            "--device", device,
        ]

        if infer_cfg.get("trust_remote_code", False):
            cmd.append("--trust_remote_code")
        if infer_cfg.get("max_samples") is not None:
            cmd.extend(["--max_samples", str(infer_cfg["max_samples"])])

        env = os.environ.copy()
        infer_visible = infer_cfg.get("cuda_visible_devices")
        if infer_visible:
            env["CUDA_VISIBLE_DEVICES"] = infer_visible

        print("\n[Defender] Starting inference evaluation (subprocess):")
        print("Running command:\n" + " ".join(str(x) for x in cmd))
        subprocess.run(
            [str(x) for x in cmd],
            env=env,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        results = read_jsonl_file(output_file)

        metrics_path = os.path.join(inference_output_dir, "metrics.json")
        if os.path.exists(metrics_path):
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            accuracy = metrics.get("accuracy")
            print(f"[Defender] Inference complete. Accuracy: {accuracy:.4f}")
            return accuracy, results

        print(
            "[Defender] Inference complete (metrics.json not found). "
            f"Results written to: {output_file}"
        )
        return None, results

    # ------------------------------------------------------------------
    # Convenience — run all three steps in sequence
    # ------------------------------------------------------------------

    def run_all(
        self,
        base_model: str,
        train_file: str,
        output_root: str,
        do_inference: bool = True,
    ) -> Optional[List[Dict]]:
        """
        Execute the full fine-tune → merge → (optional) inference pipeline.

        Args:
            base_model:    Path to the base model for fine-tuning.
            train_file:    Path to the training JSONL file.
            output_root:   Root directory for this round's outputs.
            do_inference:  Whether to run inference after merging.

        Returns:
            List of inference result dicts, or ``None`` if fine-tuning failed.
        """
        lora_dir = self.run_finetune(
            base_model=base_model,
            train_file=train_file,
            output_root=output_root,
        )
        if not lora_dir:
            print("Fine-tuning failed or produced no LoRA weights. Aborting.")
            return None

        merged_dir = self.run_merge(
            base_model=base_model,
            output_root=output_root,
            lora_output_dir=lora_dir,
        )

        results: Optional[List[Dict]] = None
        if do_inference:
            _, results = self.run_inference(
                model_path=merged_dir,
                output_root=output_root,
            )

        return results
