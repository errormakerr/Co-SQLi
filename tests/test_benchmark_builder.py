"""Regression coverage for the external benchmark builder."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosqli.paths import PROJECT_ROOT
from cosqli.prompting import PROMPT_MODES, SFT_FILENAMES_BY_PROMPT_MODE, sft_filename
from cosqli.main import (
    BENCHMARK_ARTIFACT_FILENAMES,
    BENCHMARK_SOURCE_FILENAMES,
    _validate_benchmark_contract,
)


CLUSTER = "tautology||lor||no_comment"


def _builder_module():
    script = PROJECT_ROOT / "scripts" / "build_benchmarks.py"
    spec = importlib.util.spec_from_file_location("cosqli_benchmark_builder", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load benchmark builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchmarkBuilderTests(unittest.TestCase):
    def test_standard_dataset_sizes_are_stable(self) -> None:
        builder = _builder_module()
        self.assertEqual(
            builder.BENCHMARK_SPECS,
            {
                "train_sqls.json": ("train", 2560, 653),
                "valid_sqls.json": ("train", 1920, 40),
                "test_sqls.json": ("test", 3200, 873),
            },
        )
        self.assertEqual(set(builder.SFT_FILENAMES), set(PROMPT_MODES))

    def test_builder_refuses_to_replace_existing_artifacts(self) -> None:
        builder = _builder_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "benchmark"
            output_dir.mkdir()
            (output_dir / "existing.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "must be empty"):
                builder._prepare_output_directory(output_dir)

    def test_live_value_with_comment_marker_is_retried(self) -> None:
        builder = _builder_module()
        raw_sql = {"sql": "SELECT * FROM users WHERE id = $$", "requires_comment_delimiter": False}
        template = {"technique": "tautology", "reference_scope": "lor", "payload": "' OR 1=1"}
        expected_record = {"sql": "SELECT * FROM users WHERE id = ' OR 1=1", "label": False}
        with patch.object(
            builder, "_counts_by_cluster", return_value={CLUSTER: 1}
        ), patch.object(
            builder,
            "pipeline",
            side_effect=[
                ValueError("payload_core must not contain SQL line-comment delimiters"),
                expected_record,
            ],
        ) as mocked_pipeline:
            records = builder._build_attacks([raw_sql], [template], [], [], [], [], 1)
        self.assertEqual(records, [expected_record])
        self.assertEqual(mocked_pipeline.call_count, 2)

    def test_synthesis_audit_reports_attempt_outcomes(self) -> None:
        builder = _builder_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            audit = builder.SynthesisAudit(Path(temporary_directory), seed=7)
            for outcome in ("pipeline_returned_none", "success"):
                audit.record(
                    "attack_attempt",
                    dataset="train_sqls.json",
                    cluster=CLUSTER,
                    payload_template_source_index=4,
                    sql_carrier_source_index=2,
                    outcome=outcome,
                    cepp_comment_strategy=None,
                    synthesis_warnings=[],
                )
            audit.record(
                "final_record",
                dataset="train_sqls.json",
                output_index=0,
                label=False,
                record_sha256="record",
            )
            metadata = audit.write()
            summary = json.loads(
                (Path(temporary_directory) / metadata["summary_file"]).read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(summary["attack_attempt_count"], 2)
        self.assertEqual(
            summary["payload_template_source_index"]["4"],
            {
                "attempts": 2,
                "successes": 1,
                "failure_count": 1,
                "success_rate": 0.5,
                "outcomes": {"pipeline_returned_none": 1, "success": 1},
            },
        )
        self.assertEqual(summary["final_records"]["train_sqls.json"], {"attack": 1})
        self.assertEqual(summary["synthesis_warnings"]["total"], 0)

    def test_cepp_rational_plan_has_an_exact_twenty_percent_allocation(self) -> None:
        builder = _builder_module()
        choices, rational_count, cepp_count = builder._cepp_rational_plan(1920)

        self.assertEqual(cepp_count, 640)
        self.assertEqual(rational_count, 128)
        self.assertEqual(sum(choices), 128)

    def test_benign_comments_have_an_exact_ten_percent_allocation(self) -> None:
        builder = _builder_module()
        self.assertEqual(builder._benign_comment_count(653), 65)
        self.assertEqual(builder._benign_comment_count(40), 4)
        self.assertEqual(builder._benign_comment_count(873), 87)

    def test_pick_benign_appends_one_line_comment_without_raw_metadata(self) -> None:
        builder = _builder_module()
        normal_sqls = [
            {
                "db": "app",
                "sql": f"SELECT name FROM employees WHERE id = {index}",
                "label": True,
                "set": "train",
            }
            for index in range(10)
        ]
        normal_sqls[0]["sql"] += " -- Existing source annotation"
        with tempfile.TemporaryDirectory() as temporary_directory:
            audit = builder.SynthesisAudit(Path(temporary_directory), seed=3)
            with patch.object(
                builder,
                "generate_benign_comment",
                return_value=("Retrieve the requested employee record.", "test_strategy"),
            ), patch.object(builder, "choose_comment_prefix", return_value="# "):
                records = builder._pick_benign(
                    normal_sqls,
                    count=10,
                    comment_count=1,
                    allow_llm_comment=False,
                    dataset="train_sqls.json",
                    audit=audit,
                )
            metadata = audit.write()
            summary = json.loads(
                (Path(temporary_directory) / metadata["summary_file"]).read_text(
                    encoding="utf-8"
                )
            )

        annotated = [
            record
            for record in records
            if record["sql"].endswith("# Retrieve the requested employee record.")
        ]
        self.assertEqual(len(annotated), 1)
        self.assertEqual(set(annotated[0]), {"db", "sql", "label", "set"})
        self.assertIn(
            "SELECT name FROM employees WHERE id = 0 -- Existing source annotation",
            [record["sql"] for record in records],
        )
        self.assertEqual(
            summary["benign_comments"]["train_sqls.json"],
            {
                "selected": 10,
                "annotated": 1,
                "strategies": {"test_strategy": 1},
                "prefixes": {"# ": 1},
            },
        )

    def test_contract_rejects_modified_benchmark_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            benchmark_dir = Path(temporary_directory)
            for filename in BENCHMARK_ARTIFACT_FILENAMES:
                (benchmark_dir / filename).write_text(filename + "\n", encoding="utf-8")
            source_hashes = {
                filename: hashlib.sha256(
                    (PROJECT_ROOT / "data" / "source" / filename).read_bytes()
                ).hexdigest()
                for filename in BENCHMARK_SOURCE_FILENAMES
            }
            artifact_hashes = {
                filename: hashlib.sha256((benchmark_dir / filename).read_bytes()).hexdigest()
                for filename in BENCHMARK_ARTIFACT_FILENAMES
            }
            manifest = {
                "schema_version": 2,
                "source_files_sha256": source_hashes,
                "artifact_files_sha256": artifact_hashes,
                "prompt_modes": [mode.value for mode in PROMPT_MODES],
                "sft_files": {
                    mode.value: dict(SFT_FILENAMES_BY_PROMPT_MODE[mode])
                    for mode in PROMPT_MODES
                },
                "datasets": {
                    "train_sqls.json": {
                        "source_split": "train",
                        "attack_count": 2560,
                        "benign_count": 653,
                    },
                    "valid_sqls.json": {
                        "source_split": "train",
                        "attack_count": 1920,
                        "benign_count": 40,
                    },
                    "test_sqls.json": {
                        "source_split": "test",
                        "attack_count": 3200,
                        "benign_count": 873,
                    },
                },
            }
            (benchmark_dir / "build_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            _validate_benchmark_contract(benchmark_dir)
            manifest["datasets"]["train_sqls.json"]["rational_cepp_count"] = 171
            (benchmark_dir / "build_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            _validate_benchmark_contract(benchmark_dir)
            (benchmark_dir / sft_filename("test_sqls.json", "query_only")).write_text(
                "modified\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                _validate_benchmark_contract(benchmark_dir)


if __name__ == "__main__":
    unittest.main()
