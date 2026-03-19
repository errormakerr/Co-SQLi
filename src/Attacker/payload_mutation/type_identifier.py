"""
SQL injection payload type identifier.

Identifies the attack type (``AttackType``) and information feature category
(``InfoFeature``) of a payload template using a combination of explicit
metadata fields and regex-based heuristics.
"""

import re
from enum import Enum
from typing import Dict, Tuple


class AttackType(Enum):
    """Enumeration of SQL injection attack categories."""
    ERROR_BASE = "Error base attack"
    UNION_QUERY = "Union-query attack"
    TAUTOLOGIES = "Tautologies attack"
    PIGGY_BACKED = "Piggy-backed queries attacks"
    BOOLEAN_INFERENCE = "Boolean base inference attack"
    TIME_INFERENCE = "Time base inference attack"
    UNKNOWN = "Unknown"


class InfoFeature(Enum):
    """Enumeration of information-feature categories."""
    CONSTANT = "constant"
    SYSTEM_INFO = "system information"
    SPECIFIC_DB = "specific database"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Regex patterns for attack-type detection
# ---------------------------------------------------------------------------

TYPE_PATTERNS: Dict[AttackType, list] = {
    AttackType.ERROR_BASE: [
        r"CAST\s*\(",
        r"CONVERT\s*\(",
        r"SQRT\s*\(",
        r"LOG\d*\s*\(",
        r"LN\s*\(",
        r"MOD\s*\(",
        r"extractvalue\s*\(",
        r"updatexml\s*\(",
        r"GTID_SUBSET\s*\(",
        r"GTID_SUBTRACT\s*\(",
        r"TIME\s*\(['\"]",
        r"DATE\s*\(['\"]",
        r"TO_DAYS\s*\(",
        r"SUBSTR\s*\([^,]+,\s*['\"]",  # SUBSTR with invalid (non-integer) params
        r"\/\s*\(SELECT\s+0\)",
        r"9223372036854775807",          # INT overflow value
        r"-9223372036854775808",
        r"1\.7976931348623157e\+308",
    ],
    AttackType.UNION_QUERY: [
        r"\bUNION\b",
        r"\bORDER\s+BY\s+\d",
        r"\bGROUP\s+BY\s+\d",
    ],
    AttackType.TAUTOLOGIES: [
        r"'\s+OR\s+",
        r"'\s+AND\s+\d\s*=\s*\d",
        r"'\s+AND\s+'[^']+'\s*=\s*'[^']+'",
    ],
    AttackType.PIGGY_BACKED: [
        r";\s*SELECT\b",
        r";\s*DELETE\b",
        r";\s*INSERT\b",
        r";\s*UPDATE\b",
        r";\s*DROP\b",
        r";\s*TRUNCATE\b",
        r";\s*CREATE\b",
    ],
    AttackType.TIME_INFERENCE: [
        r"SLEEP\s*\(",
        r"BENCHMARK\s*\(",
        r"SELECT\s+COUNT\s*\(\*\)\s+FROM\s+\w+\s*,\s*\w+",
    ],
    AttackType.BOOLEAN_INFERENCE: [
        r"'\s+AND\s+.*(?:SUBSTR|SUBSTRING|LEFT|RIGHT|ASCII|ORD)",
        r"'\s+AND\s+.*(?:LENGTH|COUNT)",
        r"'\s+AND\s+IF\s*\(",
        r"'\s+AND\s+CASE\s+WHEN",
    ],
}


