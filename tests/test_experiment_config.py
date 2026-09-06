"""Regression coverage for the versioned experiment configuration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cosqli.experiment_config import load_experiment_config, resolved_experiment_config_sha256


class ExperimentConfigTests(unittest.TestCase):
    def test_current_configuration_has_the_eight_round_contract(self) -> None:
        config = load_experiment_config()
        self.assertEqual(config.random_seed, 42)
        self.assertEqual(config.num_rounds, 8)
        self.assertEqual(config.num_training_sqls, 300)
        self.assertEqual(config.prompt_mode, "query_only")
        self.assertEqual(config.attacker_clusters_per_round, 8)
        self.assertEqual(config.attacker_weight_exponent, 2.0)
        self.assertEqual(config.verifier_learning_rate, 1.0)
        self.assertEqual(config.verifier_reward_smoothing_alpha, 1.0)
        self.assertEqual(config.verifier_reward_smoothing_beta, 1.0)
        self.assertEqual(config.verifier_benign_fpr_target, 0.05)
        self.assertEqual(config.verifier_benign_ratio_step_size, 0.5)
        self.assertEqual(config.verifier_benign_error_ema_decay, 0.7)
        self.assertEqual(config.verifier_benign_ratio_min, 0.15)
        self.assertEqual(config.verifier_benign_ratio_max, 0.35)
        self.assertEqual(config.payload_mutation_weight_scale_min, 0.5)
        self.assertEqual(config.payload_mutation_effective_probability_max, 0.8)
        self.assertEqual(config.payload_mutation_llm_temperature, 0.7)
        self.assertEqual(config.payload_mutation_llm_max_tokens, 2000)
        self.assertEqual(config.payload_mutation_info_focused_probability, 0.3)
        self.assertTrue(config.payload_mutation_infer_expected_types)
        self.assertEqual(config.payload_mutation_types_inference_temperature, 0.3)
        self.assertEqual(config.payload_mutation_types_inference_max_tokens, 500)
        self.assertEqual(config.payload_mutation_fewshot_examples, 5)
        self.assertEqual(config.synthesis_cepp_rational_explanation_probability, 0.20)
        self.assertEqual(config.synthesis_cepp_llm_max_tokens, 96)
        self.assertEqual(config.synthesis_cepp_llm_max_retries, 0)
        self.assertTrue(config.mix_benign_sources)
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
            random_seed=123,
        )
        self.assertEqual(config.num_rounds, 2)
        self.assertEqual(config.num_training_sqls, 16)
        self.assertEqual(config.prompt_mode, "schema_aware")
        self.assertEqual(config.random_seed, 123)
        self.assertFalse(config.mix_benign_sources)
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

    def test_schema_aware_mode_resolves_benign_mixing_off(self) -> None:
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
            config = load_experiment_config(path)
            self.assertFalse(config.mix_benign_sources)

    def test_schema_v3_requires_complete_cepp_configuration(self) -> None:
        contents = """\
schema_version: 3
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
  update: centered_full_information_exponential
  learning_rate: 1
  reward_smoothing_alpha: 1
  reward_smoothing_beta: 1
  benign_fpr_target: 0.05
  benign_ratio_step_size: 0.5
  benign_error_ema_decay: 0.7
  benign_ratio_min: 0.15
  benign_ratio_max: 0.35
payload_mutation:
  enabled: true
  probability_start: 0.1
  probability_end: 0.4
  weight_scale_min: 0.5
  effective_probability_max: 0.8
  llm_temperature: 0.7
  llm_max_tokens: 2000
  info_focused_probability: 0.3
  infer_expected_types: true
  types_inference_temperature: 0.3
  types_inference_max_tokens: 500
  fewshot_examples: 5
  model: null
synthesis: {}
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "experiment.yaml"
            path.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "synthesis.cepp"):
                load_experiment_config(path)

if __name__ == "__main__":
    unittest.main()
