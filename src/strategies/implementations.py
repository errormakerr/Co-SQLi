"""
Cluster Selection Strategies — Concrete Implementations

Five strategies forming a spectrum from "no feedback" to "theory-guided":

1. **UniformRandomSelector**  — No feedback (baseline).
2. **GreedyTopKSelector**     — Simple heuristic, pure exploitation.
3. **SoftmaxProportionalSelector** — Simple heuristic with exploration.
4. **ThompsonSamplingSelector** — Stochastic bandit (Beta-Bernoulli).
5. **EXP3Selector**           — Adversarial bandit (current approach).
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional

import numpy as np

from utils.cluster import NORMAL_CLUSTER_KEY
from .base import ClusterSelector, SelectionResult

# Default accuracy assumed for clusters absent from evaluation results.
_DEFAULT_ACC = 0.5


# ========================================================================
# (A) Uniform Random — No feedback baseline
# ========================================================================

class UniformRandomSelector(ClusterSelector):
    """Uniformly random cluster selection with no feedback utilisation.

    Every round, *k* clusters are sampled uniformly without replacement.
    ``update()`` is a no-op.
    """

    def select(self, k: int, round_idx: int) -> SelectionResult:
        selected = random.sample(self.injection_clusters, k)
        probs = {c: 1.0 / self.N for c in self.cluster_list}
        weights = {c: 1.0 for c in self.cluster_list}
        return SelectionResult(selected, probs, weights)

    def update(self, cluster_accuracies: Dict[str, float]) -> None:
        pass  # Stateless

    def get_state(self) -> Dict[str, Any]:
        return {"strategy": "uniform"}


# ========================================================================
# (B) Greedy Top-K — Pure exploitation
# ========================================================================

class GreedyTopKSelector(ClusterSelector):
    """Deterministically select the *k* clusters with the lowest accuracy.

    Falls back to uniform random on the first round (no accuracy data yet).
    """

    def __init__(self, cluster_list: List[str]) -> None:
        super().__init__(cluster_list)
        self._last_accs: Optional[Dict[str, float]] = None

    def select(self, k: int, round_idx: int) -> SelectionResult:
        if self._last_accs is None:
            # First round: no accuracy info → uniform random
            selected = random.sample(self.injection_clusters, k)
        else:
            # Sort by accuracy ascending (weakest first), take top-k
            sorted_clusters = sorted(
                self.injection_clusters,
                key=lambda c: self._last_accs.get(c, _DEFAULT_ACC),
            )
            selected = sorted_clusters[:k]

        weights = self._build_weights()
        injection_probs = self._build_injection_scores()
        probs = self._build_probabilities(injection_probs)
        return SelectionResult(selected, probs, weights)

    def update(self, cluster_accuracies: Dict[str, float]) -> None:
        self._last_accs = cluster_accuracies.copy()

    def get_state(self) -> Dict[str, Any]:
        return {"strategy": "greedy", "last_accs": self._last_accs}

    def set_state(self, state: Dict[str, Any]) -> None:
        self._last_accs = state.get("last_accs")

    # -- helpers --

    def _build_weights(self) -> Dict[str, float]:
        if self._last_accs is None:
            return {c: 1.0 for c in self.cluster_list}
        weights = {
            c: max(1.0 - self._last_accs.get(c, _DEFAULT_ACC), 0.01)
            for c in self.injection_clusters
        }
        weights[NORMAL_CLUSTER_KEY] = 1.0
        return weights

    def _build_injection_scores(self) -> Dict[str, float]:
        if self._last_accs is None:
            return {c: 1.0 for c in self.injection_clusters}
        return {
            c: max(1.0 - self._last_accs.get(c, _DEFAULT_ACC), 0.01)
            for c in self.injection_clusters
        }


# ========================================================================
# (C) Softmax Proportional — Heuristic with tuneable exploration
# ========================================================================

class SoftmaxProportionalSelector(ClusterSelector):
    """Sample clusters proportionally to ``softmax((1 - acc) / τ)``.

    The temperature *τ* controls the exploration–exploitation trade-off:
    - ``τ → 0``:  degenerates to greedy (pure exploitation).
    - ``τ → ∞``:  degenerates to uniform (pure exploration).

    Falls back to uniform random on the first round (no accuracy data yet).

    Args:
        cluster_list: Complete cluster key list.
        temperature:  Softmax temperature (default 0.3).
    """

    def __init__(self, cluster_list: List[str], temperature: float = 0.3) -> None:
        super().__init__(cluster_list)
        self.temperature = temperature
        self._last_accs: Optional[Dict[str, float]] = None

    def select(self, k: int, round_idx: int) -> SelectionResult:
        if self._last_accs is None:
            selected = random.sample(self.injection_clusters, k)
            probs = {c: 1.0 / self.N for c in self.cluster_list}
            weights = {c: 1.0 for c in self.cluster_list}
            return SelectionResult(selected, probs, weights)

        # Compute softmax over (1 - acc) / temperature
        scores = np.array([
            1.0 - self._last_accs.get(c, _DEFAULT_ACC)
            for c in self.injection_clusters
        ])
        scores = scores - scores.max()  # Numerical stability
        exp_scores = np.exp(scores / self.temperature)
        softmax_probs = exp_scores / exp_scores.sum()

        # Weighted sampling without replacement
        indices = np.random.choice(
            len(self.injection_clusters), size=k, replace=False, p=softmax_probs,
        )
        selected = [self.injection_clusters[i] for i in indices]

        # Build full probability distribution
        injection_probs = {
            self.injection_clusters[i]: float(softmax_probs[i])
            for i in range(len(self.injection_clusters))
        }
        probs = self._build_probabilities(injection_probs)

        # Weights for mutation coupling (same semantics as Greedy)
        weights = {
            c: max(1.0 - self._last_accs.get(c, _DEFAULT_ACC), 0.01)
            for c in self.injection_clusters
        }
        weights[NORMAL_CLUSTER_KEY] = 1.0

        return SelectionResult(selected, probs, weights)

    def update(self, cluster_accuracies: Dict[str, float]) -> None:
        self._last_accs = cluster_accuracies.copy()

    def get_state(self) -> Dict[str, Any]:
        return {
            "strategy": "softmax",
            "temperature": self.temperature,
            "last_accs": self._last_accs,
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        self._last_accs = state.get("last_accs")


# ========================================================================
# (D) Thompson Sampling — Stochastic bandit (Beta-Bernoulli)
# ========================================================================

class ThompsonSamplingSelector(ClusterSelector):
    """Thompson Sampling with Beta(a, b) posteriors and exponential decay.

    Each injection cluster maintains a ``Beta(a, b)`` distribution.  On each
    round, a sample ``θ_c ~ Beta(a_c, b_c)`` is drawn and the top-*k*
    clusters are selected.  This matches Eq. (eq:thompson) in the paper; we
    use the lowercase ``a, b`` rather than the conventional Greek
    ``α, β`` to avoid collision with the ambiguity ratio ``α`` (Def. 4 in
    the paper) and the taxonomy annotator ``α_ann``.

    After evaluation, ``a`` and ``b`` are updated via the batch-weighted
    decayed Bayesian update of Eq. (eq:thompson_update):

        a_c ← decay · a_c + (1 − acc_c) · n_c        # reward r_c = 1 − acc_c
        b_c ← decay · b_c + acc_c · n_c              # (1 − r_c) · n_c

    where ``n_c`` is the number of validation samples for cluster *c*
    (typically 20).  The decay factor makes the posterior "forget" old
    observations, adapting to the non-stationary reward signal.

    Args:
        cluster_list: Complete cluster key list.
        decay:        Exponential decay factor for posterior parameters
                      (default 0.7).
    """

    def __init__(self, cluster_list: List[str], decay: float = 0.7) -> None:
        super().__init__(cluster_list)
        self.decay = decay
        self.a: Dict[str, float] = {c: 1.0 for c in self.injection_clusters}
        self.b: Dict[str, float] = {c: 1.0 for c in self.injection_clusters}
        self._last_accs: Optional[Dict[str, float]] = None

    def select(self, k: int, round_idx: int) -> SelectionResult:
        # Sample from each cluster's Beta posterior
        samples = {
            c: np.random.beta(self.a[c], self.b[c])
            for c in self.injection_clusters
        }
        # Select top-k by sampled θ
        sorted_clusters = sorted(samples, key=samples.get, reverse=True)
        selected = sorted_clusters[:k]

        # Probability distribution from Beta means (for injection ratio calc)
        means = {
            c: self.a[c] / (self.a[c] + self.b[c])
            for c in self.injection_clusters
        }
        probs = self._build_probabilities(means)

        # Weights for mutation coupling (use 1-acc for consistency)
        if self._last_accs is not None:
            weights = {
                c: max(1.0 - self._last_accs.get(c, _DEFAULT_ACC), 0.01)
                for c in self.injection_clusters
            }
        else:
            weights = {c: 1.0 for c in self.injection_clusters}
        weights[NORMAL_CLUSTER_KEY] = 1.0

        return SelectionResult(selected, probs, weights)

    def update(self, cluster_accuracies: Dict[str, float]) -> None:
        self._last_accs = cluster_accuracies.copy()
        for c in self.injection_clusters:
            acc = cluster_accuracies.get(c, _DEFAULT_ACC)
            n = 20  # Each injection cluster has 20 samples in the validation set
            self.a[c] = self.decay * self.a[c] + (1.0 - acc) * n
            self.b[c] = self.decay * self.b[c] + acc * n

    def get_state(self) -> Dict[str, Any]:
        return {
            "strategy": "thompson",
            "decay": self.decay,
            "a": self.a.copy(),
            "b": self.b.copy(),
            "last_accs": self._last_accs,
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        # Accept both new ("a"/"b") and legacy ("alpha"/"beta") keys for
        # backward compatibility with pre-rename checkpoints.
        self.a = state.get("a", state.get("alpha"))
        self.b = state.get("b", state.get("beta"))
        self._last_accs = state.get("last_accs")


# ========================================================================
# (E) EXP3 — Adversarial bandit (current approach)
# ========================================================================

class EXP3Selector(ClusterSelector):
    """EXP3 (Exponential-weight algorithm for Exploration and Exploitation).

    This implementation consolidates the EXP3 logic currently split across
    ``Attacker._update_clusters_probability_distribution()`` and
    ``Verifier.update_weight()`` into a single self-contained class.

    **Behaviour must be byte-level identical** to the original code paths.

    Key correspondences to the original codebase:
    - Probability computation: ``attacker.py`` L200-212
    - Weight update:           ``verifier.py`` L102-109
    - **No two-phase strategy**: the original ``main.py`` switches to top-k
      for the last 2 rounds; this ablation strategy does NOT do that, to
      isolate pure EXP3 behaviour.

    Args:
        cluster_list: Complete cluster key list.
        gamma_a:      Exploration coefficient for probability calculation,
                      corresponding to ``γ_A`` in Eq. (eq:exp3_prob) of the
                      paper (default 0.7, matching ``ATTACKER_GAMMA``).
        gamma_v:      Learning rate for multiplicative weight updates,
                      corresponding to ``γ_V`` in Eq. (eq:exp3_weight) of
                      the paper (default 0.3, matching ``VERIFIER_GAMMA``).
    """

    def __init__(
        self,
        cluster_list: List[str],
        gamma_a: float = 0.7,
        gamma_v: float = 0.3,
    ) -> None:
        super().__init__(cluster_list)
        self.gamma_a = gamma_a
        self.gamma_v = gamma_v
        # Weight initialisation: all 1.0 (matches Verifier.__init__)
        self.weights: Dict[str, float] = {c: 1.0 for c in self.cluster_list}
        self._last_probs: Dict[str, float] = {}

    def select(self, k: int, round_idx: int) -> SelectionResult:
        # --- Probability calculation (mirrors attacker.py L187-212) ---
        total_weight = sum(self.weights.values())
        n = self.N

        if total_weight <= 0:
            probs = {c: 1.0 / n for c in self.cluster_list}
        else:
            probs = {
                c: (1.0 - self.gamma_a) * (self.weights[c] / total_weight)
                + self.gamma_a / n
                for c in self.cluster_list
            }
            # Normalise (matches attacker.py L205-212)
            dist_sum = sum(probs.values())
            if dist_sum > 0:
                probs = {c: p / dist_sum for c, p in probs.items()}
            else:
                probs = {c: 1.0 / n for c in self.cluster_list}

        self._last_probs = probs.copy()

        # --- Weighted sampling without replacement (mirrors attacker.py L252-258) ---
        non_normal = {
            c: p for c, p in probs.items() if c != NORMAL_CLUSTER_KEY
        }
        keys = list(non_normal.keys())
        p_arr = np.array(list(non_normal.values()), dtype=float)
        p_total = p_arr.sum()
        p_arr = p_arr / p_total if p_total > 0 else np.full(len(p_arr), 1.0 / len(p_arr))
        indices = np.random.default_rng().choice(
            len(keys), size=k, replace=False, p=p_arr,
        )
        selected = [keys[i] for i in indices]

        return SelectionResult(selected, probs, self.weights.copy())

    def update(self, cluster_accuracies: Dict[str, float]) -> None:
        # --- Reward computation (mirrors verifier.py L80-83) ---
        rewards: Dict[str, float] = {}
        for c in self.cluster_list:
            acc = cluster_accuracies.get(c, 0.0)
            rewards[c] = 1.0 - acc

        # --- Weight update (mirrors verifier.py L102-109) ---
        n = self.N
        for c in self.cluster_list:
            prob = self._last_probs.get(c, 1.0 / max(n, 1))
            reward = rewards.get(c, 0.0)
            if prob > 0:
                self.weights[c] = self.weights[c] * math.exp(
                    (self.gamma_v / n) * (reward / prob)
                )

    def get_state(self) -> Dict[str, Any]:
        return {
            "strategy": "exp3",
            "gamma_a": self.gamma_a,
            "gamma_v": self.gamma_v,
            "weights": self.weights.copy(),
            "last_probs": self._last_probs.copy(),
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        self.weights = state["weights"]
        self._last_probs = state.get("last_probs", {})
