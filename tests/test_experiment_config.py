"""Regression coverage for the versioned experiment configuration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cosqli.experiment_config import load_experiment_config, resolved_experiment_config_sha256
from cosqli.paths import PROJECT_ROOT


class ExperimentConfigTests(unittest.TestCase):
    def test_current_configuration_has_the_eight_round_contract(self) -> None:
        config = load_experiment_config()
        self.assertEqual(config.num_rounds, 8)
        self.assertEqual(config.num_training_sqls, 300)
        self.assertEqual(config.prompt_mode, "query_only")
        self.assertEqual(config.attacker_clusters_per_round, 8)
        self.assertEqual(config.attacker_weight_exponent, 2.0)
        self.assertEqual(config.verifier_learning_rate, 1.0)
        self.assertFalse(config.mix_benign_sources)
        self.assertEqual(
            config.verifier_update,
            "centered_full_information_exponential",
        )

    def test_execution_size_overrides_preserve_other_parameters(self) -> None:
        default_config = load_experiment_config()
        config = default_config.with_cli_overrides(
            num_rounds=2,
            num_training_sqls=16,
            prompt_mode="schema_aware",
        )
        self.assertEqual(config.num_rounds, 2)
        self.assertEqual(config.num_training_sqls, 16)
        self.assertEqual(config.prompt_mode, "schema_aware")
        self.assertEqual(config.attacker_clusters_per_round, 8)
        self.assertNotEqual(
            resolved_experiment_config_sha256(config),
            resolved_experiment_config_sha256(default_config),
        )

    def test_unknown_verifier_update_is_rejected(self) -> None:
        contents = """\
schema_version: 2
random_seed: 1
prompt_mode: query_only
num_rounds: 8
num_training_sqls: 300
initial_benign_ratio: 0.25
attacker:
  gamma_start: 0.7
  gamma_end: 0.2
  strategy: by_probability
  clusters_per_round: 8
  weight_exponent: 2
verifier:
  update: unsupported
  learning_rate: 1
payload_mutation:
  enabled: true
  probability_start: 0.1
  probability_end: 0.4
  model: null
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "experiment.yaml"
            path.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verifier update"):
                load_experiment_config(path)

    def test_mixed_benign_sources_require_query_only_prompts(self) -> None:
        contents = """\
schema_version: 2
random_seed: 1
prompt_mode: schema_aware
num_rounds: 8
num_training_sqls: 300
initial_benign_ratio: 0.25
mix_benign_sources: true
attacker:
  gamma_start: 0.7
  gamma_end: 0.2
  strategy: by_probability
  clusters_per_round: 8
  weight_exponent: 2
verifier:
  update: centered_full_information_exponential
  learning_rate: 1
payload_mutation:
  enabled: true
  probability_start: 0.1
  probability_end: 0.4
  model: null
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "experiment.yaml"
            path.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only supported for query_only"):
                load_experiment_config(path)

    def test_seed123_experiment_configs_enable_only_query_mixing(self) -> None:
        query_config = load_experiment_config(
            PROJECT_ROOT / "config" / "experiments" / "seed123-eta-1.00.yaml"
        )
        schema_config = load_experiment_config(
            PROJECT_ROOT
            / "config"
            / "experiments"
            / "schema-aware-seed123-eta-1.00.yaml"
        )
        self.assertEqual(query_config.random_seed, 123)
        self.assertTrue(query_config.mix_benign_sources)
        self.assertEqual(schema_config.random_seed, 123)
        self.assertFalse(schema_config.mix_benign_sources)


if __name__ == "__main__":
    unittest.main()
