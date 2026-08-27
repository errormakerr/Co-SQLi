"""Regression coverage for the versioned experiment configuration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cosqli.experiment_config import load_experiment_config


class ExperimentConfigTests(unittest.TestCase):
    def test_current_configuration_has_the_eight_round_contract(self) -> None:
        config = load_experiment_config()
        self.assertEqual(config.num_rounds, 8)
        self.assertEqual(config.num_training_sqls, 400)
        self.assertEqual(config.attacker_clusters_per_round, 8)
        self.assertEqual(config.attacker_weight_exponent, 2.0)
        self.assertEqual(config.verifier_learning_rate, 1.0)
        self.assertEqual(
            config.verifier_update,
            "centered_full_information_exponential",
        )

    def test_execution_size_overrides_preserve_other_parameters(self) -> None:
        config = load_experiment_config().with_cli_overrides(
            num_rounds=2,
            num_training_sqls=16,
        )
        self.assertEqual(config.num_rounds, 2)
        self.assertEqual(config.num_training_sqls, 16)
        self.assertEqual(config.attacker_clusters_per_round, 8)

    def test_unknown_verifier_update_is_rejected(self) -> None:
        contents = """\
schema_version: 1
random_seed: 1
num_rounds: 8
num_training_sqls: 400
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


if __name__ == "__main__":
    unittest.main()
