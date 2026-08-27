#!/usr/bin/env python
# coding=utf-8
"""
Model Inference and Accuracy Evaluation Script

Loads a fine-tuned (merged) model, runs inference over a test JSONL file,
and writes per-sample predictions plus aggregate metrics to disk.

Usage:
    python inference.py \\
        --model_path /path/to/merged_model \\
        --test_file  /path/to/test_data.jsonl \\
        --output_file /path/to/results.jsonl \\
        [--batch_size 1] [--max_new_tokens 128] ...
"""

import argparse
import json
import os
import random
import time
from typing import Dict, List, Optional

import torch
import numpy as np
from tqdm import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer

from cosqli.evaluation import compute_classification_metrics, compute_cluster_metrics
from cosqli.modeling.chat import (
    collect_message_tokenization_stats,
    render_inference_chat,
    tokenize_rendered_chat,
)
from cosqli.paths import require_external_path


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run inference with a fine-tuned model and evaluate accuracy."
    )
    parser.add_argument(
        "--model_path",
        type=str,
        required=True,
        help="Path to the model directory (base or merged).",
    )
    parser.add_argument(
        "--test_file",
        type=str,
        required=True,
        help="Path to the test data JSONL file.",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        required=True,
        help="Path for writing per-sample inference results.",
    )
    parser.add_argument("--batch_size", type=int, default=1, help="Inference batch size.")
    parser.add_argument(
        "--max_new_tokens", type=int, default=128, help="Maximum tokens to generate per sample."
    )
    parser.add_argument(
        "--max_seq_length", type=int, default=2048, help="Maximum input sequence length."
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature (lower = more deterministic).",
    )
    parser.add_argument("--top_p", type=float, default=0.9, help="Nucleus sampling parameter.")
    parser.add_argument("--seed", type=int, required=True, help="Random seed for generation.")
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="Device to run inference on (e.g. 'cuda:0', 'cpu').",
    )
    parser.add_argument(
        "--trust_remote_code",
        action="store_true",
        help="Pass trust_remote_code=True when loading the model/tokenizer.",
    )
    parser.add_argument(
        "--max_samples",
        type=int,
        default=None,
        help="Maximum number of test samples to evaluate (useful for debugging).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_test_data(file_path: str, max_samples: Optional[int] = None) -> List[Dict]:
    """
    Load test samples from a JSONL file.

    Args:
        file_path:   Path to the test JSONL file.
        max_samples: If set, only the first *max_samples* lines are loaded.

    Returns:
        List of sample dicts.
    """
    print(f"Loading test data from: {file_path}")
    data: List[Dict] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if max_samples is not None and idx >= max_samples:
                break
            data.append(json.loads(line.strip()))
    print(f"Loaded {len(data)} test samples.")
    return data


# ---------------------------------------------------------------------------
# Prompt construction (must match the format used during fine-tuning)
# ---------------------------------------------------------------------------

def build_prompt_from_messages(tokenizer, messages: List[Dict]) -> str:
    """
    Build an inference prompt from an OpenAI-style ``messages`` list.

    Qwen's native tokenizer chat template renders the prompt and opens the
    assistant turn. The rendered result must later be tokenized with
    ``add_special_tokens=False``.

    Args:
        tokenizer: Qwen tokenizer supplying ``apply_chat_template``.
        messages: List of ``{"role": ..., "content": ...}`` dicts.

    Returns:
        Formatted prompt string.
    """
    return render_inference_chat(tokenizer, messages)


# ---------------------------------------------------------------------------
# Answer extraction
# ---------------------------------------------------------------------------

def extract_answer(text: str) -> str:
    """
    Extract the classification label from generated text.

    Supports two output formats:
    1. ``<answer>...</answer>`` tag (preferred, more robust).
    2. Raw text containing ``"benign"`` or ``"malicious"``.

    Args:
        text: Raw text generated by the model.

    Returns:
        ``"malicious"``, ``"benign"``, or the first generated word as a
        fallback.
    """
    import re

    text = text.strip()

    # Try <answer>...</answer> tag first
    match = re.search(r"<answer>\s*(.*?)\s*</answer>", text, re.DOTALL | re.IGNORECASE)
    if match:
        answer_content = match.group(1).strip().lower()
        if "not malicious" in answer_content or "is benign" in answer_content:
            return "benign"
        if "malicious" in answer_content:
            return "malicious"
        if "benign" in answer_content:
            return "benign"
        return answer_content

    # Fallback: search in full text
    text_lower = text.lower()
    if "not malicious" in text_lower or "is benign" in text_lower:
        return "benign"
    if "malicious" in text_lower:
        return "malicious"
    if "benign" in text_lower:
        return "benign"

    # Last resort: return first word
    words = text.split()
    return words[0] if words else text


def get_ground_truth(messages: List[Dict]) -> str:
    """
    Extract the expected label from the assistant's message.

    Args:
        messages: OpenAI-style message list.

    Returns:
        Lower-cased ground-truth label string.
    """
    for message in messages:
        if message["role"] == "assistant":
            return message["content"].strip().lower()
    return ""


# ---------------------------------------------------------------------------
# Inference loop
# ---------------------------------------------------------------------------

def run_inference(args: argparse.Namespace) -> None:
    """
    Main inference routine.

    Loads the model and tokenizer, iterates over batches of test samples,
    generates predictions, and writes results + metrics to disk.

    Args:
        args: Parsed command-line arguments.
    """
    print("=" * 80)
    print("Starting model inference and evaluation")
    print("=" * 80)

    started_at = time.perf_counter()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    # 1. Load tokenizer and model
    model_load_started_at = time.perf_counter()
    print(f"\nLoading model: {args.model_path}")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_path,
        trust_remote_code=args.trust_remote_code,
        padding_side="left",  # left-padding for generative inference
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        trust_remote_code=args.trust_remote_code,
        torch_dtype=torch.float16 if args.device != "cpu" else torch.float32,
        device_map="auto" if args.device != "cpu" else None,
    )
    if args.device == "cpu":
        model = model.to(args.device)
    model.eval()
    model_load_seconds = time.perf_counter() - model_load_started_at
    print("Model loaded successfully.")

    # 2. Load test data
    test_data = load_test_data(args.test_file, args.max_samples)
    tokenization_stats = collect_message_tokenization_stats(
        test_data,
        tokenizer,
        args.max_seq_length,
        purpose="inference",
    )

    # 3. Inference loop
    results: List[Dict] = []
    correct = 0
    total = 0

    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)

    print(f"\nRunning inference (batch_size={args.batch_size}) ...")
    inference_started_at = time.perf_counter()
    with torch.no_grad():
        for i in tqdm(range(0, len(test_data), args.batch_size)):
            batch = test_data[i : i + args.batch_size]

            prompts: List[str] = []
            ground_truths: List[str] = []
            for example in batch:
                messages = example["messages"]
                prompts.append(build_prompt_from_messages(tokenizer, messages))
                ground_truths.append(get_ground_truth(messages))

            inputs = tokenize_rendered_chat(
                tokenizer,
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=args.max_seq_length,
            ).to(model.device)

            outputs = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                do_sample=args.temperature > 0,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )

            for j, output in enumerate(outputs):
                input_length = inputs["input_ids"][j].shape[0]
                generated_tokens = output[input_length:]
                generated_text = tokenizer.decode(
                    generated_tokens, skip_special_tokens=True
                )

                predicted = extract_answer(generated_text)
                ground_truth = ground_truths[j]
                is_correct = predicted == ground_truth

                if is_correct:
                    correct += 1
                total += 1

                result: Dict = {
                    "id": i + j,
                    "prompt": prompts[j],
                    "generated_text": generated_text,
                    "predicted_answer": predicted,
                    "ground_truth": ground_truth,
                    "is_correct": is_correct,
                }
                # Carry forward metadata fields from the original example
                for key in (
                    "sql",
                    "label",
                    "technique",
                    "reference_scope",
                    "comment_state",
                    "difficulty",
                ):
                    if key in batch[j]:
                        result[key] = batch[j][key]
                results.append(result)

    inference_seconds = time.perf_counter() - inference_started_at

    # 4. Compute aggregate and taxonomy-aware metrics.
    metrics = compute_classification_metrics(results)
    metrics["timing"] = {
        "model_load_seconds": model_load_seconds,
        "inference_seconds": inference_seconds,
        "total_seconds": time.perf_counter() - started_at,
        "samples_per_second": total / inference_seconds if inference_seconds else 0.0,
        "milliseconds_per_sample": 1000 * inference_seconds / total if total else 0.0,
    }
    metrics["tokenization"] = tokenization_stats
    cluster_metrics = compute_cluster_metrics(results)
    accuracy = metrics["accuracy"]
    print(f"\nOverall accuracy: {accuracy:.4f}  ({correct}/{total})")

    # 5. Write results
    print(f"\nSaving inference results to: {args.output_file}")
    with open(args.output_file, "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    metrics_path = os.path.join(os.path.dirname(args.output_file), "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    cluster_metrics_path = os.path.join(os.path.dirname(args.output_file), "cluster_metrics.json")
    with open(cluster_metrics_path, "w", encoding="utf-8") as f:
        json.dump(cluster_metrics, f, ensure_ascii=False, indent=2)
    print(f"Metrics saved to: {metrics_path}")
    print(f"Cluster metrics saved to: {cluster_metrics_path}")
    print("\nDone!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run inference."""
    args = parse_args()
    args.output_file = str(require_external_path(args.output_file, purpose="inference output"))

    print("\nConfiguration:")
    print(f"  Model path:       {args.model_path}")
    print(f"  Test file:        {args.test_file}")
    print(f"  Output file:      {args.output_file}")
    print(f"  Device:           {args.device}")
    print(f"  Batch size:       {args.batch_size}")
    print(f"  Max new tokens:   {args.max_new_tokens}")
    print(f"  Temperature:      {args.temperature}")
    print(f"  Top-p:            {args.top_p}")
    print(f"  Seed:             {args.seed}")
    if args.max_samples is not None:
        print(f"  Max samples:      {args.max_samples}")
    print()

    run_inference(args)


if __name__ == "__main__":
    main()