def identify_attack_type(payload: str) -> AttackType:
    """
    Identify the attack type of *payload* using prioritised heuristic rules.

    Detection priority (highest first):
    1. Piggy-backed  (secondary statement after ``;``)
    2. Time-based    (``SLEEP`` / ``BENCHMARK``)
    3. Union-query   (``UNION``, ``ORDER BY N``, ``GROUP BY N``)
    4. Error-based   (error-triggering functions)
    5. Boolean-based (character-extraction functions with ``AND``)
    6. Tautologies   (``' OR …`` / ``' AND …``)

    Returns ``AttackType.UNKNOWN`` when no pattern matches.

    Args:
        payload: SQL injection payload string (may contain placeholders).

    Returns:
        Matching ``AttackType`` enum value.
    """
    payload_upper = payload.upper()

    # 1. Piggy-backed — secondary statement introduced by semicolon
    if re.search(r";\s*(SELECT|DELETE|INSERT|UPDATE|DROP|TRUNCATE|CREATE)\b", payload_upper):
        return AttackType.PIGGY_BACKED

    # 2. Time-based — delay functions
    if re.search(r"(SLEEP|BENCHMARK)\s*\(", payload_upper):
        return AttackType.TIME_INFERENCE

    # 3. Union-query — UNION keyword or positional ORDER/GROUP BY probes
    if re.search(r"\b(UNION|ORDER\s+BY\s+\d|GROUP\s+BY\s+\d)", payload_upper):
        return AttackType.UNION_QUERY

    # 4. Error-based — error-triggering numeric/XML/GTID functions
    error_funcs = [
        r"CAST\s*\(", r"CONVERT\s*\(", r"SQRT\s*\(", r"LOG\d*\s*\(",
        r"MOD\s*\(",  r"extractvalue\s*\(", r"updatexml\s*\(",
        r"GTID_SUBSET\s*\(", r"GTID_SUBTRACT\s*\(",
    ]
    for pattern in error_funcs:
        if re.search(pattern, payload, re.IGNORECASE):
            return AttackType.ERROR_BASE

    # 5. Boolean inference — character-extraction functions paired with AND
    bool_indicators = ["SUBSTR", "SUBSTRING", "ASCII", "ORD", "LENGTH"]
    if "AND" in payload_upper:
        if any(ind in payload_upper for ind in bool_indicators):
            return AttackType.BOOLEAN_INFERENCE

    # 6. Tautologies — OR / AND always-true conditions
    if re.search(r"'\s+OR\s+", payload, re.IGNORECASE):
        return AttackType.TAUTOLOGIES
    if re.search(r"'\s+AND\s+", payload, re.IGNORECASE):
        return AttackType.TAUTOLOGIES

    return AttackType.UNKNOWN


def identify_info_feature(payload: str) -> InfoFeature:
    """
    Identify the information feature of *payload* from its placeholder types.

    - ``$table_N$`` / ``$column_tN_M$``  → ``SPECIFIC_DB``
    - ``$sysInfo$``                        → ``SYSTEM_INFO``
    - (none)                               → ``CONSTANT``

    Args:
        payload: SQL injection payload string (may contain placeholders).

    Returns:
        Matching ``InfoFeature`` enum value.
    """
    has_table = bool(re.search(r"\$table_\d+\$", payload))
    has_column = bool(re.search(r"\$column_t\d+_\d+\$", payload))
    has_sysinfo = bool(re.search(r"\$sysInfo\$", payload))

    if has_table or has_column:
        return InfoFeature.SPECIFIC_DB
    if has_sysinfo:
        return InfoFeature.SYSTEM_INFO
    return InfoFeature.CONSTANT


def identify(payload_template: Dict) -> Tuple[AttackType, InfoFeature]:
    """
    Identify the attack type and information feature of a payload template.

    Explicit ``"type"`` and ``"information_features"`` fields in
    *payload_template* take precedence over heuristic detection.

    Args:
        payload_template: Dict with at least a ``"payload"`` key and
                          optionally ``"type"`` and ``"information_features"``.

    Returns:
        ``(AttackType, InfoFeature)`` tuple.
    """
    # Attack type — prefer explicit field
    if payload_template.get("type"):
        type_str = payload_template["type"]
        attack_type = (
            AttackType(type_str)
            if type_str in {e.value for e in AttackType}
            else AttackType.UNKNOWN
        )
    else:
        attack_type = identify_attack_type(payload_template.get("payload", ""))

    # Information feature — prefer explicit field
    if payload_template.get("information_features"):
        feature_str = payload_template["information_features"]
        info_feature = (
            InfoFeature(feature_str)
            if feature_str in {e.value for e in InfoFeature}
            else InfoFeature.UNKNOWN
        )
    else:
        info_feature = identify_info_feature(payload_template.get("payload", ""))

    return attack_type, info_feature


# ---------------------------------------------------------------------------
# Convenience display helpers
# ---------------------------------------------------------------------------

def get_attack_type_name(attack_type: AttackType) -> str:
    """Return the human-readable name of *attack_type*."""
    return attack_type.value


def get_info_feature_name(info_feature: InfoFeature) -> str:
    """Return the human-readable name of *info_feature*."""
    return info_feature.value
