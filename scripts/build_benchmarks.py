#!/usr/bin/env python3
"""Build canonical taxonomy benchmarks into an external artifact directory."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from cosqli.paths import PROJECT_ROOT, require_external_path
from cosqli.prompting import (
    PROMPT_MODES,
    SFT_FILENAMES_BY_PROMPT_MODE,
    all_sft_filenames,
)
from cosqli.synthesis.injection_pipeline import (
    BENIGN_COMMENT_LLM_MAX_TOKENS,
    BENIGN_COMMENT_PROBABILITY,
    CEPP_LLM_MAX_RETRIES,
    CEPP_LLM_MAX_TOKENS,
    CEPP_RATIONAL_EXPLANATION_PROBABILITY,
    choose_comment_prefix,
    generate_benign_comment,
    pipeline,
)
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
    "train_sqls.json": ("train", 2560, 653),
    "valid_sqls.json": ("train", 1920, 40),
    "test_sqls.json": ("test", 3200, 873),
}
SFT_FILENAMES = SFT_FILENAMES_BY_PROMPT_MODE
SOURCE_FILENAMES = (
    "payload_template.json",
    "sql_data_with_injection_point.json",
    "schema.json",
    "system_table_schema.json",
    "system_var.json",
    "comment_repository.json",
    "normal_sqls.json",
)

AUDIT_EVENTS_FILENAME = "synthesis_events.jsonl"
AUDIT_SUMMARY_FILENAME = "synthesis_summary.json"


def _json_fingerprint(value: Any) -> str:
    """Return a deterministic hash without duplicating source content in audit logs."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class SynthesisAudit:
    """Collect one structured event per selection, attempt, and final record."""

    def __init__(self, output_dir: Path, seed: int) -> None:
        self._output_dir = output_dir
        self._events: List[Dict[str, Any]] = []
        self.record("build_started", seed=seed)

    def record(self, event_type: str, **fields: Any) -> None:
        self._events.append(
            {
                "event_index": len(self._events),
                "event_type": event_type,
                **fields,
            }
        )

    def write(self) -> Dict[str, Any]:
        events_path = self._output_dir / AUDIT_EVENTS_FILENAME
        write_jsonl_file(str(events_path), self._events)

        attempts = [
            event for event in self._events if event["event_type"] == "attack_attempt"
        ]
        final_records = [
            event for event in self._events if event["event_type"] == "final_record"
        ]
        by_dataset: Dict[str, Dict[str, Any]] = {}
        template_stats: Dict[str, Dict[str, Any]] = {}
        carrier_stats: Dict[str, Dict[str, Any]] = {}
        cluster_stats: Dict[str, Dict[str, Any]] = {}
        warning_kinds: Counter = Counter()
        warning_resources: Counter = Counter()
        benign_comment_stats: Dict[str, Dict[str, Any]] = {}
        for event in attempts:
            dataset = event["dataset"]
            dataset_stats = by_dataset.setdefault(
                dataset,
                {"attempts": 0, "outcomes": Counter(), "cepp_strategies": Counter()},
            )
            dataset_stats["attempts"] += 1
            dataset_stats["outcomes"][event["outcome"]] += 1
            if event.get("cepp_comment_strategy"):
                dataset_stats["cepp_strategies"][event["cepp_comment_strategy"]] += 1
            for warning in event.get("synthesis_warnings", []):
                warning_kinds[warning["kind"]] += 1
                resource = ".".join(
                    value
                    for value in (warning.get("database"), warning.get("table"))
                    if value
                )
                if resource:
                    warning_resources[resource] += 1

            for key, bucket in (
                ("payload_template_source_index", template_stats),
                ("sql_carrier_source_index", carrier_stats),
                ("cluster", cluster_stats),
            ):
                value = str(event[key])
                stat = bucket.setdefault(value, {"attempts": 0, "outcomes": Counter()})
                stat["attempts"] += 1
                stat["outcomes"][event["outcome"]] += 1

        def normalize(stats: Mapping[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
            result: Dict[str, Dict[str, Any]] = {}
            for key, value in sorted(stats.items(), key=lambda item: int(item[0]) if item[0].isdigit() else item[0]):
                outcomes = dict(sorted(value["outcomes"].items()))
                successes = outcomes.get("success", 0)
                result[key] = {
                    "attempts": value["attempts"],
                    "successes": successes,
                    "failure_count": value["attempts"] - successes,
                    "success_rate": successes / value["attempts"],
                    "outcomes": outcomes,
                }
            return result

        final_counts: Dict[str, Counter] = defaultdict(Counter)
        for event in final_records:
            final_counts[event["dataset"]]["benign" if event["label"] else "attack"] += 1

        for event in self._events:
            if event["event_type"] != "benign_selected":
                continue
            stats = benign_comment_stats.setdefault(
                event["dataset"],
                {
                    "selected": 0,
                    "annotated": 0,
                    "strategies": Counter(),
                    "prefixes": Counter(),
                },
            )
            stats["selected"] += 1
            if event.get("benign_comment_added"):
                stats["annotated"] += 1
                stats["strategies"][event["benign_comment_strategy"]] += 1
                stats["prefixes"][event["benign_comment_prefix"]] += 1

        summary = {
            "schema_version": 1,
            "event_count": len(self._events),
            "attack_attempt_count": len(attempts),
            "by_dataset": {
                dataset: {
                    "attempts": values["attempts"],
                    "outcomes": dict(sorted(values["outcomes"].items())),
                    "cepp_strategies": dict(sorted(values["cepp_strategies"].items())),
                }
                for dataset, values in sorted(by_dataset.items())
            },
            "payload_template_source_index": normalize(template_stats),
            "sql_carrier_source_index": normalize(carrier_stats),
            "cluster": normalize(cluster_stats),
            "synthesis_warnings": {
                "total": sum(warning_kinds.values()),
                "by_kind": dict(sorted(warning_kinds.items())),
                "by_resource": dict(sorted(warning_resources.items())),
            },
            "benign_comments": {
                dataset: {
                    "selected": values["selected"],
                    "annotated": values["annotated"],
                    "strategies": dict(sorted(values["strategies"].items())),
                    "prefixes": dict(sorted(values["prefixes"].items())),
                }
                for dataset, values in sorted(benign_comment_stats.items())
            },
            "final_records": {
                dataset: dict(sorted(counts.items()))
                for dataset, counts in sorted(final_counts.items())
            },
        }
        summary_path = self._output_dir / AUDIT_SUMMARY_FILENAME
        write_json_file(str(summary_path), summary)
        return {
            "events_file": AUDIT_EVENTS_FILENAME,
            "events_sha256": _sha256(events_path),
            "summary_file": AUDIT_SUMMARY_FILENAME,
            "summary_sha256": _sha256(summary_path),
            "event_count": len(self._events),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="External benchmark artifact directory.")
    parser.add_argument("--seed", type=int, default=20260827, help="Deterministic generation seed.")
    parser.add_argument(
        "--allow-llm-comments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Generate query-specific CEPP and benign-comment explanations. Use "
            "--no-allow-llm-comments for an offline deterministic build."
        ),
    )
    parser.add_argument(
        "--cepp-llm-timeout-seconds",
        type=float,
        default=45.0,
        help="Per-request timeout for query-specific CEPP generation.",
    )
    parser.add_argument(
        "--cepp-llm-max-tokens",
        type=int,
        default=CEPP_LLM_MAX_TOKENS,
        help="Maximum completion tokens for one query-specific CEPP explanation.",
    )
    parser.add_argument(
        "--cepp-llm-max-retries",
        type=int,
        default=CEPP_LLM_MAX_RETRIES,
        help="SDK retries per query-specific CEPP explanation.",
    )
    args = parser.parse_args()
    if args.cepp_llm_timeout_seconds <= 0:
        parser.error("--cepp-llm-timeout-seconds must be positive")
    if args.cepp_llm_max_tokens <= 0:
        parser.error("--cepp-llm-max-tokens must be positive")
    if args.cepp_llm_max_retries < 0:
        parser.error("--cepp-llm-max-retries must be non-negative")
    return args


def _counts_by_cluster(total_attacks: int) -> Dict[str, int]:
    clusters = all_attack_cluster_keys()
    base, remainder = divmod(total_attacks, len(clusters))
    return {
        cluster: base + (1 if index < remainder else 0)
        for index, cluster in enumerate(clusters)
    }


def _cepp_rational_plan(total_attacks: int) -> Tuple[Iterator[bool], int, int]:
    """Allocate the rational CEPP class exactly, then randomize its placement."""
    cepp_count = sum(
        count
        for cluster, count in _counts_by_cluster(total_attacks).items()
        if ClusterKey.from_str(cluster).comment_state == "cepp"
    )
    rational_count = round(cepp_count * CEPP_RATIONAL_EXPLANATION_PROBABILITY)
    choices = [True] * rational_count + [False] * (cepp_count - rational_count)
    random.shuffle(choices)
    return iter(choices), rational_count, cepp_count


def _benign_comment_count(total_benign: int) -> int:
    """Return the exact nearest-integer number of annotated benign samples."""
    return round(total_benign * BENIGN_COMMENT_PROBABILITY)


def _validate_source(payloads: List[Dict[str, Any]], raw_sqls: List[Dict[str, Any]]) -> None:
    for payload in payloads:
        PayloadCategoryKey(payload["technique"], payload["reference_scope"])
        if payload.get("set") not in {"train", "test"}:
            raise ValueError(f"Source payload must declare set=train or set=test: {payload!r}")
        core = payload.get("payload")
        if not isinstance(core, str) or not core or "--" in core or "#" in core:
            raise ValueError(f"Source payload must be a non-empty comment-free core: {payload!r}")
    for raw_sql in raw_sqls:
        if raw_sql.get("set") not in {"train", "test"}:
            raise ValueError(f"Source SQL must declare set=train or set=test: {raw_sql!r}")
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
    allow_llm_comment: bool = True,
    cepp_llm_timeout_seconds: Optional[float] = None,
    cepp_llm_max_tokens: int = CEPP_LLM_MAX_TOKENS,
    cepp_llm_max_retries: int = CEPP_LLM_MAX_RETRIES,
    cepp_rational_choices: Optional[Iterator[bool]] = None,
    *,
    dataset: str = "unspecified",
    audit: Optional[SynthesisAudit] = None,
    raw_source_indices: Optional[Mapping[int, int]] = None,
    payload_source_indices: Optional[Mapping[int, int]] = None,
) -> List[Dict[str, Any]]:
    payload_clusters = cluster_payload_templates(payloads)
    raw_source_indices = raw_source_indices or {
        id(item): index for index, item in enumerate(raw_sqls)
    }
    payload_source_indices = payload_source_indices or {
        id(item): index for index, item in enumerate(payloads)
    }
    if cepp_rational_choices is None:
        cepp_rational_choices, _, _ = _cepp_rational_plan(total_attacks)
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
        for sample_number in range(count):
            cepp_use_rational = (
                next(cepp_rational_choices)
                if cluster_key.comment_state == "cepp"
                else None
            )
            for attempt_number in range(1, 129):
                sql_candidate = random.choice(sql_candidates)
                payload_candidate = random.choice(payload_candidates)
                event = {
                    "dataset": dataset,
                    "cluster": cluster,
                    "sample_number_in_cluster": sample_number,
                    "attempt_number": attempt_number,
                    "sql_carrier_source_index": raw_source_indices[id(sql_candidate)],
                    "sql_carrier_sha256": _json_fingerprint(sql_candidate),
                    "payload_template_source_index": payload_source_indices[id(payload_candidate)],
                    "payload_template_sha256": _json_fingerprint(payload_candidate),
                    "comment_state": cluster_key.comment_state,
                    "cepp_rational_requested": cepp_use_rational,
                }
                try:
                    record = pipeline(
                        sql_example=sql_candidate,
                        payload_template=payload_candidate,
                        db_schemas=db_schemas,
                        sys_schemas=sys_schemas,
                        system_vars=system_vars,
                        comment_list=comment_list,
                        comment_state=cluster_key.comment_state,
                        allow_llm_comment=allow_llm_comment,
                        cepp_llm_timeout_seconds=cepp_llm_timeout_seconds,
                        cepp_llm_max_tokens=cepp_llm_max_tokens,
                        cepp_llm_max_retries=cepp_llm_max_retries,
                        cepp_use_rational=cepp_use_rational,
                    )
                except ValueError as error:
                    # A live sample value can contain a line-comment marker.
                    # Reject that candidate while retaining contract failures.
                    if audit is not None:
                        audit.record(
                            "attack_attempt",
                            **event,
                            outcome="retry_payload_core_contains_comment_marker",
                            error_type=type(error).__name__,
                            error_message=str(error),
                        )
                    if str(error) != "payload_core must not contain SQL line-comment delimiters":
                        raise
                    continue
                except Exception as error:
                    if audit is not None:
                        audit.record(
                            "attack_attempt",
                            **event,
                            outcome="fatal_exception",
                            error_type=type(error).__name__,
                            error_message=str(error),
                        )
                    raise
                if record is not None:
                    cepp_comment_strategy = record.pop("cepp_comment_strategy", None)
                    synthesis_warnings = record.pop("synthesis_warnings", [])
                    if audit is not None:
                        audit.record(
                            "attack_attempt",
                            **event,
                            outcome="success",
                            generated_record_sha256=_json_fingerprint(record),
                            payload_core_sha256=_json_fingerprint(record["payload_core"]),
                            payload_sha256=_json_fingerprint(record["payload"]),
                            cepp_comment_strategy=cepp_comment_strategy,
                            synthesis_warnings=synthesis_warnings,
                        )
                    records.append(record)
                    break
                if audit is not None:
                    audit.record(
                        "attack_attempt",
                        **event,
                        outcome="pipeline_returned_none",
                    )
            else:
                raise RuntimeError(f"Could not generate a valid sample for {cluster}")
    return records


