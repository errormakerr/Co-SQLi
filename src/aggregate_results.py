"""
Aggregate Ablation Results

Scans the output directory for ``experiment_summary.json`` files, groups
them by strategy + mutation setting, and computes mean ± std for key metrics.

Usage::

    python src/aggregate_results.py --results_dir /path/to/ablation_results
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


def load_summaries(results_dir: str) -> List[Dict[str, Any]]:
    """Load all experiment_summary.json files from subdirectories."""
    summaries: List[Dict[str, Any]] = []
    root = Path(results_dir)
    for summary_path in sorted(root.glob("*/experiment_summary.json")):
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_dir"] = str(summary_path.parent.name)
        summaries.append(data)
    return summaries


def aggregate(summaries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group summaries by strategy+mutation and compute aggregate statistics."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in summaries:
        mut_tag = "mutON" if s.get("mutation", True) else "mutOFF"
        key = f"{s['strategy']}_{mut_tag}"
        groups[key].append(s)

    agg: Dict[str, Dict[str, Any]] = {}
    for key, group in sorted(groups.items()):
        # Validation metrics
        val_acc = [s["final_overall_acc"] for s in group if s.get("final_overall_acc") is not None]
        val_worst = [s["final_worst_cluster_acc"] for s in group if s.get("final_worst_cluster_acc") is not None]
        val_std = [s["final_cluster_acc_std"] for s in group if s.get("final_cluster_acc_std") is not None]
        val_bottom5 = [s["final_bottom5_avg"] for s in group if s.get("final_bottom5_avg") is not None]

        # Test metrics
        test_acc = [s["test_overall_acc"] for s in group if s.get("test_overall_acc") is not None]
        test_worst = [s["test_worst_cluster_acc"] for s in group if s.get("test_worst_cluster_acc") is not None]
        test_std = [s["test_cluster_acc_std"] for s in group if s.get("test_cluster_acc_std") is not None]

        def _stat(vals):
            if not vals:
                return {"mean": None, "std": None, "n": 0}
            return {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals)),
                "n": len(vals),
            }

        agg[key] = {
            "n_experiments": len(group),
            "seeds": [s.get("seed") for s in group],
            "val_overall_acc": _stat(val_acc),
            "val_worst_cluster": _stat(val_worst),
            "val_cluster_std": _stat(val_std),
            "val_bottom5_avg": _stat(val_bottom5),
            "test_overall_acc": _stat(test_acc),
            "test_worst_cluster": _stat(test_worst),
            "test_cluster_std": _stat(test_std),
        }

    return agg


def print_table(agg: Dict[str, Dict[str, Any]]) -> None:
    """Print a formatted results table to stdout."""
    header = (
        f"{'Strategy':<25s}  "
        f"{'Val Acc (%)':>14s}  "
        f"{'Test Acc (%)':>14s}  "
        f"{'Test Worst (%)':>14s}  "
        f"{'Test Std':>10s}  "
        f"{'N':>3s}"
    )
    print("\n" + "=" * len(header))
    print(header)
    print("-" * len(header))

    for key, data in sorted(agg.items()):
        def _fmt(stat):
            if stat["mean"] is None:
                return f"{'—':>14s}"
            return f"{stat['mean']*100:6.2f} ± {stat['std']*100:5.2f}"

        line = (
            f"{key:<25s}  "
            f"{_fmt(data['val_overall_acc']):>14s}  "
            f"{_fmt(data['test_overall_acc']):>14s}  "
            f"{_fmt(data['test_worst_cluster']):>14s}  "
        )
        test_std = data["test_cluster_std"]
        if test_std["mean"] is not None:
            line += f"{test_std['mean']:.4f}     "
        else:
            line += f"{'—':>10s}  "
        line += f"{data['n_experiments']:3d}"
        print(line)

    print("=" * len(header))


def extract_convergence(summaries: List[Dict[str, Any]]) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Extract per-round metrics for convergence analysis.

    Returns:
        Dict mapping ``strategy_mutTag`` → ``{round_idx: {metric_name: [values]}}``
    """
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in summaries:
        mut_tag = "mutON" if s.get("mutation", True) else "mutOFF"
        key = f"{s['strategy']}_{mut_tag}"
        groups[key].append(s)

    convergence: Dict[str, Dict[int, Dict[str, list]]] = {}
    for key, group in groups.items():
        per_round: Dict[int, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for s in group:
            for m in s.get("round_metrics", []):
                r = m["round"]
                per_round[r]["overall_acc"].append(m["overall_acc"])
                per_round[r]["worst_cluster_acc"].append(m["worst_cluster_acc"])
                per_round[r]["cluster_acc_std"].append(m["cluster_acc_std"])

        # Compute mean ± std per round
        convergence[key] = {}
        for r, metrics in sorted(per_round.items()):
            convergence[key][r] = {
                name: {
                    "mean": float(np.mean(vals)),
                    "std": float(np.std(vals)),
                }
                for name, vals in metrics.items()
            }

    return convergence


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate ablation results.")
    parser.add_argument(
        "--results_dir",
        type=str,
        required=True,
        help="Root directory containing experiment output folders.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write aggregated_results.json (default: results_dir/aggregated_results.json).",
    )
    args = parser.parse_args()

    summaries = load_summaries(args.results_dir)
    if not summaries:
        print(f"No experiment_summary.json files found in {args.results_dir}")
        return

    print(f"Found {len(summaries)} experiment(s)")

    agg = aggregate(summaries)
    convergence = extract_convergence(summaries)

    print_table(agg)

    # Save to JSON
    output_path = args.output or os.path.join(args.results_dir, "aggregated_results.json")
    result = {
        "aggregate": agg,
        "convergence": convergence,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nAggregated results saved to: {output_path}")


if __name__ == "__main__":
    main()
