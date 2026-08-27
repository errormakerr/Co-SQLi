"""Regression tests for taxonomy, adversarial weights, and checkpoints."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosqli.attacker.attacker import Attacker
from cosqli.defender.defender import DefenderOutput, EvaluationOutput
from cosqli.verifier.verifier import Verifier
from cosqli.main import (
    ProjectPaths,
    attacker_gamma_for_round,
    run_training_loop,
    run_training_round,
)
from cosqli.paths import PROJECT_ROOT, require_external_path
from cosqli.synthesis.injection_pipeline import (
    SQL_COMMENT_PREFIXES,
    choose_comment_prefix,
    pipeline,
)
from cosqli.utils.cluster import (
    NORMAL_CLUSTER_KEY,
    TAXONOMY_VERSION,
    ClusterKey,
    PayloadCategoryKey,
    all_attack_cluster_keys,
    get_injection_cluster_keys,
)
from cosqli.utils.json_operation import read_json_file, write_json_file, write_jsonl_file


ATTACK_CLUSTER_A = "tautology||lor||no_comment"
ATTACK_CLUSTER_B = "error_based||scr||cepp"


def attack_result(cluster: str, predicted: str, correct: bool) -> dict:
    technique, reference_scope, comment_state = cluster.split("||")
    return {
        "label": False,
        "technique": technique,
        "reference_scope": reference_scope,
        "comment_state": comment_state,
        "predicted_answer": predicted,
        "is_correct": correct,
    }


class TaxonomyAndMABTests(unittest.TestCase):
    def test_project_local_artifacts_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the Co-SQLi repository"):
            require_external_path(PROJECT_ROOT / "generated", purpose="test output")

    def test_declared_taxonomy_has_exactly_48_stable_arms(self) -> None:
        arms = all_attack_cluster_keys()
        self.assertEqual(len(arms), 48)
        self.assertEqual(len(set(arms)), 48)
        self.assertEqual(arms[0], ATTACK_CLUSTER_A)
        self.assertEqual(arms[-1], "time_blind||scr||cepp")
        self.assertNotIn("boolean_blind||lor||no_comment", arms)
        self.assertNotIn("piggy_backed||lor||no_comment", arms)

    def test_cluster_and_payload_category_validation(self) -> None:
        self.assertEqual(str(ClusterKey.from_str(ATTACK_CLUSTER_A)), ATTACK_CLUSTER_A)
        self.assertEqual(
            str(PayloadCategoryKey("tautology", "lor")), "tautology||lor"
        )
        with self.assertRaises(ValueError):
            ClusterKey.from_str("tautology||lor||True||False")
        with self.assertRaises(ValueError):
            ClusterKey("boolean_blind", "lor", "no_comment")
        with self.assertRaises(ValueError):
            ClusterKey("tautology", "lor", "comment")

    def test_comment_state_contract_is_enforced(self) -> None:
        template = {
            "technique": "tautology",
            "reference_scope": "lor",
            "payload": "' OR 1=1",
            "expected_types": None,
            "set": "train",
        }
        no_comment_carrier = {
            "sql": "SELECT * FROM users WHERE id = $$",
            "db": "unused",
            "requires_comment_delimiter": False,
        }
        trailing_carrier = {
            "sql": "SELECT * FROM users WHERE name = '$$' ORDER BY id",
            "db": "unused",
            "requires_comment_delimiter": True,
        }
        with patch(
            "cosqli.synthesis.injection_pipeline.choose_comment_prefix",
            side_effect=("-- ", "# "),
        ):
            clean = pipeline(
                trailing_carrier, template, [], [], [], [], "clean_comment"
            )
            cepp = pipeline(
                trailing_carrier,
                template,
                [],
                [],
                [],
                [{"type": "Irrelevant text dilution", "comment": "routine validation"}],
                "cepp",
                allow_llm_comment=False,
            )
        self.assertEqual(clean["payload"], "' OR 1=1-- ")
        self.assertEqual(cepp["payload"], "' OR 1=1# routine validation")
        no_comment = pipeline(
            no_comment_carrier, template, [], [], [], [], "no_comment"
        )
        self.assertNotIn("--", no_comment["payload"])
        with self.assertRaises(ValueError):
            pipeline(no_comment_carrier, template, [], [], [], [], "clean_comment")

    def test_comment_prefix_is_chosen_from_both_supported_markers(self) -> None:
        with patch(
            "cosqli.synthesis.injection_pipeline.random.choice", return_value="# "
        ) as mocked_choice:
            self.assertEqual(choose_comment_prefix(), "# ")
        self.assertEqual(SQL_COMMENT_PREFIXES, ("-- ", "# "))
        mocked_choice.assert_called_once_with(SQL_COMMENT_PREFIXES)

    def test_filters_benign_key_without_changing_attack_order(self) -> None:
        self.assertEqual(
            get_injection_cluster_keys([ATTACK_CLUSTER_A, NORMAL_CLUSTER_KEY, ATTACK_CLUSTER_B]),
            [ATTACK_CLUSTER_A, ATTACK_CLUSTER_B],
        )

    def test_attacker_probability_and_budget_ignore_benign_weight(self) -> None:
        attacker = object.__new__(Attacker)
        attacker.cluster_list = [ATTACK_CLUSTER_A, ATTACK_CLUSTER_B]
        attacker.benign_ratio = 0.25
        attacker.weight_exponent = 2.0
        attacker._update_clusters_probability_distribution(
            gamma=0.7,
            clusters_weight_distribution={
                ATTACK_CLUSTER_A: 1.0,
                ATTACK_CLUSTER_B: 3.0,
                NORMAL_CLUSTER_KEY: 10_000.0,
            },
        )
        probabilities = attacker.clusters_probability_distribution
        self.assertEqual(set(probabilities), {ATTACK_CLUSTER_A, ATTACK_CLUSTER_B})
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
        self.assertAlmostEqual(probabilities[ATTACK_CLUSTER_A], 0.38)
        self.assertAlmostEqual(probabilities[ATTACK_CLUSTER_B], 0.62)
        self.assertEqual(attacker._get_sample_counts(300), (225, 75))

    def test_attacker_gamma_schedule_matches_the_eight_round_protocol(self) -> None:
        observed = [attacker_gamma_for_round(round_idx, 8) for round_idx in range(8)]
        expected = [0.70, 0.6285714286, 0.5571428571, 0.4857142857, 0.4142857143, 0.3428571429, 0.2714285714, 0.20]
        for actual, target in zip(observed, expected):
            self.assertAlmostEqual(actual, target)

    def test_attacker_filters_benign_sqls_to_the_train_split(self) -> None:
        attacker = Attacker(
            number_of_training_sqls=8,
            cluster_list=[ATTACK_CLUSTER_A, ATTACK_CLUSTER_B],
            normal_sqls_path=str(PROJECT_ROOT / "data" / "source" / "normal_sqls.json"),
            source_data_dir=str(PROJECT_ROOT / "data" / "source"),
            enable_payload_mutation=False,
        )
        self.assertTrue(attacker.normal_sqls)
        self.assertTrue(all(item["set"] == "train" for item in attacker.normal_sqls))

    def test_verifier_uses_smoothed_fnr_and_centered_full_information_weight(self) -> None:
        verifier = Verifier([ATTACK_CLUSTER_A, ATTACK_CLUSTER_B])
        verifier.update_reward(
            [
                attack_result(ATTACK_CLUSTER_A, "benign", False),
                attack_result(ATTACK_CLUSTER_A, "benign", False),
                attack_result(ATTACK_CLUSTER_A, "malicious", True),
                attack_result(ATTACK_CLUSTER_B, "malicious", True),
                attack_result(ATTACK_CLUSTER_B, "malicious", True),
                {"label": True, "predicted_answer": "malicious", "is_correct": False},
            ]
        )
        self.assertAlmostEqual(verifier.cluster_rewards[ATTACK_CLUSTER_A], 3 / 5)
        self.assertAlmostEqual(verifier.cluster_rewards[ATTACK_CLUSTER_B], 1 / 4)
        verifier.update_weight(learning_rate=0.3)
        self.assertAlmostEqual(verifier.get_last_reward_baseline(), 0.425)
        self.assertAlmostEqual(verifier.get_weights()[ATTACK_CLUSTER_A], math.exp(0.0525))
        self.assertAlmostEqual(verifier.get_weights()[ATTACK_CLUSTER_B], math.exp(-0.0525))

    def test_verifier_full_information_weight_is_probability_independent(self) -> None:
        verifier = Verifier([ATTACK_CLUSTER_A, ATTACK_CLUSTER_B])
        verifier.cluster_rewards = {
            ATTACK_CLUSTER_A: 0.25,
            ATTACK_CLUSTER_B: 0.25,
        }
        verifier.update_weight(learning_rate=0.3)
        self.assertAlmostEqual(verifier.get_last_reward_baseline(), 0.25)
        self.assertEqual(verifier.get_weights()[ATTACK_CLUSTER_A], 1.0)
        self.assertEqual(verifier.get_weights()[ATTACK_CLUSTER_B], 1.0)

    def test_verifier_rejects_missing_declared_feedback(self) -> None:
        verifier = Verifier([ATTACK_CLUSTER_A, ATTACK_CLUSTER_B])
        with self.assertRaises(ValueError):
            verifier.update_reward([attack_result(ATTACK_CLUSTER_A, "malicious", True)])

    def test_round_persists_taxonomy_metadata(self) -> None:
        class FakeAttacker:
            cluster_list = [ATTACK_CLUSTER_A]
            mutation_memory = None

            def generate_training_sqls(self, **_kwargs):
                return [], {ATTACK_CLUSTER_A: 1.0}

            def get_generation_stats(self):
                return {}

            def set_benign_ratio(self, _value: float) -> None:
                pass

        class FakeDefender:
            def run_all(self, **_kwargs):
                validation_results = [
                    attack_result(ATTACK_CLUSTER_A, "malicious", True),
                    {"label": True, "predicted_answer": "benign", "is_correct": True},
                ]
                test_results = [
                    attack_result(ATTACK_CLUSTER_A, "benign", False),
                    {"label": True, "predicted_answer": "malicious", "is_correct": False},
                ]
                return DefenderOutput(
                    validation=EvaluationOutput("validation", validation_results, {}, 0.0),
                    test=EvaluationOutput("test", test_results, {}, 0.0),
                    stages={},
                    training_metrics={},
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paths = ProjectPaths(root, root, root, root, root, root)
            verifier = Verifier([ATTACK_CLUSTER_A])
            with patch("cosqli.main.ENABLE_PAYLOAD_MUTATION", False):
                run_training_round(0, paths, FakeAttacker(), FakeDefender(), verifier)
            metadata = read_json_file(str(root / "round_0" / "round_metadata.json"))
            self.assertEqual(metadata["taxonomy_version"], TAXONOMY_VERSION)
            self.assertEqual(metadata["attack_clusters"], [ATTACK_CLUSTER_A])
            self.assertEqual(metadata["verifier_update"], "centered_full_information_exponential")
            self.assertEqual(metadata["verifier_learning_rate"], 1.0)
            self.assertAlmostEqual(metadata["verifier_reward_baseline"], 1 / 3)
            self.assertAlmostEqual(verifier.cluster_rewards[ATTACK_CLUSTER_A], 1 / 3)

    def test_breakpoint_rejects_missing_checkpoint_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paths = ProjectPaths(root, root, root, root, root, root)
            verifier = Verifier([ATTACK_CLUSTER_A])
            attacker = type("FakeAttacker", (), {"mutation_memory": None, "set_benign_ratio": lambda *_: None})()
            with patch("cosqli.main.ProjectPaths.create", return_value=paths), \
                 patch("cosqli.main.initialize_components", return_value=(attacker, object(), verifier)), \
                 patch("cosqli.main._sha256", return_value="test-checksum"), \
                 patch("cosqli.main.os.chdir"):
                with self.assertRaisesRegex(ValueError, "metadata is missing"):
                    run_training_loop(start_round=0, breakpoint_round=0)

    def test_breakpoint_restores_matching_taxonomy_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            round_dir = root / "round_0"
            write_json_file(
                str(round_dir / "round_metadata.json"),
                {"taxonomy_version": TAXONOMY_VERSION, "attack_clusters": [ATTACK_CLUSTER_A]},
            )
            write_jsonl_file(str(round_dir / "cluster_weights.jsonl"), [{"cluster": ATTACK_CLUSTER_A, "weight": 1.75}])
            write_json_file(str(round_dir / "verifier_state.json"), {"benign_ratio": 0.31, "benign_error_ema": 0.19})
            paths = ProjectPaths(root, root, root, root, root, root)
            verifier = Verifier([ATTACK_CLUSTER_A])
            attacker = type("FakeAttacker", (), {"mutation_memory": None, "set_benign_ratio": lambda *_: None})()
            with patch("cosqli.main.ProjectPaths.create", return_value=paths), \
                 patch("cosqli.main.initialize_components", return_value=(attacker, object(), verifier)), \
                 patch("cosqli.main._sha256", return_value="test-checksum"), \
                 patch("cosqli.main.os.chdir"), \
                 patch("cosqli.main.run_training_round") as run_round:
                run_training_loop(start_round=8, breakpoint_round=0)
            run_round.assert_not_called()
            self.assertEqual(verifier.get_weights(), {ATTACK_CLUSTER_A: 1.75})


if __name__ == "__main__":
    unittest.main()
