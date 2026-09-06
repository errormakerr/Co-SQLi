"""Regression coverage for canonical and derived benchmark manifests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cosqli.main import (
    BENCHMARK_ARTIFACT_FILENAMES,
    BENCHMARK_SOURCE_FILENAMES,
    _json_fingerprint,
    _validate_benchmark_contract,
)
from cosqli.paths import PROJECT_ROOT
from cosqli.prompting import PROMPT_MODES, SFT_FILENAMES_BY_PROMPT_MODE
from cosqli.utils.cluster import TAXONOMY_VERSION, all_attack_cluster_keys


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DerivedBenchmarkContractTests(unittest.TestCase):
    def test_provenance_bound_train_subsample_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            benchmark_dir = Path(temporary_directory)
            records = []
            for cluster in all_attack_cluster_keys():
                technique, reference_scope, comment_state = cluster.split("||")
                records.extend(
                    {
                        "label": False,
                        "technique": technique,
                        "reference_scope": reference_scope,
                        "comment_state": comment_state,
                        "sql": f"SELECT {sample_number}",
                    }
                    for sample_number in range(40)
                )
            records.extend(
                {"label": True, "sql": f"SELECT benign_{sample_number}"}
                for sample_number in range(480)
            )
            (benchmark_dir / "train_sqls.json").write_text(
                json.dumps(records), encoding="utf-8"
            )

            parent = {
                "directory_name": "v6-full-benign-cepp-seed-20260831",
                "build_manifest_sha256": "a" * 64,
                "train_sqls_sha256": "b" * 64,
            }
            selection = {
                "schema_version": 1,
                "method": "uniform_stratified_by_attack_cluster",
                "sampling_seed": 42,
                "parent": parent,
                "records": [
                    {
                        "output_index": index,
                        "parent_index": index + 100,
                        "record_sha256": _json_fingerprint(record),
                        "label": record["label"],
                        "cluster": (
                            "benign"
                            if record["label"]
                            else "||".join(
                                (
                                    record["technique"],
                                    record["reference_scope"],
                                    record["comment_state"],
                                )
                            )
                        ),
                    }
                    for index, record in enumerate(records)
                ],
            }
            selection_path = benchmark_dir / "train_selection.json"
            selection_path.write_text(json.dumps(selection), encoding="utf-8")

            for filename in BENCHMARK_ARTIFACT_FILENAMES - {"train_sqls.json"}:
                (benchmark_dir / filename).write_text(filename + "\n", encoding="utf-8")
            manifest = {
                "schema_version": 3,
                "benchmark_type": "derived_train_subsample",
                "taxonomy_version": TAXONOMY_VERSION,
                "seed": 42,
                "prompt_modes": [mode.value for mode in PROMPT_MODES],
                "sft_files": {
                    mode.value: dict(SFT_FILENAMES_BY_PROMPT_MODE[mode])
                    for mode in PROMPT_MODES
                },
                "source_files_sha256": {
                    filename: _sha256(PROJECT_ROOT / "data" / "source" / filename)
                    for filename in BENCHMARK_SOURCE_FILENAMES
                },
                "datasets": {
                    "train_sqls.json": {
                        "source_split": "train",
                        "attack_count": 1920,
                        "benign_count": 480,
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
                "derivation": {
                    "method": "uniform_stratified_by_attack_cluster",
                    "content_generation": "none",
                    "sampling_seed": 42,
                    "parent": parent,
                    "target_train": {"attack_count": 1920, "benign_count": 480},
                    "selection_file": "train_selection.json",
                    "selection_file_sha256": _sha256(selection_path),
                },
                "artifact_files_sha256": {
                    filename: _sha256(benchmark_dir / filename)
                    for filename in BENCHMARK_ARTIFACT_FILENAMES
                },
            }
            (benchmark_dir / "build_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            _validate_benchmark_contract(benchmark_dir)

            selection["records"][0]["cluster"] = "benign"
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selection checksum mismatch"):
                _validate_benchmark_contract(benchmark_dir)


if __name__ == "__main__":
    unittest.main()
