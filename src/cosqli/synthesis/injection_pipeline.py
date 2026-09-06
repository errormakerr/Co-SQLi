"""
SQL injection sample generation pipeline.

This module provides:
- ``pipeline``                      — end-to-end function that converts a raw SQL example +
                                       payload template into a labelled injection SQL sample

Extracted components (imported from sub-modules):
- ``SymbolChecker``                 — see ``Attacker.symbol_checker``
- ``GetRandomAttribute``            — see ``Attacker.random_attributes``
- ``SpecificDatabaseTemplateFiller``— see ``Attacker.template_fillers.specific_db_filler``
- ``SystemInformationTemplateFiller``— see ``Attacker.template_fillers.system_info_filler``
"""

from __future__ import annotations

import os
import re
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from cosqli.paths import PROJECT_ROOT, get_config_path, require_secret
from cosqli.utils.yaml_operation import load_yaml_to_dict
from cosqli.utils.llm import LLM
from cosqli.utils.j2_operation import load_prompt_template

# Re-export synthesis helpers from the refactored package boundary.
from .symbol_checker import SymbolChecker
from .random_attributes import GetRandomAttribute
from .template_fillers.specific_db_filler import SpecificDatabaseTemplateFiller
from .template_fillers.system_info_filler import SystemInformationTemplateFiller


# ---------------------------------------------------------------------------
# Config loading helpers (module-level cache)
# ---------------------------------------------------------------------------

