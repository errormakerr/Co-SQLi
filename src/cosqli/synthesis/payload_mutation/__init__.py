"""
SQL Injection Payload Mutation Module

A system for generating diverse SQL injection payloads through LLM-based mutation.

Key Features:
- Technique-focused and structure-focused mutation strategies
- 16-category memory system (valid technique × reference-scope pairs)
- Anti-imitation few-shot learning
- Separate expected_types inference for semantic understanding
"""

from .type_identifier import ReferenceScope, Technique, identify
from .memory import MutationMemory, CategoryMemory
from .validator import validate_mutation, PayloadValidator
from .payload_mutator import PayloadMutator
from .expected_types_inferrer import ExpectedTypesInferrer, infer_expected_types

__all__ = [
    # Type identification
    "identify", "Technique", "ReferenceScope",
    # Memory system
    "MutationMemory", "CategoryMemory",
    # Validation
    "validate_mutation", "PayloadValidator",
    # Core mutator
    "PayloadMutator",
    # Expected types inference
    "ExpectedTypesInferrer", "infer_expected_types"
]
