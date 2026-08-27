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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cosqli.paths import require_external_path
from cosqli.telemetry import measure_stage
from cosqli.utils.json_operation import read_jsonl_file
from cosqli.utils.yaml_operation import load_yaml_to_dict


# Absolute paths to lower-level model operation scripts. Keeping these as
# paths avoids importing heavyweight training dependencies into the
# orchestration process.
_THIS_DIR = Path(__file__).resolve().parent
_MODELING_DIR = _THIS_DIR.parent / "modeling"
FINETUNE_PY = str(_MODELING_DIR / "finetune.py")
MERGE_PY = str(_MODELING_DIR / "merge_lora.py")
INFER_PY = str(_MODELING_DIR / "inference.py")


@dataclass
class EvaluationOutput:
    """One dataset evaluation and its persisted aggregate metrics."""

    dataset_name: str
    results: List[Dict]
    metrics: Dict[str, Any]
    duration_seconds: float


@dataclass
class DefenderOutput:
    """Artifacts needed by the verifier and experiment reporting."""

    validation: EvaluationOutput
    test: Optional[EvaluationOutput]
    stages: Dict[str, float]
    training_metrics: Dict[str, Any]


class Defender:
    """
    Manages fine-tuning, LoRA merging, and inference for one training round.

    Args:
        validation_file:        Path to the validation JSONL used for MAB
                                feedback.
        test_file:              Path to the held-out test JSONL. Its metrics
                                are never passed to the verifier.
        training_config_path:   Path to the training configuration YAML file.
        inference_config_path:  Path to the inference configuration YAML file.
        random_seed:            Seed shared by fine-tuning and inference.
    """

    def __init__(
        self,
        validation_file: str,
        test_file: str,
        training_config_path: str,
        inference_config_path: str,
        random_seed: int,
    ) -> None:
        self.validation_file = validation_file
        self.test_file = test_file
        self.training_config_path = training_config_path
        self.inference_config_path = inference_config_path
        self.random_seed = random_seed
        self.training_cfg: Dict[str, Any] = load_yaml_to_dict(training_config_path)
        self.inference_cfg: Dict[str, Any] = load_yaml_to_dict(inference_config_path)

    # ------------------------------------------------------------------
    # Step 1 — Fine-tune
    # ------------------------------------------------------------------

    def run_finetune(
        self, base_model: str, train_file: str, output_root: str
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Launch multi-GPU LoRA fine-tuning via ``accelerate launch``.

        Args:
            base_model:   Path to the base (or previously merged) model.
            train_file:   Path to the training JSONL file.
            output_root:  Root directory for this round's outputs; the LoRA
                          adapter is saved to ``{output_root}/adapter/``.

        Returns:
            A tuple containing the LoRA adapter directory on success (or
            ``None``) and structured training metrics.
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
        training_metrics_path = os.path.join(output_root, "performance", "training_metrics.json")
        os.makedirs(lora_output_dir, exist_ok=True)

        print(
            f"*** Fine-tuning {base_model} "
            f"(GPUs={num_gpus}, batch={cfg['batch_size_per_gpu']}, "
            f"grad_accum={cfg['gradient_accumulation_steps']}) ***"
        )
        print(f"*** Training data: {train_file} ***")
        print(f"*** Data proportion: {cfg['data_prop']}  Seed: {self.random_seed} ***")

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
            "--metrics_file", training_metrics_path,
            "--logging_steps", str(cfg["logging_steps"]),
            "--token_select_pattern", cfg["token_select_pattern"],
            "--data_prop", str(cfg["data_prop"]),
            "--seed", str(self.random_seed),
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
        round_index = int(Path(output_root).name.removeprefix("round_"))
        with measure_stage(
            Path(output_root).parent,
            round_index=round_index,
            stage="fine_tune",
        ) as timing:
            result = subprocess.run(cmd, env=env, stdout=sys.stdout, stderr=sys.stderr)

        metrics: Dict[str, Any] = {}
        metrics_path = Path(training_metrics_path)
        if metrics_path.is_file():
            with metrics_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                metrics = loaded
        metrics["subprocess_seconds"] = timing["duration_seconds"]
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_path.open("w", encoding="utf-8") as handle:
            json.dump(metrics, handle, ensure_ascii=False, indent=2)

        if result.returncode != 0:
            print(f"Fine-tuning failed with return code {result.returncode}.")
            return None, metrics

        adapter_config = os.path.join(lora_output_dir, "adapter_config.json")
        if not os.path.exists(adapter_config):
            print(
                f"No adapter_config.json found in {lora_output_dir}. "
                "Fine-tuning did not produce LoRA weights."
            )
            return None, metrics

        return lora_output_dir, metrics

    # ------------------------------------------------------------------
    # Step 2 — Merge
    # ------------------------------------------------------------------

    def run_merge(
        self, base_model: str, output_root: str, lora_output_dir: str
    ) -> Tuple[str, float]:
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
            The merged model directory and merge wall-clock time in seconds.
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
        round_index = int(Path(output_root).name.removeprefix("round_"))
        with measure_stage(
            Path(output_root).parent,
            round_index=round_index,
            stage="merge",
        ) as timing:
            subprocess.run(
                [str(x) for x in cmd],
                env=env,
                check=True,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        print("*** Merge complete. ***")
        return merged_output_dir, timing["duration_seconds"]

    # ------------------------------------------------------------------
    # Step 3 — Inference
    # ------------------------------------------------------------------

    def run_inference(
        self,
        model_path: str,
        output_root: str,
        dataset_file: str,
        dataset_name: str,
    ) -> EvaluationOutput:
        """
        Run inference on one named dataset and return its results and metrics.

        Inference is executed as a subprocess.  The script writes two files:
        - ``{output_root}/evaluation/{dataset_name}/results.jsonl`` — predictions.
        - ``{output_root}/evaluation/{dataset_name}/metrics.json``  — metrics.

        Args:
            model_path: Path to the merged model to evaluate.
            output_root: Root directory for this round's outputs.
            dataset_file: Dataset JSONL to evaluate.
            dataset_name: Stable name used in the output path and report.

        Returns:
            Structured evaluation results.

        Raises:
            ValueError: If a required model or dataset path is absent.
        """
        if not model_path:
            raise ValueError("run_inference requires a valid model_path.")
        if not dataset_file:
            raise ValueError("run_inference requires a dataset_file to be set.")

        infer_cfg = self.inference_cfg
        inference_output_dir = os.path.join(output_root, "evaluation", dataset_name)
        os.makedirs(inference_output_dir, exist_ok=True)
        output_file = os.path.join(inference_output_dir, "results.jsonl")

        device = infer_cfg.get("device", "cuda:0")
        cmd = [
            sys.executable, INFER_PY,
            "--model_path", model_path,
            "--test_file", dataset_file,
            "--output_file", output_file,
            "--batch_size", str(infer_cfg.get("batch_size", 1)),
            "--max_new_tokens", str(infer_cfg.get("max_new_tokens", 128)),
            "--max_seq_length", str(infer_cfg.get("max_seq_length", 2048)),
            "--temperature", str(infer_cfg.get("temperature", 0.1)),
            "--top_p", str(infer_cfg.get("top_p", 0.9)),
            "--seed", str(self.random_seed),
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

        print(f"\n[Defender] Starting {dataset_name} evaluation (subprocess):")
        print("Running command:\n" + " ".join(str(x) for x in cmd))
        round_index = int(Path(output_root).name.removeprefix("round_"))
        with measure_stage(
            Path(output_root).parent,
            round_index=round_index,
            stage=f"{dataset_name}_evaluation",
        ) as timing:
            subprocess.run(
                [str(x) for x in cmd],
                env=env,
                check=True,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )

        results = read_jsonl_file(output_file)

        metrics_path = os.path.join(inference_output_dir, "metrics.json")
        metrics: Dict[str, Any] = {}
        if os.path.exists(metrics_path):
            with open(metrics_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                metrics = loaded
            metrics.setdefault("timing", {})["orchestrator_seconds"] = timing["duration_seconds"]
            with open(metrics_path, "w", encoding="utf-8") as f:
                json.dump(metrics, f, ensure_ascii=False, indent=2)
            accuracy = metrics.get("accuracy")
            if isinstance(accuracy, (float, int)):
                print(f"[Defender] {dataset_name} evaluation complete. Accuracy: {accuracy:.4f}")
            return EvaluationOutput(dataset_name, results, metrics, timing["duration_seconds"])

        print(
            f"[Defender] {dataset_name} evaluation complete (metrics.json not found). "
            f"Results written to: {output_file}"
        )
        return EvaluationOutput(dataset_name, results, metrics, timing["duration_seconds"])

    # ------------------------------------------------------------------
    # Convenience — run all three steps in sequence
    # ------------------------------------------------------------------

    def run_all(
        self,
        base_model: str,
        train_file: str,
        output_root: str,
        do_inference: bool = True,
    ) -> Optional[DefenderOutput]:
        """
        Execute the full fine-tune → merge → (optional) inference pipeline.

        Args:
            base_model:    Path to the base model for fine-tuning.
            train_file:    Path to the training JSONL file.
            output_root:   Root directory for this round's outputs.
            do_inference:  Whether to run inference after merging.

        Returns:
            Validation/test outputs, or ``None`` if fine-tuning fails.
        """
        output_root = str(require_external_path(output_root, purpose="defender output"))
        lora_dir, training_metrics = self.run_finetune(
            base_model=base_model,
            train_file=train_file,
            output_root=output_root,
        )
        if not lora_dir:
            print("Fine-tuning failed or produced no LoRA weights. Aborting.")
            return None

        merged_dir, merge_seconds = self.run_merge(
            base_model=base_model,
            output_root=output_root,
            lora_output_dir=lora_dir,
        )

        validation: Optional[EvaluationOutput] = None
        test: Optional[EvaluationOutput] = None
        if do_inference:
            validation = self.run_inference(
                model_path=merged_dir,
                output_root=output_root,
                dataset_file=self.validation_file,
                dataset_name="validation",
            )
            test = self.run_inference(
                model_path=merged_dir,
                output_root=output_root,
                dataset_file=self.test_file,
                dataset_name="test",
            )
        if validation is None:
            return None
        return DefenderOutput(
            validation=validation,
            test=test,
            stages={
                "fine_tune_seconds": float(training_metrics.get("subprocess_seconds", 0.0)),
                "merge_seconds": merge_seconds,
                "validation_evaluation_seconds": validation.duration_seconds,
                "test_evaluation_seconds": test.duration_seconds if test else 0.0,
            },
            training_metrics=training_metrics,
        )
