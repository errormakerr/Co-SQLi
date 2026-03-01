#!/usr/bin/env python
# coding: utf-8

import os
import subprocess
import sys
from types import SimpleNamespace
import yaml
from typing import Any, Dict


from utils.yaml_operation import load_yaml_to_dict
from utils.json_operation import read_jsonl_file
from pathlib import Path



# 假设 finetune.py 和 merge_lora.py 与本文件在同一目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FINETUNE_PY = os.path.join(PROJECT_ROOT, "finetune.py")
MERGE_PY = os.path.join(PROJECT_ROOT, "merge_lora.py")
INFER_PY = os.path.join(PROJECT_ROOT, "inference.py")



class Defender:
    def __init__(self,valid_file: str,training_config_path: str,inference_config_path: str,):
        self.valid_file = valid_file

        self.training_config_path = training_config_path
        self.inference_config_path = inference_config_path
        self.training_cfg = load_yaml_to_dict(self.training_config_path)
        self.inference_cfg = load_yaml_to_dict(self.inference_config_path)


    def run_finetune(self, base_model, train_file, output_root) -> str | None:
        """
        调用 accelerate 启动多卡训练，返回 LoRA 输出目录。
        """
        cfg = self.training_cfg
        num_gpus = cfg["num_gpus"]

        lora_output_dir = os.path.join(output_root, "adapter")
        os.makedirs(lora_output_dir, exist_ok=True)

        print(
            f"*** Training {base_model} using {num_gpus} GPUs, "
            f"{cfg['batch_size_per_gpu']} batch size per GPU, "
            f"{cfg['gradient_accumulation_steps']} gradient accumulation steps ***"
        )
        print(f"*** Training data path: {train_file} ***")
        print(f"*** Selected data proportion: {cfg['data_prop']} ***")
        print(f"*** Random seed: {cfg['random_seed']} ***")

        cmd = [
            "accelerate",
            "launch",
            "--num_machines",
            "1",
            "--mixed_precision",
            cfg["mixed_precision"],
            "--num_processes",
            str(num_gpus),
            "--config_file",
            cfg["accelerate_config_file"],
            "--main_process_port",
            str(cfg["main_process_port"]),
            FINETUNE_PY,
            "--model_name_or_path",
            base_model,
            "--tokenizer_name",
            base_model,
            "--train_file",
            train_file,
            "--max_seq_length",
            str(cfg["max_seq_length"]),
            "--preprocessing_num_workers",
            "16",
            "--checkpointing_steps",
            str(cfg["checkpointing_steps"]),
            "--per_device_train_batch_size",
            str(cfg["batch_size_per_gpu"]),
            "--gradient_accumulation_steps",
            str(cfg["gradient_accumulation_steps"]),
            "--learning_rate",
            str(cfg["learning_rate"]),
            "--lr_scheduler_type",
            cfg["lr_scheduler_type"],
            "--warmup_ratio",
            str(cfg["warmup_ratio"]),
            "--weight_decay",
            str(cfg["weight_decay"]),
            "--num_train_epochs",
            str(cfg["num_train_epochs"]),
            "--output_dir",
            lora_output_dir,
            "--logging_steps",
            str(cfg["logging_steps"]),
            # "--train_data_tag",
            # self.train_data_tag,
            "--token_select_pattern",
            cfg["token_select_pattern"],
            "--data_prop",
            str(cfg["data_prop"]),
            "--seed",
            str(cfg["random_seed"]),
            "--with_prompt_token",
            str(cfg["with_prompt_token"]),
            "--gradient_checkpointing",
            "--use_lora",
            "--lora_rank",
            str(cfg["lora_rank"]),
            "--lora_alpha",
            str(cfg["lora_alpha"]),
            "--lora_dropout",
            str(cfg["lora_dropout"]),
        ]

        if cfg.get("use_qlora", False):
            cmd.append("--use_qlora")

        if cfg.get("with_tracking", False):
            cmd.append("--with_tracking")
            cmd.extend(["--report_to", cfg.get("report_to", "tensorboard")])

        env = os.environ.copy()
        if cfg.get("cuda_visible_devices"):
            env["CUDA_VISIBLE_DEVICES"] = cfg["cuda_visible_devices"]
        cmd = [str(x) for x in cmd]
        print("Running command:")
        print(" ".join(cmd))

        result = subprocess.run(cmd, env=env, stdout=sys.stdout, stderr=sys.stderr)
        if result.returncode != 0:
            print("Finetuning failed with return code", result.returncode)
            return None

        adapter_config_path = os.path.join(lora_output_dir, "adapter_config.json")
        if not os.path.exists(adapter_config_path):
            print(
                f"No adapter_config.json found in {lora_output_dir}. "
                "Finetune did not produce LoRA weights."
            )
            return None

        return lora_output_dir
    
    
    def run_merge(self, base_model, output_root, lora_output_dir: str) -> str:
        """
        子进程执行 merge 脚本：python merge_*.py --...
        """
        cfg = self.training_cfg

        merged_output_dir = os.path.join(output_root, "merged_model")
        os.makedirs(merged_output_dir, exist_ok=True)

        print(f"*** Merging LoRA from {lora_output_dir} into base model {base_model} ***")
        print(f"*** Saving merged model to {merged_output_dir} ***")

        cmd = [
            sys.executable, MERGE_PY,
            "--lora_model_name_or_path", str(lora_output_dir),
            "--base_model_name_or_path", str(base_model),
            "--output_dir", str(merged_output_dir),
        ]

        # 是否 qlora：沿用你原本的逻辑
        qlora_flag = cfg.get("merge", {}).get("qlora", cfg.get("use_qlora", False))
        if qlora_flag:
            cmd.append("--qlora")

        if cfg.get("merge", {}).get("save_tokenizer", True):
            cmd.append("--save_tokenizer")
        if cfg.get("merge", {}).get("use_fast_tokenizer", True):
            cmd.append("--use_fast_tokenizer")

        # merge 设备配置（优先使用配置中的设备，否则自动选择）
        merge_device = cfg.get("merge", {}).get("device", "auto")
        cmd.extend(["--device", str(merge_device)])

        # merge 的 CUDA_VISIBLE_DEVICES（可选）
        env = os.environ.copy()
        merge_visible = cfg.get("merge", {}).get("cuda_visible_devices", None)
        if merge_visible:
            env["CUDA_VISIBLE_DEVICES"] = merge_visible

        print("Running command:")
        print(" ".join([str(x) for x in cmd]))

        subprocess.run([str(x) for x in cmd], env=env, check=True, stdout=sys.stdout, stderr=sys.stderr)

        print("*** Merge finished. ***")
        return merged_output_dir

    
    def run_inference(self, model_path: str, output_root: str):
        infer_cfg = self.inference_cfg

        inference_output_dir = os.path.join(output_root, "inference")
        os.makedirs(inference_output_dir, exist_ok=True)

        output_file = os.path.join(inference_output_dir, "results.jsonl")

        if not model_path:
            raise ValueError("run_inference 需要 model_path")
        if not self.valid_file:
            raise ValueError("run_inference 需要 valid_file")

        # 注意：device 建议用 cuda:0 而不是 cuda
        device = infer_cfg.get("device", "cuda:0")

        cmd = [
            sys.executable, INFER_PY,
            "--model_path", str(model_path),
            "--test_file", str(self.valid_file),
            "--output_file", str(output_file),
            "--batch_size", str(infer_cfg.get("batch_size", 1)),
            "--max_new_tokens", str(infer_cfg.get("max_new_tokens", 128)),
            "--max_seq_length", str(infer_cfg.get("max_seq_length", 2048)),
            "--temperature", str(infer_cfg.get("temperature", 0.1)),
            "--top_p", str(infer_cfg.get("top_p", 0.9)),
            "--device", str(device),
        ]

        if infer_cfg.get("trust_remote_code", False):
            cmd.append("--trust_remote_code")

        if infer_cfg.get("max_samples", None) is not None:
            cmd.extend(["--max_samples", str(infer_cfg["max_samples"])])

        # inference 子进程的可见 GPU（强烈建议单独指定，避免污染训练卡）
        env = os.environ.copy()
        infer_visible = infer_cfg.get("cuda_visible_devices", None)
        if infer_visible:
            env["CUDA_VISIBLE_DEVICES"] = infer_visible

        print("\n[Defender] 开始推理评估 (subprocess):")
        print("Running command:")
        print(" ".join([str(x) for x in cmd]))

        subprocess.run([str(x) for x in cmd], env=env, check=True, stdout=sys.stdout, stderr=sys.stderr)
        results = read_jsonl_file(output_file)
        # 从 metrics.json 读取 accuracy（建议你在 inference.py 里写这个文件）
        import json
        metrics_path = os.path.join(inference_output_dir, "metrics.json")
        if os.path.exists(metrics_path):
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            accuracy = metrics.get("accuracy", None)
            print(f"[Defender] 推理完成，准确率: {accuracy}")
            return accuracy, results

        # 如果你还没加 metrics.json，就先返回 output_file
        print("[Defender] 推理完成（未找到 metrics.json），结果文件:", output_file)
        return None, results


    def run_all(self, base_model, train_file, output_root, do_inference: bool = True):
        """
        一键流程：训练 → 合并 → (可选) 推理
        """
        lora_dir = self.run_finetune(base_model=base_model, train_file=train_file, output_root=output_root)
        if not lora_dir:
            print("训练失败/未产生 LoRA，停止后续流程。")
            return None
        
        merged_dir = self.run_merge(base_model=base_model, output_root=output_root, lora_output_dir=lora_dir)

        if do_inference:
            accuracy, results = self.run_inference(model_path=merged_dir, output_root=output_root)

        return results


# def main():
    
#     valid_file = "/home/linxiaotian/panhao/eval_test/few_test_sqls.jsonl"
#     training_config_path = "/home/linxiaotian/panhao/new_train_test/config.yaml"
#     inference_config_path = "/home/linxiaotian/panhao/new_train_test/inference_config.yaml"
    
#     base_model = "/home/linxiaotian/llamafactory/LLaMA-Factory/model/Qwen/Qwen2.5-Coder-1.5B-Instruct"
#     train_file = "/home/linxiaotian/panhao/train_test/few_train_sqls.jsonl"
#     output_root = "/home/linxiaotian/panhao/output"

#     defender = Defender(valid_file=valid_file,training_config_path=training_config_path,inference_config_path=inference_config_path,)

#     # defender.run_finetune()
#     # defender.run_merge(...)
#     # defender.run_inference(model_path="...")

#     defender.run_all(do_inference=True)


# if __name__ == "__main__":
#     main()
