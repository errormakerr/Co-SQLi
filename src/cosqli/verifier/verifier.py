"""
Verifier Module

The Verifier updates the Multi-Armed Bandit (MAB) reward and weight for each
attack cluster based on the Defender's evaluation results.

Reward:  ``reward[k] = (FN[k] + alpha) / (n[k] + alpha + beta)``
          (higher reward = more missed attacks)
Because validation observes every attack cluster in each round, weight updates
use centered full-information exponential weighting:
    ``weight[k] *= exp(learning_rate * (reward[k] - mean_reward))``
"""

from __future__ import annotations

import math
from typing import Dict, List

from cosqli.utils.cluster import (
    NORMAL_CLUSTER_KEY,
)
from .eval import cluster_results, compute_cluster_acc


REWARD_SMOOTHING_ALPHA = 1.0
"""Additive prior for false-negative rewards, matching the paper default."""

REWARD_SMOOTHING_BETA = 1.0
"""Denominator prior for false-negative rewards, matching the paper default."""

DEFAULT_BENIGN_RATIO = 0.25
"""Initial share of benign samples in a training round."""

BENIGN_RATIO_MIN = 0.15
"""Lower bound for the benign-ratio controller."""

BENIGN_RATIO_MAX = 0.35
"""Upper bound for the benign-ratio controller."""

BENIGN_FPR_TARGET = 0.05
"""Target smoothed false-positive rate for benign validation examples."""

BENIGN_RATIO_STEP_SIZE = 0.5
"""Controller gain applied to the benign false-positive error."""

BENIGN_ERROR_EMA_DECAY = 0.7
"""Exponential-moving-average decay for benign false-positive feedback."""


