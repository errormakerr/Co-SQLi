#!/usr/bin/env python3
"""Migrate source assets and rebuild canonical taxonomy-v3 benchmarks.

The script intentionally derives benchmark metadata from the new generation
pipeline.  It never attempts to infer comment state from legacy benchmark
records, because those records do not retain enough structural information.
"""

from __future__ import annotations

import argparse
import copy
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from synthesis.injection_pipeline import pipeline
from synthesis.sft_formatter import batch_process_to_sft
from utils.cluster import (
    ClusterKey,
    TAXONOMY_VERSION,
    all_attack_cluster_keys,
    cluster_injection_sqls,
    cluster_payload_templates,
)
from utils.json_operation import read_json_file, write_json_file, write_jsonl_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw_datas_for_generation"
BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmark"

TECHNIQUE_MAP = {
    "Tautologies attack": "tautology",
    "Union-query attack": "union_query",
    "Piggy-backed queries attacks": "piggy_backed",
    "Error base attack": "error_based",
    "Boolean base inference attack": "boolean_blind",
    "Time base inference attack": "time_blind",
}
REFERENCE_SCOPE_MAP = {
    "constant": "lor",
    "specific database": "tsr",
    "system information": "scr",
}
COMMENT_SUFFIX_RE = re.compile(r"(?:--|#)\s*$")

BENCHMARK_SPECS = {
    "train_sqls.json": ("train", 1680, 657),
    "train_sqls_hard.json": ("train", 2276, 24),
    "valid_sqls.json": ("test", 960, 20),
    "test_sqls.json": ("test", 1738, 875),
}
SFT_FILENAMES = {
    "train_sqls.json": "train_datas_openai_format.jsonl",
    "train_sqls_hard.json": "train_datas_hard_openai_format.jsonl",
    "valid_sqls.json": "valid_datas_openai_format.jsonl",
    "test_sqls.json": "test_datas_openai_format.jsonl",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed", type=int, default=20260822, help="Deterministic generation seed."
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Migrate raw payload and carrier files without generating benchmarks.",
    )
    return parser.parse_args()


def _payload_core(payload: str) -> str:
    core = COMMENT_SUFFIX_RE.sub("", payload).rstrip()
    if "--" in core or "#" in core:
        raise ValueError(f"Payload contains a non-terminal comment marker: {payload!r}")
    if not core:
        raise ValueError(f"Payload became empty after removing terminal delimiter: {payload!r}")
    return core