_MYSQL_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def get_mysql_config(
    config_path=None, *, force_reload: bool = False
) -> Dict[str, Any]:
    """
    Load (and cache) the MySQL connection configuration from YAML.

    Args:
        config_path:  Path to ``database_connection.yaml``.  Defaults to
                      ``<project_root>/config/database_connection.yaml``.
        force_reload: Bypass the in-memory cache and reload from disk.

    Returns:
        MySQL configuration dict.
    """
    global _MYSQL_CONFIG_CACHE
    if _MYSQL_CONFIG_CACHE is not None and not force_reload:
        return _MYSQL_CONFIG_CACHE

    if config_path is None:
        config_path = get_config_path("database_connection.yaml")
    else:
        config_path = Path(config_path)

    _MYSQL_CONFIG_CACHE = load_yaml_to_dict(str(config_path))
    _MYSQL_CONFIG_CACHE["password"] = require_secret(_MYSQL_CONFIG_CACHE, "password")
    port_override = os.environ.get("COSQLI_MYSQL_PORT")
    if port_override:
        try:
            port = int(port_override)
        except ValueError as error:
            raise ValueError("COSQLI_MYSQL_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ValueError("COSQLI_MYSQL_PORT must be in [1, 65535]")
        _MYSQL_CONFIG_CACHE["port"] = port
    return _MYSQL_CONFIG_CACHE


def get_gpt_config(config_path=None) -> Dict[str, Any]:
    """
    Load the GPT/LLM configuration from YAML.

    Args:
        config_path: Path to ``gpt_config.yaml``.  Defaults to
                     ``<project_root>/config/gpt_config.yaml``.

    Returns:
        LLM configuration dict.
    """
    if config_path is None:
        config_path = get_config_path("gpt_config.yaml")
    else:
        config_path = Path(config_path)
    config = load_yaml_to_dict(str(config_path))
    config["api_key"] = require_secret(config, "api_key")
    return config


# ---------------------------------------------------------------------------
# Lazy-initialised singletons (no import-time side effects)
# ---------------------------------------------------------------------------

_gpt_config: Optional[Dict[str, Any]] = None
_gpt: Optional[LLM] = None
_checker: Optional[SymbolChecker] = None


def _get_gpt_config() -> Dict[str, Any]:
    """Return the cached GPT config, loading it on first access."""
    global _gpt_config
    if _gpt_config is None:
        _gpt_config = get_gpt_config()
    return _gpt_config


def _get_gpt() -> LLM:
    """Return the cached LLM instance, creating it on first access."""
    global _gpt
    if _gpt is None:
        cfg = _get_gpt_config()
        _gpt = LLM(
            api_key=cfg["api_key"],
            base_url=cfg.get("base_url"),
            request_extra_body=cfg.get("extra_body"),
        )
    return _gpt


def _get_checker() -> SymbolChecker:
    """Return the cached SymbolChecker instance, creating it on first access."""
    global _checker
    if _checker is None:
        _checker = SymbolChecker()
    return _checker


# ---------------------------------------------------------------------------
# Pipeline helper functions (extracted from nested definitions)
# ---------------------------------------------------------------------------

SQL_COMMENT_PREFIXES = ("-- ", "# ")
CEPP_RATIONAL_EXPLANATION_PROBABILITY = 0.20
"""Compatibility default; configured experiment runs use ``synthesis.cepp``."""

CEPP_LLM_MAX_TOKENS = 96
"""Compatibility default; configured experiment runs use ``synthesis.cepp``."""

CEPP_LLM_MAX_RETRIES = 0
"""Compatibility default; configured experiment runs use ``synthesis.cepp``."""

LOCAL_CEPP_COMMENT_TYPES = (
    "Irrelevant text dilution",
    "Authoritative statement",
)
"""The two repository-backed CEPP strategies, sampled by entry count."""

_RATIONAL_CONTEXT_STOPWORDS = {
    "ALL", "AND", "AS", "BETWEEN", "BY", "CASE", "CAST", "CREATE", "DELETE",
    "DROP", "EXISTS", "FROM", "IF", "IN", "INSERT", "INTO", "IS", "LIKE", "NOT",
    "NULL", "OR", "ORDER", "SELECT", "SET", "TABLE", "THEN", "UNION", "UPDATE",
    "VALUES", "WHEN", "WHERE",
}


def choose_comment_prefix() -> str:
    """Return one of the supported MySQL line-comment prefixes at random."""
    return random.choice(SQL_COMMENT_PREFIXES)


def _is_safe_cepp_text(value: object) -> bool:
    """Return whether a local or LLM CEPP string obeys the CEPP contract."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "\n" not in value
        and "\r" not in value
        and "--" not in value
        and "#" not in value
    )


def _local_cepp_candidates(
    comment_list: List[Dict], comment_type: Optional[str] = None
) -> List[str]:
    """Return only local CEPP entries that satisfy the canonical contract."""
    allowed_types = (
        {comment_type}
        if comment_type is not None
        else set(LOCAL_CEPP_COMMENT_TYPES)
    )
    return [
        entry["comment"].strip()
        for entry in comment_list
        if entry.get("type") in allowed_types
        and _is_safe_cepp_text(entry.get("comment"))
    ]


def _contextual_rational_explanation(technique: str, payload: str) -> str:
    """Create a safe, payload-specific CEPP explanation without an LLM call."""
    identifiers = [
        token.replace("_", " ")
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", payload)
        if token.upper() not in _RATIONAL_CONTEXT_STOPWORDS
    ]
    if identifiers:
        return f"Validate the requested {identifiers[-1]} operation for the current query."

    technique_subjects = {
        "tautology": "condition",
        "union_query": "report field",
        "piggy_backed": "maintenance action",
        "error_based": "database diagnostic",
        "boolean_blind": "validation result",
        "time_blind": "response timing check",
    }
    subject = technique_subjects.get(technique, "database operation")
    return f"Validate the requested {subject} for the current query."


def identify_difficulty(reference_scope: str, comment_state: str) -> str:
    """Assign a display-only difficulty label from canonical taxonomy fields."""
    if reference_scope == "lor":
        return "simple"
    if reference_scope == "scr":
        return "medium"
    return "hard" if comment_state == "cepp" else "medium"


def generate_comment(
    technique: str,
    payload_template_str: str,
    payload: str,
    comment_list: List[Dict],
    allow_llm: bool = True,
    llm_timeout_seconds: Optional[float] = None,
    rational_explanation_probability: float = CEPP_RATIONAL_EXPLANATION_PROBABILITY,
    llm_max_tokens: int = CEPP_LLM_MAX_TOKENS,
    llm_max_retries: int = CEPP_LLM_MAX_RETRIES,
    use_rational: Optional[bool] = None,
) -> str:
    """Generate CEPP text while preserving the historical string-only API."""
    comment, _ = _generate_comment_with_strategy(
        technique,
        payload_template_str,
        payload,
        comment_list,
        allow_llm=allow_llm,
        llm_timeout_seconds=llm_timeout_seconds,
        rational_explanation_probability=rational_explanation_probability,
        llm_max_tokens=llm_max_tokens,
        llm_max_retries=llm_max_retries,
        use_rational=use_rational,
    )
    return comment


def _generate_comment_with_strategy(
    technique: str,
    payload_template_str: str,
    payload: str,
    comment_list: List[Dict],
    allow_llm: bool = True,
    llm_timeout_seconds: Optional[float] = None,
    rational_explanation_probability: float = CEPP_RATIONAL_EXPLANATION_PROBABILITY,
    llm_max_tokens: int = CEPP_LLM_MAX_TOKENS,
    llm_max_retries: int = CEPP_LLM_MAX_RETRIES,
    use_rational: Optional[bool] = None,
) -> tuple[str, str]:
    """
    Generate a deceptive natural-language comment to append to the payload.

    When LLM generation is enabled, query-specific rational explanations are
    selected with the configured probability. The remaining samples are drawn
    uniformly from the combined local candidate pool, preserving the
    repository's relative proportions of irrelevant-text and authoritative
    entries.

    With LLM generation disabled, only the local pool is available; its two
    strategies remain sampled in their repository proportions.
    """
    local_candidates_by_type = {
        comment_type: _local_cepp_candidates(comment_list, comment_type)
        for comment_type in LOCAL_CEPP_COMMENT_TYPES
    }
    fallback_candidates = [
        candidate
        for comment_type in LOCAL_CEPP_COMMENT_TYPES
        for candidate in local_candidates_by_type[comment_type]
    ]
    if not fallback_candidates:
        raise ValueError("CEPP generation requires a safe local comment candidate")
    if not 0.0 <= rational_explanation_probability <= 1.0:
        raise ValueError("rational_explanation_probability must be in [0, 1]")

    def choose_local_comment() -> tuple[str, str]:
        comment = random.choice(fallback_candidates)
        for comment_type, candidates in local_candidates_by_type.items():
            if comment in candidates:
                return comment, "local_" + comment_type.lower().replace(" ", "_")
        raise AssertionError("Chosen CEPP comment was not in the local candidate pool")

    if use_rational is None:
        use_rational = random.random() < rational_explanation_probability
    if not use_rational:
        return choose_local_comment()

    if not allow_llm:
        return (
            _contextual_rational_explanation(technique, payload),
            "rational_template_explanation",
        )

    # An unavailable or invalid LLM response must retain the rational CEPP class.
    fallback_reason = "invalid_response"
    try:
        templates_dir = PROJECT_ROOT / "prompts"
        gpt_config = _get_gpt_config()
        response = _get_gpt().generate(
            prompt=load_prompt_template(str(templates_dir), "comment_generation.j2").render(
                technique=technique,
                payload_template=payload_template_str,
                payload=payload,
            ),
            model=gpt_config.get("model", "gpt-3.5-turbo"),
            temperature=gpt_config.get("temperature", 0.5),
            max_tokens=min(int(gpt_config.get("max_tokens", 1024)), llm_max_tokens),
            timeout_seconds=llm_timeout_seconds,
            max_retries=llm_max_retries,
        )
        if _is_safe_cepp_text(response):
            return response.strip(), "rational_explanation"
    except Exception as error:
        fallback_reason = "exception_" + type(error).__name__
    return (
        _contextual_rational_explanation(technique, payload),
        "rational_fallback_" + fallback_reason,
    )


def insert_payload(sql: str, payload: str) -> Optional[str]:
    """
    Insert *payload* into *sql* at the ``$$`` injection point.

    Handles two contexts:
    - **String context** (``$$`` is followed by ``'``): keep the leading
      quote of the payload.
    - **Non-string context**: strip the leading quote from the payload.

    The payload is inserted verbatim apart from the established non-string
    context quote handling.  In particular, comment delimiters are never
    removed or rewritten: they encode the canonical ``comment_state``.
    """

    def remove_first_char(text: str) -> str:
        return text[1:] if text else text

    if not isinstance(sql, str) or not isinstance(payload, str):
        return None

    try:
        matches = list(re.finditer(r"\$\$", sql))
        if not matches:
            return None
        positions = [m.start() for m in matches]

        try:
            is_string_context = sql[positions[0] + 2] == "'"
        except IndexError:
            is_string_context = False

        if is_string_context:
            injection_sql = sql.replace("$$", payload)
        else:
            injection_sql = sql.replace("$$", remove_first_char(payload))

        return injection_sql

    except Exception as e:
        print(f"Error inserting payload: {e}")
        return None


# ---------------------------------------------------------------------------
# Injection-SQL generation pipeline
# ---------------------------------------------------------------------------

def _has_line_comment_marker(value: str) -> bool:
    """Return whether *value* contains a SQL line-comment delimiter."""
    return "--" in value or "#" in value


def _validate_comment_state(
    sql_example: Dict[str, Any],
    payload_core: str,
    payload: str,
    comment_state: str,
    cepp_text: str = "",
    comment_prefix: str = "",
) -> None:
    """Enforce the three-state comment taxonomy before SQL insertion."""
    requires_delimiter = sql_example.get("requires_comment_delimiter")
    if not isinstance(requires_delimiter, bool):
        raise ValueError("sql_example requires boolean requires_comment_delimiter")
    if _has_line_comment_marker(payload_core):
        raise ValueError("payload_core must not contain SQL line-comment delimiters")

    if comment_state == "no_comment":
        if requires_delimiter:
            raise ValueError("no_comment requires requires_comment_delimiter=False")
        if _has_line_comment_marker(payload) or cepp_text.strip():
            raise ValueError("no_comment must contain neither delimiter nor CEPP")
        return

    if comment_state == "clean_comment":
        if not requires_delimiter:
            raise ValueError("clean_comment requires requires_comment_delimiter=True")
        if comment_prefix not in SQL_COMMENT_PREFIXES:
            raise ValueError("clean_comment requires a supported comment delimiter")
        if payload != payload_core + comment_prefix or cepp_text.strip():
            raise ValueError("clean_comment requires exactly one trailing comment delimiter")
        return

    if comment_state == "cepp":
        if not requires_delimiter:
            raise ValueError("cepp requires requires_comment_delimiter=True")
        if not cepp_text.strip():
            raise ValueError("cepp requires non-empty text after the delimiter")
        if not _is_safe_cepp_text(cepp_text):
            raise ValueError("CEPP must be a single plain-text line")
        if comment_prefix not in SQL_COMMENT_PREFIXES:
            raise ValueError("cepp requires a supported comment delimiter")
        if payload != payload_core + comment_prefix + cepp_text:
            raise ValueError("CEPP must occur directly after the comment delimiter")
        return

    raise ValueError(f"Unsupported comment_state: {comment_state!r}")


def _fill_payload_core(
    sql_example: Dict[str, Any],
    payload_template: Dict[str, Any],
    db_schemas: List[Dict],
    sys_schemas: List[Dict],
    system_vars: List[Dict],
) -> tuple[str, List[Dict[str, Any]]]:
    """Fill a comment-free canonical payload template with live values."""
    if payload_template["expected_types"] is None:
        return str(payload_template["payload"]), []

    reference_scope = payload_template["reference_scope"]
    mysql_config = get_mysql_config().copy()
    mysql_config["database"] = sql_example["db"]
    if reference_scope == "scr":
        if "table" in payload_template["expected_types"]:
            filler = SpecificDatabaseTemplateFiller(random.choice(sys_schemas), mysql_config)
        else:
            filler = SystemInformationTemplateFiller(system_vars, mysql_config)
        return str(filler.fill_template(payload_template)), filler.synthesis_warnings
    if reference_scope == "tsr":
        schema = next(
            (schema for schema in db_schemas if schema["database_name"] == sql_example["db"]),
            {},
        )
        filler = SpecificDatabaseTemplateFiller(schema, mysql_config)
        return str(filler.fill_template(payload_template)), filler.synthesis_warnings
    return str(payload_template["payload"]), []

def pipeline(
    sql_example: Dict[str, Any],
    payload_template: Dict[str, Any],
    db_schemas: List[Dict],
    sys_schemas: List[Dict],
    system_vars: List[Dict],
    comment_list: List[Dict],
    comment_state: str,
    allow_llm_comment: bool = True,
    cepp_llm_timeout_seconds: Optional[float] = None,
    cepp_rational_explanation_probability: float = CEPP_RATIONAL_EXPLANATION_PROBABILITY,
    cepp_llm_max_tokens: int = CEPP_LLM_MAX_TOKENS,
    cepp_llm_max_retries: int = CEPP_LLM_MAX_RETRIES,
    cepp_use_rational: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convert a raw SQL example + payload template into a labelled injection sample.

    ``payload_template`` always supplies only a comment-free ``payload_core``.
    The requested ``comment_state`` is assembled here, where the carrier SQL
    context is known and can be checked.

    Args:
        sql_example:      A raw SQL query dict from ``sql_data_with_injection_point.json``.
        payload_template: A payload template dict from ``payload_template.json`` (possibly mutated).
        db_schemas:       List of all database schemas.
        sys_schemas:      List of MySQL system-table schemas.
        system_vars:      List of MySQL system variable definitions.
        comment_list:     Repository of pre-written deceptive comments.
        comment_state:    ``no_comment``, ``clean_comment``, or ``cepp``.

    Returns:
        An injection sample dict, or ``None`` if generation failed.
    """

    if sql_example.get("sql") is None:
        return None

    payload_core, synthesis_warnings = _fill_payload_core(
        sql_example, payload_template, db_schemas, sys_schemas, system_vars
    )
    cepp_text = ""
    cepp_comment_strategy = ""
    comment_prefix = ""
    if comment_state == "no_comment":
        payload = payload_core
    elif comment_state == "clean_comment":
        comment_prefix = choose_comment_prefix()
        payload = payload_core + comment_prefix
    elif comment_state == "cepp":
        comment_prefix = choose_comment_prefix()
        cepp_text, cepp_comment_strategy = _generate_comment_with_strategy(
            payload_template["technique"],
            payload_template["payload"],
            payload_core,
            comment_list,
            allow_llm=allow_llm_comment,
            llm_timeout_seconds=cepp_llm_timeout_seconds,
            rational_explanation_probability=cepp_rational_explanation_probability,
            llm_max_tokens=cepp_llm_max_tokens,
            llm_max_retries=cepp_llm_max_retries,
            use_rational=cepp_use_rational,
        )
        cepp_text = str(cepp_text).strip()
        payload = payload_core + comment_prefix + cepp_text
    else:
        raise ValueError(f"Unsupported comment_state: {comment_state!r}")

    _validate_comment_state(
        sql_example, payload_core, payload, comment_state, cepp_text, comment_prefix
    )
    injection_sql = insert_payload(sql_example["sql"], payload)
    if injection_sql is None:
        return None
    effective_sql = (
        injection_sql.split(comment_prefix, 1)[0]
        if comment_prefix
        else injection_sql
    )
    balanced, _ = _get_checker().check_balanced(effective_sql)
    if not balanced:
        return None

    return {
        "sql": injection_sql,
        "original_sql": sql_example,
        "payload_template": payload_template,
        "payload_core": payload_core,
        "payload": payload,
        "label": False,
        "technique": payload_template["technique"],
        "reference_scope": payload_template["reference_scope"],
        "comment_state": comment_state,
        "cepp_comment_strategy": cepp_comment_strategy or None,
        "synthesis_warnings": synthesis_warnings,
        "difficulty": identify_difficulty(
            payload_template["reference_scope"], comment_state
        ),
    }
