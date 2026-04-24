"""
Cluster Selection Strategy — Base Classes

Provides:
- ``SelectionResult``: dataclass carrying the output of a strategy's ``select()``
  call, ready to be passed into ``Attacker.generate_training_sqls()``.
- ``ClusterSelector``: abstract base class that all concrete strategies extend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.cluster import NORMAL_CLUSTER_KEY


# ---------------------------------------------------------------------------
# Selection result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SelectionResult:
    """Result of a strategy's ``select()`` call.

    Attributes:
        selected_clusters:    The *k* injection cluster keys chosen for this
                              round.
        cluster_probabilities: Full probability distribution over **all**
                              clusters (including the normal cluster).  Used by
                              ``Attacker`` to compute the injection/normal
                              sample ratio and for logging.
        cluster_weights:      Per-cluster weights used for mutation-coupling
                              (higher weight → higher effective mutation
                              probability).
    """

    selected_clusters: List[str]
    cluster_probabilities: Dict[str, float]
    cluster_weights: Dict[str, float]


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class ClusterSelector(ABC):
    """Abstract base class for cluster selection strategies.

    Life-cycle::

        selector = SomeSelector(cluster_list, **params)
        for round_idx in range(R):
            result = selector.select(k=8, round_idx=round_idx)
            # ... Attacker generates data, Defender trains & infers ...
            selector.update(cluster_accuracies)

    Args:
        cluster_list: Complete list of cluster key strings (including the
                      normal cluster ``NORMAL_CLUSTER_KEY``), typically
                      obtained from ``cluster_injection_sqls()``.
    """

    def __init__(self, cluster_list: List[str]) -> None:
        self.cluster_list = cluster_list
        self.injection_clusters = [
            c for c in cluster_list if c != NORMAL_CLUSTER_KEY
        ]
        self.N = len(cluster_list)           # Total clusters including normal (49)
        self.K = len(self.injection_clusters) # Injection clusters only (48)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def select(self, k: int, round_idx: int) -> SelectionResult:
        """Select *k* injection clusters for this training round.

        Args:
            k:         Number of clusters to select.
            round_idx: Zero-based round index (may be used for scheduling).

        Returns:
            A ``SelectionResult`` instance.
        """
        ...

    @abstractmethod
    def update(self, cluster_accuracies: Dict[str, float]) -> None:
        """Receive per-cluster accuracy from the latest evaluation round.

        Args:
            cluster_accuracies: Mapping from cluster key to accuracy
                                (float in [0, 1]).  May not contain entries
                                for every cluster.
        """
        ...

    # ------------------------------------------------------------------
    # Serialisation helpers (for breakpoint recovery and logging)
    # ------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of the strategy's internal state."""
        return {}

    def set_state(self, state: Dict[str, Any]) -> None:
        """Restore internal state from a previously saved snapshot."""
        pass

    # ------------------------------------------------------------------
    # Utility: build a full probability distribution
    # ------------------------------------------------------------------

    def _build_probabilities(
        self, injection_probs: Dict[str, float]
    ) -> Dict[str, float]:
        """Build a full probability distribution from injection-only probs.

        Fixes ``p(normal) = 1/N`` and scales the injection probabilities so
        that the total sums to 1.  This ensures that the injection/normal
        sample ratio is identical across all strategies (controlled variable).

        Args:
            injection_probs: Raw (un-normalised) probability scores for
                             injection clusters only.

        Returns:
            Dict mapping **every** cluster key (including normal) to its
            probability.  Sums to 1.0.
        """
        total = sum(injection_probs.values())
        if total <= 0:
            # Uniform fallback
            uniform_inj = 1.0 / self.K if self.K > 0 else 0.0
            normalized = {c: uniform_inj for c in self.injection_clusters}
        else:
            normalized = {c: p / total for c, p in injection_probs.items()}

        # Scale injection probabilities so they sum to (N-1)/N
        scale = (self.N - 1) / self.N if self.N > 0 else 0.0
        probs: Dict[str, float] = {c: p * scale for c, p in normalized.items()}
        probs[NORMAL_CLUSTER_KEY] = 1.0 / self.N if self.N > 0 else 0.0
        return probs
