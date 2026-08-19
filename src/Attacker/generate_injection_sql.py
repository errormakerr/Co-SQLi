"""
SQL injection sample generation pipeline.

This module provides:
- ``pipeline``                      — end-to-end function that converts a raw SQL example +
                                       payload template into a labelled injection SQL sample
- ``batch_generate_injection_sqls`` — convenience wrapper around ``pipeline``

Extracted components (imported from sub-modules):
- ``SymbolChecker``                 — see ``Attacker.symbol_checker``
- ``GetRandomAttribute``            — see ``Attacker.random_attributes``
- ``SpecificDatabaseTemplateFiller``— see ``Attacker.template_fillers.specific_db_filler``
- ``SystemInformationTemplateFiller``— see ``Attacker.template_fillers.system_info_filler``
"""

from __future__ import annotations

import re
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.yaml_operation import load_yaml_to_dict
from utils.LLM import LLM
from utils.j2_operation import load_prompt_template

# Re-export extracted classes so existing ``from generate_injection_sql import X``
# statements continue to work without modification.
from Attacker.symbol_checker import SymbolChecker
from Attacker.random_attributes import GetRandomAttribute
from Attacker.template_fillers.specific_db_filler import SpecificDatabaseTemplateFiller
from Attacker.template_fillers.system_info_filler import SystemInformationTemplateFiller


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
        project_root = Path(__file__).resolve().parents[2]
        config_path = project_root / "config" / "database_connection.yaml"
    else:
        config_path = Path(config_path)

    _MYSQL_CONFIG_CACHE = load_yaml_to_dict(str(config_path))
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
        project_root = Path(__file__).resolve().parents[2]
        config_path = project_root / "config" / "gpt_config.yaml"
    else:
        config_path = Path(config_path)
    return load_yaml_to_dict(str(config_path))


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

def identify_difficulty(annotator: bool, comment: bool, information_features: str) -> str:
    """Assign a difficulty label based on query and payload metadata."""
    if information_features == "constant":
        return "simple"
    if information_features == "system information":
        return "medium"
    if information_features == "specific database":
        if annotator and comment:
            return "hard"
        if annotator and not comment:
            return "medium"
        return "hard"
    return "medium"


def generate_comment(
    payload_type: str,
    payload_template_str: str,
    payload: str,
    comment_list: List[Dict],
) -> str:
    """
    Generate a deceptive natural-language comment to append to the payload.

    Randomly selects one of three strategies:
    - **Irrelevant text dilution**: random benign-looking text
    - **Authoritative statement**: authority-sounding assertion
    - **Rational explanation**: LLM-generated contextual explanation
    """
    comment_type = random.choice(
        ["Rational explanation", "Irrelevant text dilution", "Authoritative statement"]
    )
    if comment_type == "Irrelevant text dilution":
        candidates = [c for c in comment_list if c["type"] == "Irrelevant text dilution"]
        return random.choice(candidates)["comment"]
    if comment_type == "Authoritative statement":
        candidates = [c for c in comment_list if c["type"] == "Authoritative statement"]
        return random.choice(candidates)["comment"]
    # Rational explanation — use LLM
    project_root = Path(__file__).resolve().parents[2]
    templates_dir = project_root / "prompt_templates"
    gpt_config = _get_gpt_config()
    prompt = load_prompt_template(templates_dir, "generate_comment.j2").render(
        payload_type=payload_type,
        payload_template=payload_template_str,
        payload=payload,
    )
    return _get_gpt().generate(
        prompt=prompt,
        model=gpt_config.get("model", "gpt-3.5-turbo"),
        temperature=gpt_config.get("temperature", 0.5),
        max_tokens=gpt_config.get("max_tokens", 1024),
    )


def insert_payload(sql: str, payload: str) -> Optional[str]:
    """
    Insert *payload* into *sql* at the ``$$`` injection point.

    Handles two contexts:
    - **String context** (``$$`` is followed by ``'``): keep the leading
      quote of the payload.
    - **Non-string context**: strip the leading quote from the payload.

    Also removes trailing ``--`` comment terminators that would be
    redundant (i.e., followed only by whitespace or nothing), and attempts
    to fix bracket imbalances by inserting a closing ``)`` before ``--``.
    """

    def remove_first_char(text: str) -> str:
        return text[1:] if text else text

    def insert_char_at_position(text: str, position: int, char: str) -> str:
        return text[:position] + char + text[position:]

    def remove_unnecessary_comments(sql_text: str) -> str:
        """
        Remove ``--`` terminators that appear at the very end of the string
        or are followed only by whitespace — they are structurally redundant.
        """
        for match in reversed(list(re.finditer(r"--", sql_text))):
            comment_pos = match.start()
            comment_end = match.end()
            if comment_end >= len(sql_text):
                sql_text = sql_text[:comment_pos]
            elif sql_text[comment_end:].strip() == "":
                sql_text = sql_text[:comment_pos]
        return sql_text

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

        injection_sql = remove_unnecessary_comments(injection_sql)

        # Check bracket balance in the fragment before any comment terminator
        checker = SymbolChecker()
        effective_sql = injection_sql.split("--")[0] if "--" in injection_sql else injection_sql
        balanced, _ = checker.check_balanced(effective_sql)

        if not balanced:
            comment_matches = list(re.finditer(r"--", injection_sql))
            bracket_pos = comment_matches[0].start() if comment_matches else len(injection_sql)
            injection_sql = insert_char_at_position(injection_sql, bracket_pos, ")")
            injection_sql = remove_unnecessary_comments(injection_sql)

        return injection_sql

    except Exception as e:
        print(f"Error inserting payload: {e}")
        return None


