"""
Evaluation utilities for the Verifier module.

Provides functions to:
- Cluster inference results by their attack-type / annotator /
  information-feature / comment combination.
- Compute per-cluster accuracy statistics.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from utils.cluster import NORMAL_CLUSTER_KEY, str_to_bool
from utils.json_operation import read_jsonl_file


# ---------------------------------------------------------------------------
# Cluster statistics dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClusterStat:
    """Per-cluster accuracy statistics."""

    acc: float
    total: int
    correct: int


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _get_single_key_of_result(data_item: Dict[str, Any]) -> str:
    """
    Generate the cluster key for a single inference result.

    Benign (label=True) items are mapped to the fixed key
    ``"normal||normal||normal||normal"``.

    Args:
        data_item: A single inference result dictionary, expected to contain
                   ``label``, ``type``, ``annotator``, ``information_features``,
                   and ``comment`` fields.

    Returns:
        A ``"type||annotator||information_features||comment"`` cluster key,
        or the fixed benign key for normal samples.
    """
    if not data_item["label"]:
        attack_type = data_item["type"]
        annotator = data_item["annotator"]
        if isinstance(annotator, str):
            annotator = str_to_bool(annotator)
        info_features = data_item["information_features"]
        comment = data_item.get("comment")
        if isinstance(comment, str):
            comment = str_to_bool(comment)
        return f"{attack_type}||{annotator}||{info_features}||{comment}"
    return NORMAL_CLUSTER_KEY


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

    ``ACC = #correct / #total``

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
        stats[key] = ClusterStat(acc=acc, total=total, correct=correct)
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