class Verifier:
    """
    Maintains and updates per-cluster MAB weights.

    Attributes:
        cluster_list:    Ordered list of attack-cluster keys.
        cluster_rewards: Latest per-cluster smoothed false-negative reward.
        cluster_weight:  Current MAB weight for each cluster.
        last_reward_baseline: Mean reward used by the latest weight update.
        benign_ratio:    Next-round benign sample share.
        benign_error_ema: Smoothed benign false-positive error.
    """

    def __init__(
        self,
        cluster_list: List[str],
        benign_ratio: float = DEFAULT_BENIGN_RATIO,
    ) -> None:
        """
        Initialise the Verifier with uniform weights.

        Args:
            cluster_list: List of attack-only cluster key strings. Benign
                          samples are handled separately from the MAB.
            benign_ratio: Initial benign sample share for the ratio controller.
        """
        if not cluster_list:
            raise ValueError("cluster_list must not be empty")
        if NORMAL_CLUSTER_KEY in cluster_list:
            raise ValueError(
                "cluster_list must contain attack clusters only; "
                "the benign cluster is not a sampled attack cluster"
            )
        self._validate_benign_ratio(benign_ratio)
        self.cluster_list = list(cluster_list)
        self.cluster_rewards: Dict[str, float] = {k: 0.0 for k in cluster_list}
        self.cluster_weight: Dict[str, float] = {k: 1.0 for k in cluster_list}
        self.last_reward_baseline = 0.0
        self.benign_ratio = float(benign_ratio)
        self.benign_error_ema = 0.0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_weights(self) -> Dict[str, float]:
        """Return the current cluster weight dictionary."""
        return self.cluster_weight

    def get_benign_ratio(self) -> float:
        """Return the benign sample share for the next training round."""
        return self.benign_ratio

    def get_last_reward_baseline(self) -> float:
        """Return the mean reward used by the latest centered update."""
        return self.last_reward_baseline

    def get_benign_state(self) -> Dict[str, float]:
        """Return the serialisable benign-ratio controller state."""
        return {
            "benign_ratio": self.benign_ratio,
            "benign_error_ema": self.benign_error_ema,
        }

    def set_weights(self, weights: Dict[str, float]) -> None:
        """
        Directly overwrite cluster weights (used for breakpoint recovery).

        Args:
            weights: Dict mapping cluster keys to new weight values.
        """
        expected_keys = set(self.cluster_list)
        supplied_keys = set(weights)
        if supplied_keys != expected_keys:
            missing = sorted(expected_keys.difference(supplied_keys))
            unexpected = sorted(supplied_keys.difference(expected_keys))
            details = []
            if missing:
                details.append(f"missing={missing}")
            if unexpected:
                details.append(f"unexpected={unexpected}")
            raise ValueError(
                "MAB weight keys do not match attack clusters: "
                + "; ".join(details)
            )
        self.cluster_weight = {
            key: float(weights[key]) for key in self.cluster_list
        }

    def set_benign_state(
        self,
        benign_ratio: float,
        benign_error_ema: float,
    ) -> None:
        """Restore a previously persisted benign-ratio controller state."""
        self._validate_benign_ratio(benign_ratio)
        if not 0.0 <= benign_error_ema <= 1.0:
            raise ValueError(
                "benign_error_ema must be in [0, 1], "
                f"got {benign_error_ema}"
            )
        self.benign_ratio = float(benign_ratio)
        self.benign_error_ema = float(benign_error_ema)

    # ------------------------------------------------------------------
    # Update cycle
    # ------------------------------------------------------------------

    def update_reward(self, results: List[Dict]) -> None:
        """
        Compute smoothed false-negative rewards from inference results.

        For each attack cluster *k*:

        ``reward[k] = (FN[k] + alpha) / (n[k] + alpha + beta)``

        ``FN[k]`` counts malicious examples explicitly predicted as benign.
        All MAB arms must appear in the validation results; otherwise the
        update would confuse missing feedback with a low error rate.

        Args:
            results: List of inference result dicts as returned by the
                     Defender's ``run_inference()`` method.
        """
        clusters = cluster_results(results)
        cluster_stats = compute_cluster_acc(clusters)
        missing_clusters = [
            key for key in self.cluster_list if key not in cluster_stats
        ]
        if missing_clusters:
            raise ValueError(
                "Validation results are missing MAB attack clusters: "
                + ", ".join(missing_clusters)
            )

        for key in self.cluster_list:
            stat = cluster_stats[key]
            self.cluster_rewards[key] = (
                stat.false_negatives + REWARD_SMOOTHING_ALPHA
            ) / (
                stat.total
                + REWARD_SMOOTHING_ALPHA
                + REWARD_SMOOTHING_BETA
            )

    def update_weight(
        self,
        learning_rate: float,
    ) -> None:
        """
        Apply a centered full-information exponential weight update.

        Formula:
            ``mean_reward = average(reward[k] for k in clusters)``
            ``weight[k] *= exp(learning_rate * (reward[k] - mean_reward))``

        ``update_reward`` requires validation feedback for every MAB arm.
        Importance weighting by the attacker's sampling probability is therefore
        inappropriate here: it is needed only when an arm's reward is observed
        exclusively because that arm was sampled. Centering makes the update
        explicitly relative to the round-wide reward baseline, increasing
        weights above the mean and decreasing weights below it.

        Args:
            learning_rate: Positive exponentiated-gradient learning rate.
        """
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError(
                f"learning_rate must be finite and positive, got {learning_rate}"
            )
        self.last_reward_baseline = math.fsum(
            self.cluster_rewards.get(key, 0.0) for key in self.cluster_list
        ) / len(self.cluster_list)
        for key, weight in self.cluster_weight.items():
            reward = self.cluster_rewards.get(key, 0.0)
            self.cluster_weight[key] = weight * math.exp(
                learning_rate * (reward - self.last_reward_baseline)
            )

    def update_benign_ratio(self, results: List[Dict]) -> float:
        """Update the next-round benign share from smoothed benign FPR.

        The controller follows the paper's benign feedback path:

        ``e = (FP + alpha) / (n + alpha + beta)``
        ``ema = decay * ema + (1 - decay) * e``
        ``rho = clip(rho + step * (ema - target), rho_min, rho_max)``

        Args:
            results: Per-sample Defender inference results for the validation
                set, including benign examples.

        Returns:
            The updated benign ratio for the next training round.
        """
        clusters = cluster_results(results)
        cluster_stats = compute_cluster_acc(clusters)
        benign_stat = cluster_stats.get(NORMAL_CLUSTER_KEY)
        if benign_stat is None:
            raise ValueError(
                "Validation results are missing benign examples required for "
                "benign-ratio control"
            )

        benign_error = (
            benign_stat.false_positives + REWARD_SMOOTHING_ALPHA
        ) / (
            benign_stat.total
            + REWARD_SMOOTHING_ALPHA
            + REWARD_SMOOTHING_BETA
        )
        self.benign_error_ema = (
            BENIGN_ERROR_EMA_DECAY * self.benign_error_ema
            + (1.0 - BENIGN_ERROR_EMA_DECAY) * benign_error
        )
        proposed_ratio = self.benign_ratio + BENIGN_RATIO_STEP_SIZE * (
            self.benign_error_ema - BENIGN_FPR_TARGET
        )
        self.benign_ratio = min(
            max(proposed_ratio, BENIGN_RATIO_MIN),
            BENIGN_RATIO_MAX,
        )
        return self.benign_ratio

    @staticmethod
    def _validate_benign_ratio(benign_ratio: float) -> None:
        if not BENIGN_RATIO_MIN <= benign_ratio <= BENIGN_RATIO_MAX:
            raise ValueError(
                "benign_ratio must be in "
                f"[{BENIGN_RATIO_MIN}, {BENIGN_RATIO_MAX}], got {benign_ratio}"
            )
