"""
Ablation Experiment Entry Point — Bandit Strategy Comparison

Independent entry point for running bandit strategy ablation experiments.
Does NOT modify ``main.py`` or any production code paths.

Usage::

    python src/ablation_main.py \\
        --strategy exp3 \\
        --seed 42 \\
        --mutation on \\
        --base_model /path/to/Qwen2.5-Coder-1.5B-Instruct \\
        --output_root /path/to/ablation_results \\
        --gpu 6,7 \\
        --port 29522
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from Attacker.payload_mutation import MutationMemory

import numpy as np

from Attacker.attacker import Attacker
from Defender.defender import Defender
from Verifier.eval import cluster_results, compute_cluster_acc
from strategies import STRATEGY_REGISTRY
from utils.cluster import NORMAL_CLUSTER_KEY, cluster_injection_sqls
from utils.json_operation import (
    read_json_file,
    write_json_file,
    write_jsonl_file,
)
from utils.yaml_operation import load_yaml_to_dict
from utils.logging_config import setup_logging


# ==================== Experiment Configuration Registry ====================

EXPERIMENT_CONFIGS: Dict[str, Dict[str, Any]] = {
    # Non-adaptive baseline
    "uniform":       {"class": "uniform",   "params": {}},
    # Simple heuristics
    "greedy":        {"class": "greedy",    "params": {}},
    # Softmax variants
    "softmax_0.1":   {"class": "softmax",   "params": {"temperature": 0.1}},
    "softmax_0.3":   {"class": "softmax",   "params": {"temperature": 0.3}},
    "softmax_0.5":   {"class": "softmax",   "params": {"temperature": 0.5}},
    # Thompson Sampling variants
    "thompson_0.5":  {"class": "thompson",  "params": {"decay": 0.5}},
    "thompson_0.7":  {"class": "thompson",  "params": {"decay": 0.7}},
    "thompson_0.9":  {"class": "thompson",  "params": {"decay": 0.9}},
    # EXP3 (current approach, must match main.py behaviour)
    "exp3":          {"class": "exp3",      "params": {"gamma_a": 0.7, "gamma_v": 0.3}},
}


# ==================== Fixed Training Parameters ====================
# These must match main.py to ensure a controlled experiment.

NUM_ROUNDS = 8
NUM_TRAINING_SQLS = 300
ATTACKER_K = 6
MODIFY_PAYLOAD_PROB_START = 0.1
MODIFY_PAYLOAD_PROB_END = 0.4


# ==================== Utility Functions ====================

def delete_folder_if_exists(folder_path: str) -> None:
    """Delete a directory if it exists; skip silently otherwise."""
    if os.path.isdir(folder_path):
        try:
            shutil.rmtree(folder_path)
            print(f"Deleted directory: {folder_path}")
        except Exception as e:
            print(f"Failed to delete {folder_path}: {e}")


def create_temp_training_config(
    original_config_path: str,
    output_path: str,
    seed: int,
    gpu: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """Create a temporary copy of training_config.yaml with overridden fields.

    Writes the modified config to *output_path*.  Fields overridden:
    - ``random_seed`` → *seed*
    - ``cuda_visible_devices`` → *gpu* (if provided)
    - ``num_gpus`` → inferred from *gpu* (if provided)
    - ``main_process_port`` → *port* (if provided)
    - ``accelerate_config_file`` → resolved absolute path
    """
    import yaml

    cfg = load_yaml_to_dict(original_config_path)
    cfg["random_seed"] = seed

    if gpu is not None:
        cfg["cuda_visible_devices"] = gpu
        cfg["num_gpus"] = len([g for g in gpu.split(",") if g.strip()])

    if port is not None:
        cfg["main_process_port"] = port

    # Ensure accelerate_config_file is an absolute path
    acc_config = cfg.get("accelerate_config_file", "")
    if acc_config and not os.path.isabs(acc_config):
        project_root = Path(__file__).resolve().parents[1]
        cfg["accelerate_config_file"] = str(project_root / acc_config)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    print(f"Temporary training config written to: {output_path}")


# ==================== Core Experiment Logic ====================

def run_single_experiment(
    strategy_name: str,
    seed: int,
    enable_mutation: bool,
    base_model_path: str,
    output_root: str,
    gpu: Optional[str] = None,
    port: Optional[int] = None,
    num_rounds: int = NUM_ROUNDS,
    start_round: int = 0,
    schema_mode: str = "aware",
) -> None:
    """Run one complete ablation experiment (R rounds of training).

    Args:
        strategy_name:   Key in ``EXPERIMENT_CONFIGS``.
        seed:            Random seed for reproducibility.
        enable_mutation: Whether to enable payload mutation.
        base_model_path: Path to the base model (e.g. Qwen2.5-Coder-1.5B-Instruct).
        output_root:     Root directory for all ablation output.
        gpu:             Comma-separated GPU IDs (e.g. "6,7").
        port:            Distributed training main process port.
        num_rounds:      Number of training rounds (default 8).
        start_round:     Round to resume from (default 0). Rounds before this
                         must be fully completed (adapter + metrics + selector_state).
        schema_mode:     ``"aware"`` (default) — each round's generated training
                         record includes the real database schema as DDL.
                         ``"free"`` — the schema slot is the literal string
                         ``"N/A"`` for every record (context-free training).
    """
    if schema_mode not in ("aware", "free"):
        raise ValueError(
            f"schema_mode must be 'aware' or 'free', got {schema_mode!r}"
        )
    # ── Resolve paths ──
    project_root = Path(__file__).resolve().parents[1]
    raw_datas_dir = project_root / "data" / "raw_datas_for_generation"
    benchmark_dir = project_root / "data" / "benchmark"
    config_dir = project_root / "config"

    # Match main.py: set working directory to project root
    os.chdir(project_root)

    # ── Set random seeds ──
    random.seed(seed)
    np.random.seed(seed)

    # ── Experiment output directory ──
    mut_tag = "mutON" if enable_mutation else "mutOFF"
    schema_tag = "schemaAware" if schema_mode == "aware" else "schemaFree"
    exp_name = f"{strategy_name}_{mut_tag}_{schema_tag}_seed{seed}"
    exp_dir = Path(output_root) / exp_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n{'=' * 60}")
    print(f"Experiment: {exp_name}")
    print(f"Output: {exp_dir}")
    print(f"{'=' * 60}")

    # ── Build cluster list (same as main.py L102) ──
    test_sqls_path = benchmark_dir / "test_sqls.json"
    cluster_list = list(
        cluster_injection_sqls(read_json_file(str(test_sqls_path))).keys()
    )

    # ── Create strategy instance ──
    if strategy_name not in EXPERIMENT_CONFIGS:
        raise ValueError(
            f"Unknown strategy {strategy_name!r}. "
            f"Available: {list(EXPERIMENT_CONFIGS.keys())}"
        )
    cfg = EXPERIMENT_CONFIGS[strategy_name]
    selector_cls = STRATEGY_REGISTRY[cfg["class"]]
    selector = selector_cls(cluster_list, **cfg["params"])
    print(f"Strategy: {strategy_name} ({selector_cls.__name__})")

    # ── Create Attacker instance ──
    attacker = Attacker(
        number_of_training_sqls=NUM_TRAINING_SQLS,
        cluster_list=cluster_list,
        normal_sqls_path=str(raw_datas_dir / "normal_sqls.json"),
        raw_datas_dir=str(raw_datas_dir),
        enable_payload_mutation=enable_mutation,
        mutation_model=None,
        schema_mode=schema_mode,
    )
    print(f"Schema mode: {schema_mode}")

    # ── Create temporary training config ──
    temp_config_path = str(exp_dir / "training_config.yaml")
    create_temp_training_config(
        original_config_path=str(config_dir / "training_config.yaml"),
        output_path=temp_config_path,
        seed=seed,
        gpu=gpu,
        port=port,
    )

    # ── Create Defender instance ──
    valid_datas_path = benchmark_dir / "valid_datas_openai_format.jsonl"
    defender = Defender(
        valid_file=str(valid_datas_path),
        training_config_path=temp_config_path,
        inference_config_path=str(config_dir / "inference_config.yaml"),
    )

    # ── Resume from checkpoint if start_round > 0 ──
    round_metrics: List[Dict[str, Any]] = []

    if start_round > 0:
        print(f"\nResuming from round {start_round}")
        # Load metrics from completed rounds
        for r in range(start_round):
            metrics_path = exp_dir / f"round_{r}" / "ablation_metrics.json"
            if not metrics_path.exists():
                raise FileNotFoundError(
                    f"Cannot resume: round {r} metrics not found at {metrics_path}"
                )
            round_metrics.append(read_json_file(str(metrics_path)))
            print(f"  Loaded round {r} metrics (overall_acc={round_metrics[-1]['overall_acc']:.4f})")

        # Restore selector state from the last completed round
        last_selector_state_path = exp_dir / f"round_{start_round - 1}" / "selector_state.json"
        if not last_selector_state_path.exists():
            raise FileNotFoundError(
                f"Cannot resume: selector_state.json not found at {last_selector_state_path}"
            )
        selector_state = read_json_file(str(last_selector_state_path))
        selector.set_state(selector_state)
        print(f"  Restored selector state from round {start_round - 1}")

        # Restore MutationMemory if available
        if enable_mutation:
            last_memory_path = exp_dir / f"round_{start_round - 1}" / "mutation_memory.json"
            if last_memory_path.exists():
                restored_memory = MutationMemory.load(str(last_memory_path))
                attacker.mutation_memory = restored_memory
                if attacker.payload_mutator is not None:
                    attacker.payload_mutator.memory = restored_memory
                print(f"  Restored MutationMemory from round {start_round - 1} "
                      f"({restored_memory.get_stats()['total_examples']} examples, "
                      f"{restored_memory.get_stats()['global_fingerprints']} fingerprints)")

        # Clean up incomplete round directory if it exists
        incomplete_round_dir = exp_dir / f"round_{start_round}"
        if incomplete_round_dir.exists():
            # Check if adapter directory exists (indicates completion)
            adapter_dir = incomplete_round_dir / "adapter" / "adapter_config.json"
            if not adapter_dir.exists():
                print(f"  Cleaning up incomplete round {start_round} directory")
                delete_folder_if_exists(str(incomplete_round_dir))

    # ── Main training loop ──
    for round_idx in range(start_round, num_rounds):
        print(f"\n{'=' * 50}")
        print(f"Round {round_idx}")
        print(f"{'=' * 50}")

        # Determine base model for this round
        if round_idx == 0:
            current_model = base_model_path
        else:
            current_model = str(exp_dir / f"round_{round_idx - 1}" / "merged_model")

        round_dir = exp_dir / f"round_{round_idx}"
        round_dir.mkdir(parents=True, exist_ok=True)

        # Current-round mutation probability (linear schedule)
        modify_prob = MODIFY_PAYLOAD_PROB_START + (
            (MODIFY_PAYLOAD_PROB_END - MODIFY_PAYLOAD_PROB_START)
            * (round_idx / max(num_rounds - 1, 1))
        )
        if enable_mutation:
            print(f"Payload mutation probability: {modify_prob:.2%}")

        # ── Phase 1: Strategy selects clusters ──
        selection_result = selector.select(k=ATTACKER_K, round_idx=round_idx)
        print(f"Strategy selected clusters: {selection_result.selected_clusters}")

        # ── Phase 2: Attacker generates training data ──
        train_datas, _ = attacker.generate_training_sqls(
            gamma=0.0,                          # Unused (selection_result branch)
            clusters_weight_distribution={},    # Unused (selection_result branch)
            strategy="by_probability",          # Unused (selection_result branch)
            k=ATTACKER_K,                       # Unused (selection_result branch)
            modify_payload_prob=modify_prob,
            selection_result=selection_result,
        )

        # Save training data
        train_path = round_dir / "train_datas.jsonl"
        write_jsonl_file(str(train_path), train_datas)
        print(f"Generated {len(train_datas)} training samples → {train_path}")

        # ── Phase 3: Defender trains and evaluates ──
        results = defender.run_all(
            base_model=current_model,
            train_file=str(train_path),
            output_root=str(round_dir),
            do_inference=True,
        )
        if results is None:
            print(f"ERROR: Training failed at round {round_idx}")
            break

        # ── Phase 4: Compute per-cluster accuracy ──
        clustered = cluster_results(results)
        stats = compute_cluster_acc(clustered)
        cluster_accs = {key: stat.acc for key, stat in stats.items()}

        # ── Phase 5: Update strategy ──
        selector.update(cluster_accs)

        # ── Phase 6: Record metrics ──
        injection_accs = {
            c: a for c, a in cluster_accs.items() if c != NORMAL_CLUSTER_KEY
        }
        acc_values = list(injection_accs.values())

        metrics: Dict[str, Any] = {
            "round": round_idx,
            "overall_acc": (
                sum(1 for r in results if r.get("is_correct")) / len(results)
                if results else 0.0
            ),
            "worst_cluster_acc": min(acc_values) if acc_values else 0.0,
            "cluster_acc_std": float(np.std(acc_values)) if acc_values else 0.0,
            "bottom5_avg_acc": (
                float(np.mean(sorted(acc_values)[:5]))
                if len(acc_values) >= 5 else 0.0
            ),
            "num_clusters_below_80": sum(1 for a in acc_values if a < 0.8),
            "per_cluster_acc": cluster_accs,
            "selected_clusters": selection_result.selected_clusters,
        }
        round_metrics.append(metrics)
        write_json_file(str(round_dir / "ablation_metrics.json"), metrics)
        write_json_file(str(round_dir / "selector_state.json"), selector.get_state())

        print(
            f"Round {round_idx} metrics: "
            f"overall={metrics['overall_acc']:.4f}  "
            f"worst={metrics['worst_cluster_acc']:.4f}  "
            f"std={metrics['cluster_acc_std']:.4f}  "
            f"<80%={metrics['num_clusters_below_80']}"
        )

        # ── Phase 7: Save mutation log ──
        if enable_mutation:
            mutated = attacker.get_mutated_payloads()
            if mutated:
                write_json_file(str(round_dir / "mutated_payloads.json"), mutated)
                print(f"Saved {len(mutated)} mutated payloads")

            # Persist MutationMemory for breakpoint recovery
            if attacker.mutation_memory is not None:
                memory_path = str(round_dir / "mutation_memory.json")
                attacker.mutation_memory.save(memory_path)

        # ── Phase 8: Clean up previous round's model (except last round) ──
        if round_idx > 0:
            prev_model = exp_dir / f"round_{round_idx - 1}" / "merged_model"
            if prev_model.exists():
                delete_folder_if_exists(str(prev_model))

    # ── Final evaluation on test set ──
    if round_metrics:
        print(f"\n{'=' * 50}")
        print("Final evaluation on test set")
        print(f"{'=' * 50}")

        final_model_path = str(
            exp_dir / f"round_{num_rounds - 1}" / "merged_model"
        )
        test_datas_path = benchmark_dir / "test_datas_openai_format.jsonl"
        final_test_dir = str(exp_dir / "final_test")

        if Path(final_model_path).exists():
            # Use the actual test set (not validation set) for final evaluation
            original_valid_file = defender.valid_file
            defender.valid_file = str(test_datas_path)

            infer_start = time.time()
            _, test_results = defender.run_inference(
                model_path=final_model_path,
                output_root=final_test_dir,
            )
            infer_elapsed = time.time() - infer_start

            # Restore original valid_file
            defender.valid_file = original_valid_file

            if test_results:
                test_clustered = cluster_results(test_results)
                test_stats = compute_cluster_acc(test_clustered)
                test_accs = {key: stat.acc for key, stat in test_stats.items()}
                test_injection_accs = {
                    c: a for c, a in test_accs.items() if c != NORMAL_CLUSTER_KEY
                }
                test_acc_values = list(test_injection_accs.values())
                test_overall = (
                    sum(1 for r in test_results if r.get("is_correct"))
                    / len(test_results)
                )
                test_num_samples = len(test_results)
                test_per_sample_ms = (infer_elapsed / test_num_samples) * 1000

                print(f"Test overall accuracy: {test_overall:.4f}")
                print(
                    f"Test worst cluster:   {min(test_acc_values):.4f}"
                    if test_acc_values else "Test worst cluster:   N/A"
                )
                print(
                    f"Test inference time:  {infer_elapsed:.1f}s total, "
                    f"{test_per_sample_ms:.2f}ms/sample ({test_num_samples} samples)"
                )
            else:
                test_overall = None
                test_accs = {}
                test_injection_accs = {}
                test_acc_values = []
                test_per_sample_ms = None
                test_num_samples = 0

            # Clean up last round's model now (test evaluation is complete)
            delete_folder_if_exists(final_model_path)
        else:
            print(f"WARNING: final model not found at {final_model_path}")
            test_overall = None
            test_accs = {}
            test_injection_accs = {}
            test_acc_values = []
            test_per_sample_ms = None
            test_num_samples = 0

    else:
        test_overall = None
        test_accs = {}
        test_injection_accs = {}
        test_acc_values = []
        test_per_sample_ms = None
        test_num_samples = 0

    # ── Save experiment summary ──
    summary: Dict[str, Any] = {
        "strategy": strategy_name,
        "seed": seed,
        "mutation": enable_mutation,
        "num_rounds": num_rounds,
        "round_metrics": round_metrics,
        # Validation set metrics (last round)
        "final_overall_acc": (
            round_metrics[-1]["overall_acc"] if round_metrics else None
        ),
        "final_worst_cluster_acc": (
            round_metrics[-1]["worst_cluster_acc"] if round_metrics else None
        ),
        "final_cluster_acc_std": (
            round_metrics[-1]["cluster_acc_std"] if round_metrics else None
        ),
        "final_bottom5_avg": (
            round_metrics[-1]["bottom5_avg_acc"] if round_metrics else None
        ),
        # Test set metrics
        "test_overall_acc": test_overall,
        "test_worst_cluster_acc": (
            min(test_acc_values) if test_acc_values else None
        ),
        "test_cluster_acc_std": (
            float(np.std(test_acc_values)) if test_acc_values else None
        ),
        "test_per_cluster_acc": test_accs,
        # Inference latency
        "test_inference_per_sample_ms": test_per_sample_ms,
        "test_num_samples": test_num_samples,
    }
    write_json_file(str(exp_dir / "experiment_summary.json"), summary)
    print(f"\nExperiment summary saved to: {exp_dir / 'experiment_summary.json'}")
    print("Done!")


# ==================== CLI ====================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run a bandit strategy ablation experiment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Available strategies:\n"
            + "\n".join(f"  {k}" for k in sorted(EXPERIMENT_CONFIGS.keys()))
        ),
    )
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=list(EXPERIMENT_CONFIGS.keys()),
        help="Strategy name to run.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42).",
    )
    parser.add_argument(
        "--mutation",
        type=str,
        choices=["on", "off"],
        default="on",
        help="Enable or disable payload mutation (default: on).",
    )
    parser.add_argument(
        "--base_model",
        type=str,
        required=True,
        help="Path to the base model (e.g. Qwen2.5-Coder-1.5B-Instruct).",
    )
    parser.add_argument(
        "--output_root",
        type=str,
        required=True,
        help="Root directory for all ablation outputs.",
    )
    parser.add_argument(
        "--gpu",
        type=str,
        default=None,
        help='Comma-separated GPU IDs (e.g. "6,7").',
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Distributed training main process port.",
    )
    parser.add_argument(
        "--num_rounds",
        type=int,
        default=NUM_ROUNDS,
        help=f"Number of training rounds (default: {NUM_ROUNDS}).",
    )
    parser.add_argument(
        "--start_round",
        type=int,
        default=0,
        help="Round to resume from (default: 0). Previous rounds must be completed.",
    )
    parser.add_argument(
        "--schema_mode",
        type=str,
        choices=["aware", "free"],
        default="aware",
        help=(
            "Schema treatment in generated training data (default: aware). "
            "'aware' includes the real database DDL; 'free' replaces the "
            "schema slot with the literal string 'N/A' (context-free training)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    setup_logging()
    args = parse_args()

    # Set CUDA_VISIBLE_DEVICES before any CUDA init
    if args.gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
        print(f"CUDA_VISIBLE_DEVICES = {args.gpu}")

    run_single_experiment(
        strategy_name=args.strategy,
        seed=args.seed,
        enable_mutation=(args.mutation == "on"),
        base_model_path=args.base_model,
        output_root=args.output_root,
        gpu=args.gpu,
        port=args.port,
        num_rounds=args.num_rounds,
        start_round=args.start_round,
        schema_mode=args.schema_mode,
    )


if __name__ == "__main__":
    main()
