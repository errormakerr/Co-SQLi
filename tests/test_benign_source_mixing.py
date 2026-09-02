"""Regression coverage for opt-in query-only benign-source mixing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosqli.attacker import attacker as attacker_module
from cosqli.attacker.attacker import Attacker, ExternalBenignSource
from cosqli.paths import PROJECT_ROOT
from cosqli.prompting import PromptMode


class BenignSourceMixingTests(unittest.TestCase):
    def _write_source(
        self,
        directory: Path,
        *,
        name: str,
        sql_column: str,
        label_column: str,
        benign_label: str,
        prefix: str,
    ) -> ExternalBenignSource:
        path = directory / f"{name}.csv"
        rows = [f"{sql_column},{label_column}"]
        rows.extend(f"{prefix}{index},{benign_label}" for index in range(20))
        rows.append(f"{prefix}-malicious,not-{benign_label}")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return ExternalBenignSource(
            name=name,
            path=path,
            sql_column=sql_column,
            label_column=label_column,
            benign_label=benign_label,
        )

    def _attacker(self, *, mix_benign_sources: bool, prompt_mode: PromptMode) -> Attacker:
        return Attacker(
            number_of_training_sqls=300,
            cluster_list=["tautology||lor||no_comment"],
            normal_sqls_path=str(PROJECT_ROOT / "data" / "source" / "normal_sqls.json"),
            source_data_dir=str(PROJECT_ROOT / "data" / "source"),
            enable_payload_mutation=False,
            random_seed=123,
            prompt_mode=prompt_mode,
            mix_benign_sources=mix_benign_sources,
        )

    def test_query_only_mixing_balances_external_sources_and_rotates_remainders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            sources = (
                self._write_source(
                    directory,
                    name="rbsqli",
                    sql_column="sql_query",
                    label_column="vulnerability_status",
                    benign_label="No",
                    prefix="rbsqli",
                ),
                self._write_source(
                    directory,
                    name="SQLiV3",
                    sql_column="Sentence",
                    label_column="Label",
                    benign_label="0",
                    prefix="sqli-v3",
                ),
                self._write_source(
                    directory,
                    name="Superviz25",
                    sql_column="full_query",
                    label_column="label",
                    benign_label="0",
                    prefix="superviz",
                ),
            )
            with patch.object(attacker_module, "EXTERNAL_BENIGN_SOURCES", sources):
                attacker = self._attacker(
                    mix_benign_sources=True,
                    prompt_mode=PromptMode.QUERY_ONLY,
                )
                first_samples = attacker._sample_normal_sqls(75)
                first_stats = attacker._last_benign_sampling_stats
                second_samples = attacker._sample_normal_sqls(75)
                second_stats = attacker._last_benign_sampling_stats

        self.assertEqual(len(first_samples), 75)
        self.assertEqual(len(second_samples), 75)
        self.assertEqual(
            first_stats["source_counts"],
            {"normal_sqls_train": 37, "rbsqli": 13, "SQLiV3": 13, "Superviz25": 12},
        )
        self.assertEqual(
            second_stats["source_counts"],
            {"normal_sqls_train": 37, "rbsqli": 12, "SQLiV3": 13, "Superviz25": 13},
        )
        self.assertEqual(first_stats["external_round_robin_index"], 0)
        self.assertEqual(second_stats["external_round_robin_index"], 1)
        self.assertEqual(
            {name: values["available_benign_examples"] for name, values in first_stats["external_sources"].items()},
            {"rbsqli": 20, "SQLiV3": 20, "Superviz25": 20},
        )

    def test_mixing_is_rejected_for_schema_aware_prompts(self) -> None:
        with self.assertRaisesRegex(ValueError, "only supported for query_only"):
            self._attacker(
                mix_benign_sources=True,
                prompt_mode=PromptMode.SCHEMA_AWARE,
            )

    def test_default_sampling_does_not_read_external_sources(self) -> None:
        missing_source = ExternalBenignSource(
            name="missing",
            path=Path("/nonexistent/external-benign.csv"),
            sql_column="sql",
            label_column="label",
            benign_label="0",
        )
        with patch.object(attacker_module, "EXTERNAL_BENIGN_SOURCES", (missing_source,)):
            attacker = self._attacker(
                mix_benign_sources=False,
                prompt_mode=PromptMode.QUERY_ONLY,
            )
            samples = attacker._sample_normal_sqls(4)

        self.assertEqual(len(samples), 4)
        self.assertEqual(
            attacker._last_benign_sampling_stats["source_counts"],
            {"normal_sqls_train": 4},
        )


if __name__ == "__main__":
    unittest.main()