def _pick_benign(
    normal_sqls: List[Dict[str, Any]],
    count: int,
    comment_count: int = 0,
    allow_llm_comment: bool = True,
    llm_timeout_seconds: Optional[float] = None,
    llm_max_retries: int = CEPP_LLM_MAX_RETRIES,
    *,
    dataset: str = "unspecified",
    audit: Optional[SynthesisAudit] = None,
    normal_source_indices: Optional[Mapping[int, int]] = None,
) -> List[Dict[str, Any]]:
    """Select benign records and append short comments to the requested subset.

    Existing line-comment SQL is retained as a plain record but never selected
    for a second appended comment, so the added annotation remains executable
    MySQL syntax rather than becoming part of an earlier comment.
    """
    if count > len(normal_sqls):
        raise ValueError(f"Requested {count} benign examples but only {len(normal_sqls)} are available")
    if not 0 <= comment_count <= count:
        raise ValueError("benign comment count must be between zero and the benign count")
    normal_source_indices = normal_source_indices or {
        id(item): index for index, item in enumerate(normal_sqls)
    }
    annotatable = [
        item
        for item in normal_sqls
        if isinstance(item.get("sql"), str)
        and item["sql"].strip()
        and "\n" not in item["sql"]
        and "\r" not in item["sql"]
        and "--" not in item["sql"]
        and "#" not in item["sql"]
    ]
    if comment_count > len(annotatable):
        raise ValueError(
            "Requested more benign annotations than safe comment-free SQL candidates"
        )
    annotated_source = random.sample(annotatable, k=comment_count)
    annotated_ids = {id(item) for item in annotated_source}
    plain_source = random.sample(
        [item for item in normal_sqls if id(item) not in annotated_ids],
        k=count - comment_count,
    )
    selected_with_flags = [(item, True) for item in annotated_source] + [
        (item, False) for item in plain_source
    ]
    records: List[Dict[str, Any]] = []
    for selection_index, (source_record, add_comment) in enumerate(selected_with_flags):
        record = copy.deepcopy(source_record)
        strategy = None
        prefix = None
        if add_comment:
            comment, strategy = generate_benign_comment(
                record["sql"],
                str(record.get("db", "")),
                allow_llm=allow_llm_comment,
                llm_timeout_seconds=llm_timeout_seconds,
                llm_max_retries=llm_max_retries,
            )
            prefix = choose_comment_prefix()
            record["sql"] = f"{record['sql'].rstrip()} {prefix}{comment}"
        records.append(record)
        if audit is not None:
            audit.record(
                "benign_selected",
                dataset=dataset,
                selection_index=selection_index,
                normal_sql_source_index=normal_source_indices[id(source_record)],
                normal_sql_sha256=_json_fingerprint(source_record),
                benign_comment_added=add_comment,
                benign_comment_strategy=strategy,
                benign_comment_prefix=prefix,
                generated_record_sha256=_json_fingerprint(record),
            )
    return records


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


