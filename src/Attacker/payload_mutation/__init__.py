"""
SQL Injection Payload Mutation Module

A system for generating diverse SQL injection payloads through LLM-based mutation.

Key Features:
- Type-focused and Info-focused mutation strategies
- 18-category memory system (6 attack types × 3 info features)
- Anti-imitation few-shot learning
- Separate expected_types inference for semantic understanding
"""

from .type_identifier import identify, AttackType, InfoFeature
from .memory import MutationMemory, CategoryMemory
from .validator import validate_mutation, PayloadValidator
from .payload_mutator import PayloadMutator
from .expected_types_inferrer import ExpectedTypesInferrer, infer_expected_types

__version__ = "2.1.0"
__all__ = [
    # Type identification
    "identify", "AttackType", "InfoFeature",
    # Memory system
    "MutationMemory", "CategoryMemory",
    # Validation
    "validate_mutation", "PayloadValidator",
    # Core mutator
    "PayloadMutator",
    # Expected types inference
    "ExpectedTypesInferrer", "infer_expected_types"
]
