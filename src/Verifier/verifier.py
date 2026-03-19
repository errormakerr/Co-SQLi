"""
Verifier Module

The Verifier updates the Multi-Armed Bandit (MAB) reward and weight for each
attack cluster based on the Defender's evaluation results.

Reward:  ``reward[k] = 1 - accuracy[k]``  (higher reward = harder cluster)
Weight update uses the standard EXP3 formula:
    ``weight[k] *= exp(gamma / n * reward[k] / prob[k])``

where *n* is the total number of clusters and *prob[k]* is the probability
assigned to cluster *k* in the previous Attacker round.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List

from utils.cluster import cluster_injection_sqls
from utils.json_operation import read_json_file, read_jsonl_file
from .eval import cluster_results, compute_cluster_acc


class Verifier:
    """
    Maintains and updates per-cluster MAB weights.

    Attributes:
        cluster_list:    Ordered list of all known cluster keys.
        cluster_rewards: Latest per-cluster reward (1 - accuracy).
        cluster_weight:  Current MAB weight for each cluster.
    """

    def __init__(self, cluster_list: List[str]) -> None:
        """
        Initialise the Verifier with uniform weights.

        Args:
            cluster_list: List of all cluster key strings (including the
                          ``"normal||normal||normal||normal"`` key for benign
                          samples).
        """
        self.cluster_list = list(cluster_list)
        self.cluster_rewards: Dict[str, float] = {k: 0.0 for k in cluster_list}
        self.cluster_weight: Dict[str, float] = {k: 1.0 for k in cluster_list}

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_weights(self) -> Dict[str, float]:
        """Return the current cluster weight dictionary."""
        return self.cluster_weight

    def set_weights(self, weights: Dict[str, float]) -> None:
        """
        Directly overwrite cluster weights (used for breakpoint recovery).

        Args:
            weights: Dict mapping cluster keys to new weight values.
        """
        self.cluster_weight = weights

    # ------------------------------------------------------------------
    # Update cycle
    # ------------------------------------------------------------------

    def update_reward(self, results: List[Dict]) -> None:
        """
        Compute per-cluster rewards from inference results and store them.

        For each cluster *k*:  ``reward[k] = 1 - accuracy[k]``

        Args:
            results: List of inference result dicts as returned by the
                     Defender's ``run_inference()`` method.
        """
        clusters = cluster_results(results)
        cluster_stats = compute_cluster_acc(clusters)
        for key, stat in cluster_stats.items():
            self.cluster_rewards[key] = 1.0 - stat.acc

    def update_weight(
        self,
        gamma: float,
        cluster_probability_distribution: Dict[str, float],
    ) -> None:
        """
        Apply the EXP3 weight-update rule for all clusters.

        Formula:
            ``weight[k] *= exp(gamma / n * reward[k] / prob[k])``

        Args:
            gamma: EXP3 learning-rate parameter.
            cluster_probability_distribution: Probability distribution used
                by the Attacker in the most recent round (needed to normalise
                the reward signal).
        """
        n = len(self.cluster_list)
        for key, weight in self.cluster_weight.items():
            prob = cluster_probability_distribution.get(key, 1.0 / max(n, 1))
            reward = self.cluster_rewards.get(key, 0.0)
            if prob > 0:
                self.cluster_weight[key] = weight * math.exp(
                    (gamma / n) * (reward / prob)
                )


# ---------------------------------------------------------------------------
# CLI entry point (for quick inspection / debugging)
# ---------------------------------------------------------------------------

def main() -> None:
    """Run a single reward + weight update cycle on sample data."""
    project_root = Path(__file__).resolve().parents[2]
    results_file = project_root / "data" / "temp_data" / "round_0" / "inference" / "results.jsonl"
    test_sqls_file = project_root / "data" / "benchmark" / "test_sqls.json"

    results = read_jsonl_file(str(results_file))
    cluster_list = list(
        cluster_injection_sqls(read_json_file(str(test_sqls_file))).keys()
    )

    n = len(cluster_list)
    init_prob = 1.0 / n
    clusters_prob = {k: init_prob for k in cluster_list}

    verifier = Verifier(cluster_list=cluster_list)
    verifier.update_reward(results=results)

    print("=== Per-cluster rewards ===")
    for key, reward in verifier.cluster_rewards.items():
        print(f"  {key}: {reward:.4f}")

    verifier.update_weight(gamma=0.5, cluster_probability_distribution=clusters_prob)

    print("\n=== Updated cluster weights ===")
    for key, weight in verifier.cluster_weight.items():
        print(f"  {key}: {weight:.4f}")


if __name__ == "__main__":
    main()
