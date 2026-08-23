#!/usr/bin/env python3
"""Build v3 taxonomy benchmarks into an external artifact directory."""

from __future__ import annotations

import argparse
import copy
import random
from pathlib import Path
from typing import Any, Dict, List

from cosqli.paths import PROJECT_ROOT, require_external_path
from cosqli.synthesis.injection_pipeline import pipeline
from cosqli.synthesis.sft_formatter import batch_process_to_sft
from cosqli.utils.cluster import (
    ClusterKey,
    PayloadCategoryKey,
    TAXONOMY_VERSION,
    all_attack_cluster_keys,
    cluster_injection_sqls,
    cluster_payload_templates,
)
from cosqli.utils.json_operation import read_json_file, write_json_file, write_jsonl_file


SOURCE_DIR = PROJECT_ROOT / "data" / "source"

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
    parser.add_argument("--output-dir", required=True, help="External benchmark artifact directory.")
    parser.add_argument("--seed", type=int, default=20260822, help="Deterministic generation seed.")
    return parser.parse_args()


def _counts_by_cluster(total_attacks: int) -> Dict[str, int]:
    clusters = all_attack_cluster_keys()
    base, remainder = divmod(total_attacks, len(clusters))
    return {
        cluster: base + (1 if index < remainder else 0)
        for index, cluster in enumerate(clusters)
    }


def _validate_source(payloads: List[Dict[str, Any]], raw_sqls: List[Dict[str, Any]]) -> None:
    for payload in payloads:
        PayloadCategoryKey(payload["technique"], payload["reference_scope"])
        core = payload.get("payload")
        if not isinstance(core, str) or not core or "--" in core or "#" in core:
            raise ValueError(f"Source payload must be a non-empty comment-free core: {payload!r}")
    for raw_sql in raw_sqls:
        if "$$" not in str(raw_sql.get("sql")):
            raise ValueError(f"Source SQL must contain an injection marker: {raw_sql!r}")
        if not isinstance(raw_sql.get("requires_comment_delimiter"), bool):
            raise ValueError(
                "Source SQL must declare requires_comment_delimiter explicitly: "
                f"{raw_sql!r}"
            )


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
        sql_candidates = [
            item
            for item in raw_sqls
            if item["requires_comment_delimiter"]
            is (cluster_key.comment_state != "no_comment")
        ]
        payload_candidates = payload_clusters.get(str(cluster_key.payload_category_key()), [])
        if not sql_candidates or not payload_candidates:
            raise RuntimeError(f"No source candidates for declared cluster {cluster}")
        for _ in range(count):
            for _attempt in range(128):
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
                if record is not None:
                    records.append(record)
                    break
            else:
                raise RuntimeError(f"Could not generate a valid sample for {cluster}")
    return records


def _pick_benign(normal_sqls: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if count > len(normal_sqls):
        raise ValueError(f"Requested {count} benign examples but only {len(normal_sqls)} are available")
    return copy.deepcopy(random.sample(normal_sqls, k=count))


def _validate_records(records: List[Dict[str, Any]], expected_attack_count: int) -> None:
    attacks = [record for record in records if not record["label"]]
    if len(attacks) != expected_attack_count:
        raise ValueError("Generated attack count does not match requested count")
    observed = set(cluster_injection_sqls(records)) - {"benign"}
    expected = set(all_attack_cluster_keys())
    if observed != expected:
        raise ValueError(
            f"Generated benchmark coverage mismatch: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )


def main() -> None:
    args = parse_args()
    output_dir = require_external_path(args.output_dir, purpose="benchmark output")
    output_dir.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)

    payloads = read_json_file(str(SOURCE_DIR / "payload_template.json"))
    raw_sqls = read_json_file(str(SOURCE_DIR / "sql_data_with_injection_point.json"))
    _validate_source(payloads, raw_sqls)
    db_schemas = read_json_file(str(SOURCE_DIR / "schema.json"))
    sys_schemas = read_json_file(str(SOURCE_DIR / "system_table_schema.json"))
    system_vars = read_json_file(str(SOURCE_DIR / "system_var.json"))
    comment_list = read_json_file(str(SOURCE_DIR / "comment_repository.json"))
    normal_sqls = read_json_file(str(SOURCE_DIR / "normal_sqls.json"))
    schema_by_database = {schema["database_name"]: schema for schema in db_schemas}

    write_json_file(
        str(output_dir / "build_manifest.json"),
        {"taxonomy_version": TAXONOMY_VERSION, "seed": args.seed},
    )
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
        write_json_file(str(output_dir / filename), records)
        sft_records = batch_process_to_sft(records, schema_by_database)
        if len(sft_records) != len(records):
            raise RuntimeError(f"SFT conversion dropped records for {filename}")
        write_jsonl_file(str(output_dir / SFT_FILENAMES[filename]), sft_records)
        print(f"Built {filename}: attacks={attack_count}, benign={benign_count}")


if __name__ == "__main__":
    main()