def migrate_payloads(payloads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    migrated: List[Dict[str, Any]] = []
    for item in payloads:
        legacy_technique = item.get("technique", item.get("type"))
        legacy_scope = item.get("reference_scope", item.get("information_features"))
        technique = TECHNIQUE_MAP.get(legacy_technique, legacy_technique)
        reference_scope = REFERENCE_SCOPE_MAP.get(legacy_scope, legacy_scope)
        if not isinstance(technique, str) or not isinstance(reference_scope, str):
            raise ValueError(f"Unmapped payload taxonomy: {item!r}")
        migrated.append(
            {
                "technique": technique,
                "payload": _payload_core(str(item["payload"])),
                "expected_types": item.get("expected_types"),
                "reference_scope": reference_scope,
                "set": item["set"],
            }
        )
    return migrated


def migrate_raw_sqls(raw_sqls: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    migrated: List[Dict[str, Any]] = []
    for item in raw_sqls:
        sql = item.get("sql")
        if not isinstance(sql, str) or "$$" not in sql:
            raise ValueError(f"Raw SQL must contain one injection marker: {item!r}")
        migrated_item = {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key != "annotator"
        }
        suffix = sql.split("$$", 1)[1]
        migrated_item["requires_comment_delimiter"] = bool(suffix.strip())
        migrated.append(migrated_item)
    return migrated


def _counts_by_cluster(total_attacks: int) -> Dict[str, int]:
    clusters = all_attack_cluster_keys()
    base, remainder = divmod(total_attacks, len(clusters))
    return {
        cluster: base + (1 if index < remainder else 0)
        for index, cluster in enumerate(clusters)
    }


def _build_attacks(
    raw_sqls: List[Dict[str, Any]],
    payloads: List[Dict[str, Any]],
    db_schemas: List[Dict[str, Any]],
    sys_schemas: List[Dict[str, Any]],
    system_vars: List[Dict[str, Any]],
    comment_list: List[Dict[str, Any]],
    total_attacks: int,
) -> List[Dict[str, Any]]:
    payload_clusters = cluster_payload_templates(payloads)
    records: List[Dict[str, Any]] = []
    for cluster, count in _counts_by_cluster(total_attacks).items():
        cluster_key = ClusterKey.from_str(cluster)
        requires_delimiter = cluster_key.comment_state != "no_comment"
        sql_candidates = [
            item
            for item in raw_sqls
            if item["requires_comment_delimiter"] is requires_delimiter
        ]
        payload_candidates = payload_clusters.get(str(cluster_key.payload_category_key()), [])
        if not sql_candidates or not payload_candidates:
            raise RuntimeError(f"No source candidates for declared cluster {cluster}")

        for _ in range(count):
            last_error: Exception | None = None
            for attempt in range(128):
                try:
                    record = pipeline(
                        sql_example=random.choice(sql_candidates),
                        payload_template=random.choice(payload_candidates),
                        db_schemas=db_schemas,
                        sys_schemas=sys_schemas,
                        system_vars=system_vars,
                        comment_list=comment_list,
                        comment_state=cluster_key.comment_state,
                        allow_llm_comment=False,
                    )
                except (IndexError, KeyError, ValueError) as error:
                    last_error = error
                    continue
                if record is not None:
                    records.append(record)
                    break
            else:
                raise RuntimeError(
                    f"Could not generate a valid sample for {cluster} after 128 attempts. "
                    f"Last error: {last_error}"
                )
    return records


def _pick_benign(normal_sqls: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if count > len(normal_sqls):
        raise ValueError(f"Requested {count} benign examples but only {len(normal_sqls)} available")
    return copy.deepcopy(random.sample(normal_sqls, k=count))


def _validate_records(records: List[Dict[str, Any]], expected_attack_count: int) -> None:
    attack_records = [record for record in records if not record["label"]]
    if len(attack_records) != expected_attack_count:
        raise ValueError("Generated attack count does not match requested count")
    observed = set(cluster_injection_sqls(records)) - {"benign"}
    expected = set(all_attack_cluster_keys())
    if observed != expected:
        raise ValueError(
            f"Generated benchmark coverage mismatch: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )
    for record in attack_records:
        state = record["comment_state"]
        payload = record["payload"]
        core = record["payload_core"]
        requires = record["original_sql"]["requires_comment_delimiter"]
        if state == "no_comment":
            valid = not requires and "--" not in payload and "#" not in payload
        elif state == "clean_comment":
            valid = requires and payload == core + "-- "
        else:
            valid = requires and payload.startswith(core + "-- ") and bool(payload[len(core) + 3 :].strip())
        if not valid:
            raise ValueError(f"Invalid comment-state contract: {record!r}")


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    payloads = migrate_payloads(read_json_file(str(RAW_DIR / "payloads.json")))
    raw_sqls = migrate_raw_sqls(read_json_file(str(RAW_DIR / "sql_data_with_injection_point.json")))
    write_json_file(str(RAW_DIR / "payloads.json"), payloads)
    write_json_file(str(RAW_DIR / "sql_data_with_injection_point.json"), raw_sqls)
    print(f"Migrated raw taxonomy to v{TAXONOMY_VERSION}: payloads={len(payloads)}, raw_sqls={len(raw_sqls)}")

    if args.source_only:
        return

    db_schemas = read_json_file(str(RAW_DIR / "schema.json"))
    sys_schemas = read_json_file(str(RAW_DIR / "system_table_schema.json"))
    system_vars = read_json_file(str(RAW_DIR / "system_var.json"))
    comment_list = read_json_file(str(RAW_DIR / "comment_repository.json"))
    normal_sqls = read_json_file(str(RAW_DIR / "normal_sqls.json"))
    schema_by_database = {schema["database_name"]: schema for schema in db_schemas}

    for filename, (source_set, attack_count, benign_count) in BENCHMARK_SPECS.items():
        attacks = _build_attacks(
            [item for item in raw_sqls if item["set"] == source_set],
            [item for item in payloads if item["set"] == source_set],
            db_schemas,
            sys_schemas,
            system_vars,
            comment_list,
            attack_count,
        )
        benign_pool = [item for item in normal_sqls if item["set"] == source_set]
        records = attacks + _pick_benign(benign_pool, benign_count)
        random.shuffle(records)
        _validate_records(records, attack_count)
        write_json_file(str(BENCHMARK_DIR / filename), records)
        sft_records = batch_process_to_sft(records, schema_by_database)
        if len(sft_records) != len(records):
            raise RuntimeError(f"SFT conversion dropped records for {filename}")
        write_jsonl_file(str(BENCHMARK_DIR / SFT_FILENAMES[filename]), sft_records)
        print(
            f"Rebuilt {filename}: attacks={attack_count}, benign={benign_count}, "
            f"clusters={len(set(cluster_injection_sqls(records)) - {'benign'})}"
        )


if __name__ == "__main__":
    main()
