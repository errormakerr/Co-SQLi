"""Unit tests for keeping benign samples outside the attack MAB."""

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Attacker.attacker import Attacker
from Verifier.verifier import Verifier
from main import (
    ATTACKER_K,
    ATTACKER_STRATEGY,
    ProjectPaths,
    run_training_loop,
    run_training_round,
)
from utils.cluster import NORMAL_CLUSTER_KEY, get_injection_cluster_keys
from utils.json_operation import read_json_file, write_json_file, write_jsonl_file


ATTACK_CLUSTER_A = "Tautologies attack||True||constant||False"
ATTACK_CLUSTER_B = "Error base attack||False||system information||False"


class MABSeparationTests(unittest.TestCase):
    def test_filters_benign_key_without_changing_attack_order(self) -> None:
        cluster_keys = [ATTACK_CLUSTER_A, NORMAL_CLUSTER_KEY, ATTACK_CLUSTER_B]
        self.assertEqual(
            get_injection_cluster_keys(cluster_keys),
            [ATTACK_CLUSTER_A, ATTACK_CLUSTER_B],
        )

    def test_attacker_probability_and_budget_ignore_benign_weight(self) -> None:
        attacker = object.__new__(Attacker)
        attacker.cluster_list = [ATTACK_CLUSTER_A, ATTACK_CLUSTER_B]
        attacker.benign_ratio = 0.25

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
        self.assertAlmostEqual(probabilities[ATTACK_CLUSTER_A], 0.425)
        self.assertAlmostEqual(probabilities[ATTACK_CLUSTER_B], 0.575)
        self.assertEqual(attacker._get_sample_counts(300), (225, 75))

    def test_verifier_rejects_benign_mab_arm_and_ignores_benign_results(self) -> None:
        with self.assertRaises(ValueError):
            Verifier([ATTACK_CLUSTER_A, NORMAL_CLUSTER_KEY])

        verifier = Verifier([ATTACK_CLUSTER_A])
        verifier.update_reward(
            [
                {
                    "label": False,
                    "type": "Tautologies attack",
                    "annotator": "True",
                    "information_features": "constant",
                    "comment": "False",
                    "predicted_answer": "benign",
                    "is_correct": False,
                },
                {
                    "label": True,
                    "predicted_answer": "malicious",
                    "is_correct": False,
                },
            ]
        )

        self.assertEqual(set(verifier.cluster_rewards), {ATTACK_CLUSTER_A})
        self.assertAlmostEqual(verifier.cluster_rewards[ATTACK_CLUSTER_A], 2 / 3)

    def test_verifier_uses_smoothed_fnr_and_exp3_weight(self) -> None:
        verifier = Verifier([ATTACK_CLUSTER_A, ATTACK_CLUSTER_B])
        verifier.update_reward(
            [
                {
                    "label": False,
                    "type": "Tautologies attack",
                    "annotator": "True",
                    "information_features": "constant",
                    "comment": "False",
                    "predicted_answer": "benign",
                    "is_correct": False,
                },
                {
                    "label": False,
                    "type": "Tautologies attack",
                    "annotator": "True",
                    "information_features": "constant",
                    "comment": "False",
                    "predicted_answer": "benign",
                    "is_correct": False,
                },
                {
                    "label": False,
                    "type": "Tautologies attack",
                    "annotator": "True",
                    "information_features": "constant",
                    "comment": "False",
                    "predicted_answer": "malicious",
                    "is_correct": True,
                },
                {
                    "label": False,
                    "type": "Error base attack",
                    "annotator": "False",
                    "information_features": "system information",
                    "comment": "False",
                    "predicted_answer": "malicious",
                    "is_correct": True,
                },
                {
                    "label": False,
                    "type": "Error base attack",
                    "annotator": "False",
                    "information_features": "system information",
                    "comment": "False",
                    "predicted_answer": "malicious",
                    "is_correct": True,
                },
            ]
        )

        self.assertAlmostEqual(verifier.cluster_rewards[ATTACK_CLUSTER_A], 3 / 5)
        self.assertAlmostEqual(verifier.cluster_rewards[ATTACK_CLUSTER_B], 1 / 4)

        verifier.update_weight(
            gamma=0.3,
            cluster_probability_distribution={
                ATTACK_CLUSTER_A: 0.4,
                ATTACK_CLUSTER_B: 0.6,
            },
        )
        self.assertAlmostEqual(verifier.get_weights()[ATTACK_CLUSTER_A], math.exp(0.225))
        self.assertAlmostEqual(verifier.get_weights()[ATTACK_CLUSTER_B], math.exp(0.0625))

    def test_verifier_rejects_incomplete_attack_feedback(self) -> None:
        verifier = Verifier([ATTACK_CLUSTER_A, ATTACK_CLUSTER_B])
        with self.assertRaises(ValueError):
            verifier.update_reward(
                [
                    {
                        "label": False,
                        "type": "Tautologies attack",
                        "annotator": "True",
                        "information_features": "constant",
                        "comment": "False",
                        "predicted_answer": "malicious",
                        "is_correct": True,
                    }
                ]
            )

    def test_benign_controller_updates_ratio_and_restores_state(self) -> None:
        verifier = Verifier([ATTACK_CLUSTER_A], benign_ratio=0.25)
        results = [
            {
                "label": True,
                "predicted_answer": "malicious" if index < 2 else "benign",
                "is_correct": index >= 2,
            }
            for index in range(10)
        ]

        self.assertAlmostEqual(verifier.update_benign_ratio(results), 0.2625)
        self.assertAlmostEqual(verifier.benign_error_ema, 0.075)

        restored = Verifier([ATTACK_CLUSTER_A])
        restored.set_benign_state(**verifier.get_benign_state())
        self.assertEqual(restored.get_benign_state(), verifier.get_benign_state())

    def test_benign_controller_clamps_ratio_bounds(self) -> None:
        all_false_positives = [
            {"label": True, "predicted_answer": "malicious", "is_correct": False}
            for _ in range(20)
        ]
        no_false_positives = [
            {"label": True, "predicted_answer": "benign", "is_correct": True}
            for _ in range(20)
        ]

        upper = Verifier([ATTACK_CLUSTER_A], benign_ratio=0.35)
        self.assertEqual(upper.update_benign_ratio(all_false_positives), 0.35)

        lower = Verifier([ATTACK_CLUSTER_A], benign_ratio=0.15)
        self.assertEqual(lower.update_benign_ratio(no_false_positives), 0.15)

    def test_round_persists_benign_controller_state(self) -> None:
        class FakeAttacker:
            def __init__(self) -> None:
                self.next_benign_ratio = None

            def generate_training_sqls(self, **_kwargs):
                return [], {ATTACK_CLUSTER_A: 1.0}

            def set_benign_ratio(self, benign_ratio: float) -> None:
                self.next_benign_ratio = benign_ratio

        class FakeDefender:
            def run_all(self, **_kwargs):
                return [
                    {
                        "label": False,
                        "type": "Tautologies attack",
                        "annotator": "True",
                        "information_features": "constant",
                        "comment": "False",
                        "predicted_answer": "malicious",
                        "is_correct": True,
                    },
                    {
                        "label": True,
                        "predicted_answer": "malicious",
                        "is_correct": False,
                    },
                ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_path = Path(temporary_directory)
            paths = ProjectPaths(
                project_root=temp_path,
                raw_datas_dir=temp_path,
                benchmark_dir=temp_path,
                temp_datas_dir=temp_path,
                config_dir=temp_path,
                base_model_path=temp_path,
            )
            attacker = FakeAttacker()
            verifier = Verifier([ATTACK_CLUSTER_A])

            with patch("main.ENABLE_PAYLOAD_MUTATION", False):
                run_training_round(
                    round_idx=0,
                    paths=paths,
                    attacker=attacker,
                    defender=FakeDefender(),
                    verifier=verifier,
                    strategy="by_probability",
                )

            persisted_state = read_json_file(
                str(temp_path / "round_0" / "verifier_state.json")
            )
            self.assertEqual(persisted_state, verifier.get_benign_state())
            self.assertEqual(attacker.next_benign_ratio, verifier.get_benign_ratio())

    def test_default_strategy_is_probability_sampling_for_every_round(self) -> None:
        class FakeAttacker:
            def __init__(self) -> None:
                self.calls = []

            def generate_training_sqls(self, **kwargs):
                self.calls.append(kwargs)
                return [], {ATTACK_CLUSTER_A: 1.0}

            def set_benign_ratio(self, _benign_ratio: float) -> None:
                pass

        class FakeDefender:
            def run_all(self, **_kwargs):
                return [
                    {
                        "label": False,
                        "type": "Tautologies attack",
                        "annotator": "True",
                        "information_features": "constant",
                        "comment": "False",
                        "predicted_answer": "malicious",
                        "is_correct": True,
                    },
                    {
                        "label": True,
                        "predicted_answer": "benign",
                        "is_correct": True,
                    },
                ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_path = Path(temporary_directory)
            paths = ProjectPaths(
                project_root=temp_path,
                raw_datas_dir=temp_path,
                benchmark_dir=temp_path,
                temp_datas_dir=temp_path,
                config_dir=temp_path,
                base_model_path=temp_path,
            )
            attacker = FakeAttacker()
            verifier = Verifier([ATTACK_CLUSTER_A])

            with patch("main.ENABLE_PAYLOAD_MUTATION", False):
                for round_idx in (0, 7):
                    run_training_round(
                        round_idx=round_idx,
                        paths=paths,
                        attacker=attacker,
                        defender=FakeDefender(),
                        verifier=verifier,
                        strategy=None,
                    )

        self.assertEqual(ATTACKER_STRATEGY, "by_probability")
        self.assertEqual(ATTACKER_K, 6)
        self.assertEqual(
            [call["strategy"] for call in attacker.calls],
            ["by_probability", "by_probability"],
        )
        self.assertEqual([call["k"] for call in attacker.calls], [6, 6])

    def test_breakpoint_restores_benign_controller_state(self) -> None:
        class FakeAttacker:
            mutation_memory = None

            def __init__(self) -> None:
                self.next_benign_ratio = None

            def set_benign_ratio(self, benign_ratio: float) -> None:
                self.next_benign_ratio = benign_ratio

        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_path = Path(temporary_directory)
            round_dir = temp_path / "round_7"
            write_jsonl_file(
                str(round_dir / "cluster_weights.jsonl"),
                [{"cluster": ATTACK_CLUSTER_A, "weight": 1.75}],
            )
            expected_state = {"benign_ratio": 0.31, "benign_error_ema": 0.19}
            write_json_file(str(round_dir / "verifier_state.json"), expected_state)

            paths = ProjectPaths(
                project_root=temp_path,
                raw_datas_dir=temp_path,
                benchmark_dir=temp_path,
                temp_datas_dir=temp_path,
                config_dir=temp_path,
                base_model_path=temp_path,
            )
            attacker = FakeAttacker()
            verifier = Verifier([ATTACK_CLUSTER_A])

            with (
                patch("main.ProjectPaths.create", return_value=paths),
                patch(
                    "main.initialize_components",
                    return_value=(attacker, object(), verifier),
                ),
                patch("main.os.chdir"),
                patch("main.run_training_round") as run_round,
            ):
                run_training_loop(start_round=0, breakpoint_round=7)

            run_round.assert_not_called()
            self.assertEqual(verifier.get_weights(), {ATTACK_CLUSTER_A: 1.75})
            self.assertEqual(verifier.get_benign_state(), expected_state)
            self.assertEqual(attacker.next_benign_ratio, expected_state["benign_ratio"])


if __name__ == "__main__":
    unittest.main()
