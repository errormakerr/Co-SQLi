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
                "train_sqls.json": ("train", 2560, 640),
                "valid_sqls.json": ("train", 1920, 40),
                "test_sqls.json": ("test", 3200, 800),
            },
        )

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
                "schema_version": 1,
                "source_files_sha256": source_hashes,
                "artifact_files_sha256": artifact_hashes,
                "datasets": {
                    "train_sqls.json": {
                        "source_split": "train",
                        "attack_count": 2560,
                        "benign_count": 640,
                    },
                    "valid_sqls.json": {
                        "source_split": "train",
                        "attack_count": 1920,
                        "benign_count": 40,
                    },
                    "test_sqls.json": {
                        "source_split": "test",
                        "attack_count": 3200,
                        "benign_count": 800,
                    },
                },
            }
            (benchmark_dir / "build_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            _validate_benchmark_contract(benchmark_dir)
            (benchmark_dir / "test_datas_openai_format.jsonl").write_text(
                "modified\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                _validate_benchmark_contract(benchmark_dir)


if __name__ == "__main__":
    unittest.main()