# ---------------------------------------------------------------------------
# Injection-SQL generation pipeline
# ---------------------------------------------------------------------------

def pipeline(
    sql_example: Dict[str, Any],
    payload_template: Dict[str, Any],
    db_schemas: List[Dict],
    sys_schemas: List[Dict],
    system_vars: List[Dict],
    comment_list: List[Dict],
    comment_flag: bool,
) -> Optional[Dict[str, Any]]:
    """
    Convert a raw SQL example + payload template into a labelled injection sample.

    Steps:
    1. Fill the payload template's placeholders (system info or DB-specific).
    2. Optionally append a deceptive natural-language comment.
    3. Insert the filled payload at the ``$$`` injection point in the SQL query.
    4. Validate bracket balance; fix with a closing ``)`` if needed.
    5. Return a structured dict with the injection SQL, metadata, and label.

    Args:
        sql_example:      A raw SQL query dict from ``sql_data_with_injection_point.json``.
        payload_template: A payload template dict from ``payloads.json`` (possibly mutated).
        db_schemas:       List of all database schemas.
        sys_schemas:      List of MySQL system-table schemas.
        system_vars:      List of MySQL system variable definitions.
        comment_list:     Repository of pre-written deceptive comments.
        comment_flag:     Whether to append a deceptive comment to the payload.

    Returns:
        An injection sample dict, or ``None`` if generation failed.
    """

    mysql_config = get_mysql_config().copy()
    mysql_config["database"] = sql_example["db"]

    injection_sql_example = None

    # Fill payload placeholders
    if payload_template["expected_types"] is None:
        raw_payload = payload_template["payload"]
    else:
        info_features = payload_template["information_features"]
        if info_features == "system information":
            if "table" in payload_template["expected_types"]:
                sys_schema = random.choice(sys_schemas)
                filler = SpecificDatabaseTemplateFiller(sys_schema, mysql_config)
                raw_payload = filler.fill_template(payload_template)
            else:
                filler = SystemInformationTemplateFiller(system_vars, mysql_config)
                raw_payload = filler.fill_template(payload_template)
        elif info_features == "specific database":
            schema = next(
                (s for s in db_schemas if s["database_name"] == sql_example["db"]), {}
            )
            filler = SpecificDatabaseTemplateFiller(schema, mysql_config)
            raw_payload = filler.fill_template(payload_template)
        else:
            # constant — expected_types is non-None but there are no placeholders
            raw_payload = payload_template["payload"]

    # Non-annotator queries never have deceptive comments
    if not sql_example["annotator"]:
        comment_flag = False

    # Optionally append a deceptive comment
    if comment_flag:
        payload = str(raw_payload) + str(
            generate_comment(
                payload_template["type"],
                payload_template["payload"],
                raw_payload,
                comment_list,
            )
        )
    else:
        payload = str(raw_payload)

    if sql_example["sql"] is None or payload is None:
        return injection_sql_example

    injection_sql = insert_payload(sql_example["sql"], payload)
    effective_sql = injection_sql.split("--")[0]
    balanced, message = _get_checker().check_balanced(effective_sql)

    if not balanced:
        print(f"'{effective_sql}'\n  -> {balanced}: {message}\n")
    else:
        injection_sql_example = {
            "sql": injection_sql,
            "original_sql": sql_example,
            "payload_template": payload_template,
            "payload": payload,
            "label": False,
            "comment": comment_flag,
            "difficulty": identify_difficulty(
                sql_example["annotator"],
                comment_flag,
                payload_template["information_features"],
            ),
        }

    return injection_sql_example


def batch_generate_injection_sqls(
    expected_example_num: int,
    raw_sqls: List[Dict],
    payloads: List[Dict],
    db_schemas: List[Dict],
    sys_schemas: List[Dict],
    system_vars: List[Dict],
    comment_list: List[Dict],
    comment_rate: float,
) -> List[Dict]:
    """
    Generate *expected_example_num* injection SQL samples by randomly sampling
    from *raw_sqls* and *payloads*.

    Args:
        expected_example_num: Target number of generated samples.
        raw_sqls:             List of raw SQL example dicts.
        payloads:             List of payload template dicts.
        db_schemas:           Database schemas list.
        sys_schemas:          System-table schemas list.
        system_vars:          System variable definitions.
        comment_list:         Deceptive comment repository.
        comment_rate:         Probability (0-1) of appending a comment per sample.

    Returns:
        List of successfully generated injection SQL sample dicts.
    """
    count = 0
    injection_sql_examples = []
    while count < expected_example_num:
        comment_flag = random.random() < comment_rate
        sample = pipeline(
            random.choice(raw_sqls),
            random.choice(payloads),
            db_schemas,
            sys_schemas,
            system_vars,
            comment_list,
            comment_flag,
        )
        if sample is not None:
            injection_sql_examples.append(sample)
        count += 1
    return injection_sql_examples
