"""
Cluster Selection Strategies

Public API
----------
- ``SelectionResult`` — dataclass carrying the output of ``select()``.
- ``ClusterSelector``  — abstract base class.
- ``UniformRandomSelector``, ``GreedyTopKSelector``,
  ``SoftmaxProportionalSelector``, ``ThompsonSamplingSelector``,
  ``EXP3Selector`` — concrete implementations.
- ``STRATEGY_REGISTRY`` — name → class mapping for CLI dispatch.
"""

from .base import ClusterSelector, SelectionResult
from .implementations import (
    UniformRandomSelector,
    GreedyTopKSelector,
    SoftmaxProportionalSelector,
    ThompsonSamplingSelector,
    EXP3Selector,
)

STRATEGY_REGISTRY = {
    "uniform": UniformRandomSelector,
    "greedy": GreedyTopKSelector,
    "softmax": SoftmaxProportionalSelector,
    "thompson": ThompsonSamplingSelector,
    "exp3": EXP3Selector,
}

__all__ = [
    "ClusterSelector",
    "SelectionResult",
    "UniformRandomSelector",
    "GreedyTopKSelector",
    "SoftmaxProportionalSelector",
    "ThompsonSamplingSelector",
    "EXP3Selector",
    "STRATEGY_REGISTRY",
]
