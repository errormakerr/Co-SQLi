#!/usr/bin/env python3
"""Validate the refactored module boundaries without calling an LLM or training.

The test verifies that the high-level Attacker, Defender, and Verifier layers
can import their lower-level dependencies, that Defender launches scripts from
``src/model_ops``, and that one database-specific template can be filled and
converted into an SFT record through ``src/synthesis``.
"""

from __future__ import annotations

import argparse
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from Attacker.attacker import Attacker
from Defender.defender import Defender, FINETUNE_PY, INFER_PY, MERGE_PY
from Verifier.verifier import Verifier
from synthesis.injection_pipeline import get_mysql_config, pipeline
from synthesis.sft_formatter import create_sft_format
from synthesis.template_fillers import SpecificDatabaseTemplateFiller
from utils.json_operation import read_json_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw_datas_for_generation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=32,
        help="Maximum compatible raw-SQL/payload pairs to try (default: 32).",
    )
    return parser.parse_args()


def load_generation_data() -> Tuple[List[Dict[str, Any]], ...]:
    """Load only the static inputs needed for one deterministic synthesis test."""
    return (
        read_json_file(str(RAW_DATA_DIR / "sql_data_with_injection_point.json")),
        read_json_file(str(RAW_DATA_DIR / "payloads.json")),
        read_json_file(str(RAW_DATA_DIR / "schema.json")),
        read_json_file(str(RAW_DATA_DIR / "system_table_schema.json")),
        read_json_file(str(RAW_DATA_DIR / "system_var.json")),
        read_json_file(str(RAW_DATA_DIR / "comment_repository.json")),
    )


def validate_layout() -> None:
    """Validate import boundaries and the Defender subprocess targets."""
    # Import references are intentionally kept local to prove the public
    # high-level layer entry points remain available after the refactor.
    assert Attacker is not None
    assert Defender is not None
    assert Verifier is not None

    expected_model_ops = {
        "finetune.py": FINETUNE_PY,
        "merge_lora.py": MERGE_PY,
        "inference.py": INFER_PY,
    }
    for filename, script_path in expected_model_ops.items():
        path = Path(script_path)
        if path.name != filename or path.parent.name != "model_ops" or not path.is_file():
            raise RuntimeError(f"Defender model operation path is invalid: {path}")

    retired_paths = (
        PROJECT_ROOT / "src" / "Attacker" / "generate_injection_sql.py",
        PROJECT_ROOT / "src" / "Attacker" / "random_attributes.py",
        PROJECT_ROOT / "src" / "Attacker" / "symbol_checker.py",
        PROJECT_ROOT / "src" / "utils" / "sft_formatter.py",
        PROJECT_ROOT / "src" / "Defender" / "finetune.py",
        PROJECT_ROOT / "src" / "Defender" / "merge_lora.py",
        PROJECT_ROOT / "src" / "Defender" / "inference.py",
    )
    stale_paths = [str(path.relative_to(PROJECT_ROOT)) for path in retired_paths if path.exists()]
    if stale_paths:
        raise RuntimeError(f"Retired implementation paths still exist: {', '.join(stale_paths)}")


def select_database_sample(
    raw_sqls: List[Dict[str, Any]], schemas: List[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a raw SQL record and its matching schema for a live DB check."""
    schemas_by_database = {
        schema["database_name"]: schema
        for schema in schemas
        if schema.get("database_name") and schema.get("tables")
    }
    for sql_example in raw_sqls:
        database = sql_example.get("db")
        if database in schemas_by_database and "$$" in str(sql_example.get("sql")):
            return sql_example, schemas_by_database[database]
    raise RuntimeError("No raw SQL sample with a matching database schema was found")


def synthesize_one_database_sample(
    raw_sqls: List[Dict[str, Any]],
    payloads: List[Dict[str, Any]],
    schemas: List[Dict[str, Any]],
    sys_schemas: List[Dict[str, Any]],
    system_vars: List[Dict[str, Any]],
    comment_list: List[Dict[str, Any]],
    max_attempts: int,
) -> Tuple[Dict[str, Any], int]:
    """Fill a database-specific payload and return a valid injection record."""
    raw_candidates = [
        sample
        for sample in raw_sqls
        if sample.get("db") and "$$" in str(sample.get("sql"))
    ]
    payload_candidates = [
        payload
        for payload in payloads
        if payload.get("information_features") == "specific database"
        and payload.get("expected_types")
    ]
    if not raw_candidates or not payload_candidates:
        raise RuntimeError("No database-specific raw SQL/payload candidates were found")

    previous_random_state = random.getstate()
    random.seed(20260820)
    chooser = random.Random(20260820)
    last_error: Exception | None = None
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                result = pipeline(
                    chooser.choice(raw_candidates),
                    chooser.choice(payload_candidates),
                    schemas,
                    sys_schemas,
                    system_vars,
                    comment_list,
                    comment_flag=False,
                )
                if result is not None:
                    return result, attempt
            except Exception as error:
                last_error = error
    finally:
        random.setstate(previous_random_state)

    detail = f" Last error: {last_error}" if last_error is not None else ""
    raise RuntimeError(
        f"Could not synthesize a valid database-specific sample in {max_attempts} attempts.{detail}"
    )


def main() -> None:
    args = parse_args()
    if args.max_attempts <= 0:
        raise ValueError("--max-attempts must be positive")

    validate_layout()
    raw_sqls, payloads, schemas, sys_schemas, system_vars, comment_list = load_generation_data()

    # This direct connection check makes a failed database sidecar visible even
    # when a filler could otherwise fall back to placeholder values.
    connection_sample, connection_schema = select_database_sample(raw_sqls, schemas)
    mysql_config = get_mysql_config().copy()
    mysql_config["database"] = connection_sample["db"]
    filler = SpecificDatabaseTemplateFiller(connection_schema, mysql_config)
    if not filler.test_connection():
        raise RuntimeError("Database-specific synthesis could not connect to MySQL")

    record, attempts = synthesize_one_database_sample(
        raw_sqls,
        payloads,
        schemas,
        sys_schemas,
        system_vars,
        comment_list,
        args.max_attempts,
    )
    if record.get("label") is not False or "$$" in record.get("sql", ""):
        raise RuntimeError("Synthesis returned an invalid injection record")
    if re.search(r"\$(?:table|column|sample)_", record.get("payload", "")):
        raise RuntimeError("Database-specific placeholders remain after synthesis")

    sft_record = create_sft_format(record, schemas)
    messages = sft_record.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        raise RuntimeError("SFT formatter did not produce the expected three-message record")

    print(
        "Refactor smoke test passed; "
        f"database={connection_sample['db']}, synthesis_attempts={attempts}, sft_messages={len(messages)}"
    )


if __name__ == "__main__":
    main()
