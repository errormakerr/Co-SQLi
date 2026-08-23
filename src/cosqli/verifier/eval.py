"""
Evaluation utilities for the Verifier module.

Provides functions to cluster inference results by the canonical
technique / reference-scope / comment-state tuple.
- Compute per-cluster accuracy statistics.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from cosqli.utils.cluster import get_single_key_of_injection_sql
from cosqli.utils.json_operation import read_jsonl_file


# ---------------------------------------------------------------------------
# Cluster statistics dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClusterStat:
    """Per-cluster accuracy, false-negative, and false-positive statistics."""

    acc: float
    total: int
    correct: int
    false_negatives: int
    false_positives: int


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _get_single_key_of_result(data_item: Dict[str, Any]) -> str:
    """
    Generate the cluster key for a single inference result.

    Benign (label=True) items are mapped to the fixed benign key.

    Args:
        data_item: A single inference result dictionary, expected to contain
                   canonical taxonomy fields when ``label`` is false.

    Returns:
        A canonical three-part attack key or the fixed benign key.
    """
    return get_single_key_of_injection_sql(data_item)


def cluster_results(datas: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group a list of inference result dicts by their cluster key.

    Args:
        datas: List of inference result dictionaries.

    Returns:
        Dict mapping each cluster key to its list of matching result dicts.
    """
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for item in datas:
        key = _get_single_key_of_result(item)
        clusters.setdefault(key, []).append(item)
    return clusters


# ---------------------------------------------------------------------------
# Accuracy computation
# ---------------------------------------------------------------------------

def compute_cluster_acc(
    clusters: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, ClusterStat]:
    """
    Compute per-cluster accuracy.

    ``ACC = #correct / #total``. For attack clusters, a false negative is a
    malicious example that the model explicitly classifies as ``"benign"``.

    Args:
        clusters: Dict mapping cluster keys to lists of result dicts,
                  as returned by :func:`cluster_results`.

    Returns:
        Dict mapping each cluster key to a :class:`ClusterStat` instance.
    """
    stats: Dict[str, ClusterStat] = {}
    for key, items in clusters.items():
        total = len(items)
        correct = sum(1 for item in items if item.get("is_correct"))
        acc = correct / total if total > 0 else 0.0
        false_negatives = sum(
            1
            for item in items
            if not item.get("label", True)
            and item.get("predicted_answer") == "benign"
        )
        false_positives = sum(
            1
            for item in items
            if item.get("label", False)
            and item.get("predicted_answer") == "malicious"
        )
        stats[key] = ClusterStat(
            acc=acc,
            total=total,
            correct=correct,
            false_negatives=false_negatives,
            false_positives=false_positives,
        )
    return stats


# ---------------------------------------------------------------------------
# CLI entry point (for quick inspection)
# ---------------------------------------------------------------------------

def main() -> None:
    """Print per-cluster accuracy for a results JSONL file."""
    file_path = "data/temp_data/results.jsonl"
    datas = read_jsonl_file(file_path)
    if not datas:
        print(f"No data loaded from {file_path!r}. Check the file path or content.")
        return

    clusters = cluster_results(datas)
    print(f"Found {len(clusters)} cluster(s).")

    stats = compute_cluster_acc(clusters)
    print("\n==== Per-Cluster Accuracy ====")
    for key, stat in stats.items():
        print(f"{key}:  ACC={stat.acc:.3f}  ({stat.correct}/{stat.total})")


if __name__ == "__main__":
    main()