def _sha256(path: Path) -> str:
    """Return a content fingerprint for a source or generated artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_output_directory(output_dir: Path) -> None:
    """Create an empty external directory for one immutable benchmark build."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Benchmark output directory must be empty: {output_dir}. "
            "Choose a new external directory for each build."
        )
    output_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    output_dir = require_external_path(args.output_dir, purpose="benchmark output")
    _prepare_output_directory(output_dir)
    random.seed(args.seed)
    audit = SynthesisAudit(output_dir, args.seed)

    try:
        source_files = {name: SOURCE_DIR / name for name in SOURCE_FILENAMES}
        payloads = read_json_file(str(source_files["payload_template.json"]))
        raw_sqls = read_json_file(str(source_files["sql_data_with_injection_point.json"]))
        _validate_source(payloads, raw_sqls)
        db_schemas = read_json_file(str(source_files["schema.json"]))
        sys_schemas = read_json_file(str(source_files["system_table_schema.json"]))
        system_vars = read_json_file(str(source_files["system_var.json"]))
        comment_list = read_json_file(str(source_files["comment_repository.json"]))
        normal_sqls = read_json_file(str(source_files["normal_sqls.json"]))
        if any(item.get("set") not in {"train", "test"} for item in normal_sqls):
            raise ValueError("Each benign source SQL must declare set=train or set=test")
        audit.record(
            "sources_loaded",
            payload_template_count=len(payloads),
            sql_carrier_count=len(raw_sqls),
            benign_sql_count=len(normal_sqls),
            comment_count=len(comment_list),
        )
        schema_by_database = {schema["database_name"]: schema for schema in db_schemas}
        raw_source_indices = {id(item): index for index, item in enumerate(raw_sqls)}
        payload_source_indices = {id(item): index for index, item in enumerate(payloads)}
        normal_source_indices = {id(item): index for index, item in enumerate(normal_sqls)}

        build_manifest = {
            "schema_version": 2,
            "taxonomy_version": TAXONOMY_VERSION,
            "seed": args.seed,
            "cepp": {
                "allow_llm_comments": args.allow_llm_comments,
                "rational_explanation_probability": CEPP_RATIONAL_EXPLANATION_PROBABILITY,
                "llm_timeout_seconds": args.cepp_llm_timeout_seconds,
                "llm_max_tokens": args.cepp_llm_max_tokens,
                "llm_max_retries": args.cepp_llm_max_retries,
            },
            "benign_comments": {
                "explanation_probability": BENIGN_COMMENT_PROBABILITY,
                "allow_llm_comments": args.allow_llm_comments,
                "llm_timeout_seconds": args.cepp_llm_timeout_seconds,
                "llm_max_tokens": BENIGN_COMMENT_LLM_MAX_TOKENS,
                "llm_max_retries": args.cepp_llm_max_retries,
            },
            "prompt_modes": [mode.value for mode in PROMPT_MODES],
            "sft_files": {
                mode.value: dict(SFT_FILENAMES[mode])
                for mode in PROMPT_MODES
            },
            "source_files_sha256": {
                name: _sha256(path) for name, path in sorted(source_files.items())
            },
            "datasets": {
                filename: {
                    "source_split": source_set,
                    "attack_count": attack_count,
                    "benign_count": benign_count,
                }
                for filename, (source_set, attack_count, benign_count) in BENCHMARK_SPECS.items()
            },
        }
        for filename, (source_set, attack_count, benign_count) in BENCHMARK_SPECS.items():
            cepp_rational_choices, cepp_rational_count, cepp_count = _cepp_rational_plan(
                attack_count
            )
            build_manifest["datasets"][filename]["cepp_count"] = cepp_count
            build_manifest["datasets"][filename]["rational_cepp_count"] = cepp_rational_count
            build_manifest["datasets"][filename]["benign_comment_count"] = (
                _benign_comment_count(benign_count)
            )
            attacks = _build_attacks(
                [item for item in raw_sqls if item["set"] == source_set],
                [item for item in payloads if item["set"] == source_set],
                db_schemas,
                sys_schemas,
                system_vars,
                comment_list,
                attack_count,
                allow_llm_comment=args.allow_llm_comments,
                cepp_llm_timeout_seconds=args.cepp_llm_timeout_seconds,
                cepp_llm_max_tokens=args.cepp_llm_max_tokens,
                cepp_llm_max_retries=args.cepp_llm_max_retries,
                cepp_rational_choices=cepp_rational_choices,
                dataset=filename,
                audit=audit,
                raw_source_indices=raw_source_indices,
                payload_source_indices=payload_source_indices,
            )
            benign_pool = [item for item in normal_sqls if item["set"] == source_set]
            records = attacks + _pick_benign(
                benign_pool,
                benign_count,
                comment_count=_benign_comment_count(benign_count),
                allow_llm_comment=args.allow_llm_comments,
                llm_timeout_seconds=args.cepp_llm_timeout_seconds,
                llm_max_retries=args.cepp_llm_max_retries,
                dataset=filename,
                audit=audit,
                normal_source_indices=normal_source_indices,
            )
            random.shuffle(records)
            _validate_records(records, attack_count)
            for output_index, record in enumerate(records):
                audit.record(
                    "final_record",
                    dataset=filename,
                    output_index=output_index,
                    label=record["label"],
                    record_sha256=_json_fingerprint(record),
                )
            write_json_file(str(output_dir / filename), records)
            for prompt_mode in PROMPT_MODES:
                sft_records = batch_process_to_sft(
                    records,
                    schema_by_database,
                    prompt_mode=prompt_mode,
                )
                if len(sft_records) != len(records):
                    raise RuntimeError(
                        f"SFT conversion dropped records for {filename} ({prompt_mode.value})"
                    )
                write_jsonl_file(
                    str(output_dir / SFT_FILENAMES[prompt_mode][filename]),
                    sft_records,
                )
            print(f"Built {filename}: attacks={attack_count}, benign={benign_count}")
        audit.record("build_completed")
        build_manifest["synthesis_audit"] = audit.write()
        build_manifest["artifact_files_sha256"] = {
            filename: _sha256(output_dir / filename)
            for filename in sorted(set(BENCHMARK_SPECS) | all_sft_filenames())
        }
        write_json_file(str(output_dir / "build_manifest.json"), build_manifest)
    except BaseException as error:
        audit.record(
            "build_failed",
            error_type=type(error).__name__,
            error_message=str(error),
        )
        audit.write()
        raise


if __name__ == "__main__":
    main()
