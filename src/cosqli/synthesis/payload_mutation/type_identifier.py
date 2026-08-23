"""Canonical taxonomy identification for comment-free payload cores."""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, Tuple


class Technique(Enum):
    """The six attack techniques in the canonical taxonomy."""

    ERROR_BASED = "error_based"
    UNION_QUERY = "union_query"
    TAUTOLOGY = "tautology"
    PIGGY_BACKED = "piggy_backed"
    BOOLEAN_BLIND = "boolean_blind"
    TIME_BLIND = "time_blind"
    UNKNOWN = "unknown"


class ReferenceScope(Enum):
    """The payload reference-scope taxonomy."""

    LOR = "lor"
    TSR = "tsr"
    SCR = "scr"
    UNKNOWN = "unknown"


def identify_technique(payload: str) -> Technique:
    """Infer a technique from a payload core when metadata is unavailable."""
    payload_upper = payload.upper()
    if re.search(r";\s*(SELECT|DELETE|INSERT|UPDATE|DROP|TRUNCATE|CREATE)\b", payload_upper):
        return Technique.PIGGY_BACKED
    if re.search(r"(SLEEP|BENCHMARK)\s*\(", payload_upper):
        return Technique.TIME_BLIND
    if re.search(r"\b(UNION|ORDER\s+BY\s+\d|GROUP\s+BY\s+\d)", payload_upper):
        return Technique.UNION_QUERY
    if any(
        re.search(pattern, payload, re.IGNORECASE)
        for pattern in (
            r"CAST\s*\(", r"CONVERT\s*\(", r"SQRT\s*\(", r"LOG\d*\s*\(",
            r"MOD\s*\(", r"EXTRACTVALUE\s*\(", r"UPDATEXML\s*\(",
            r"GTID_SUBSET\s*\(", r"GTID_SUBTRACT\s*\(",
        )
    ):
        return Technique.ERROR_BASED
    if "AND" in payload_upper and any(
        token in payload_upper for token in ("SUBSTR", "SUBSTRING", "ASCII", "ORD", "LENGTH")
    ):
        return Technique.BOOLEAN_BLIND
    if re.search(r"'\s+(OR|AND)\s+", payload, re.IGNORECASE):
        return Technique.TAUTOLOGY
    return Technique.UNKNOWN


def identify_reference_scope(payload: str) -> ReferenceScope:
    """Infer LOR/TSR/SCR from placeholder forms."""
    if re.search(r"\$(?:table_\d+|column_t\d+_\d+|sample_t\d+_\d+)\$", payload):
        return ReferenceScope.TSR
    if "$sysInfo$" in payload:
        return ReferenceScope.SCR
    return ReferenceScope.LOR


def identify(payload_template: Dict) -> Tuple[Technique, ReferenceScope]:
    """Read canonical metadata first, falling back to payload heuristics."""
    technique_value = payload_template.get("technique")
    scope_value = payload_template.get("reference_scope")
    technique = (
        Technique(technique_value)
        if technique_value in {item.value for item in Technique}
        else identify_technique(payload_template.get("payload", ""))
    )
    reference_scope = (
        ReferenceScope(scope_value)
        if scope_value in {item.value for item in ReferenceScope}
        else identify_reference_scope(payload_template.get("payload", ""))
    )
    return technique, reference_scope
