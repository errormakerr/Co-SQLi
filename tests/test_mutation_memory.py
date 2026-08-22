"""Regression tests for mutation few-shot memory and full-template records."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from synthesis.payload_mutation.memory import MutationMemory
from synthesis.payload_mutation.payload_mutator import PayloadMutator


ATTACK_TYPE = "Tautologies attack"
INFO_FEATURE = "constant"
REQUIRED_TEMPLATE_FIELDS = {
    "type",
    "payload",
    "expected_types",
    "information_features",
    "set",
}


def source_template(index: int) -> dict:
    return {
        "type": ATTACK_TYPE,
        "payload": f"' OR {index}={index}--",
        "expected_types": None,
        "information_features": INFO_FEATURE,
        "set": "train",
    }


def mutated_template(index: int) -> dict:
    template = source_template(index)
    template["payload"] = f"' OR MUTATED_{index}=MUTATED_{index}--"
    return template


class MutationMemoryTests(unittest.TestCase):
    def test_fewshot_prioritizes_mutations_then_fills_from_source_templates(self) -> None:
        memory = MutationMemory(source_templates=[source_template(index) for index in range(6)])
        memory.record_success(mutated_template(0))
        memory.record_success(mutated_template(1))

        fewshot = memory.get_fewshot_templates(ATTACK_TYPE, INFO_FEATURE)
        fewshot_payloads = {template["payload"] for template in fewshot}
        self.assertEqual(len(fewshot), 5)
        self.assertTrue(
            {mutated_template(0)["payload"], mutated_template(1)["payload"]}
            <= fewshot_payloads
        )
        self.assertTrue(
            all(REQUIRED_TEMPLATE_FIELDS <= set(template) for template in fewshot)
        )

        for index in range(2, 8):
            memory.record_success(mutated_template(index))

        category = memory.get_category(ATTACK_TYPE, INFO_FEATURE)
        self.assertEqual(len(category.mutated_templates), 8)
        all_mutated = {
            mutated_template(index)["payload"]
            for index in range(8)
        }
        self.assertTrue(
            all(template["payload"] in all_mutated for template in memory.get_fewshot_templates(ATTACK_TYPE, INFO_FEATURE))
        )
        self.assertEqual(memory.get_prompt_addons(ATTACK_TYPE, INFO_FEATURE).count("Example "), 5)

    def test_checkpoint_restore_preserves_complete_templates_and_upgrades_legacy_entries(self) -> None:
        sources = [source_template(index) for index in range(3)]
        memory = MutationMemory(source_templates=sources)
        memory.record_success(mutated_template(0))

        with tempfile.TemporaryDirectory() as temporary_directory:
            checkpoint_path = Path(temporary_directory) / "memory.json"
            memory.save(str(checkpoint_path))
            checkpoint = MutationMemory.load(str(checkpoint_path))
            restored = MutationMemory(source_templates=sources)
            restored.restore_mutations_from(checkpoint)

            restored_template = restored.get_category(
                ATTACK_TYPE, INFO_FEATURE
            ).mutated_templates[0]
            self.assertEqual(restored_template, mutated_template(0))

            legacy_path = Path(temporary_directory) / "legacy_memory.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "categories": {
                            f"{ATTACK_TYPE}|{INFO_FEATURE}": {
                                "attack_type": ATTACK_TYPE,
                                "info_feature": INFO_FEATURE,
                                "type_focused_examples": [
                                    {
                                        "original": sources[1]["payload"],
                                        "mutated": mutated_template(1)["payload"],
                                    }
                                ],
                                "info_focused_examples": [],
                                "fingerprints": [],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            legacy_checkpoint = MutationMemory.load(str(legacy_path))
            restored.restore_mutations_from(legacy_checkpoint)

        legacy_template = restored.get_category(
            ATTACK_TYPE, INFO_FEATURE
        ).mutated_templates[0]
        self.assertEqual(legacy_template, mutated_template(1))
        self.assertTrue(REQUIRED_TEMPLATE_FIELDS <= set(legacy_template))

    def test_mutator_records_a_complete_template_after_validation(self) -> None:
        class FakeLlm:
            def chat(self, *_args, **_kwargs) -> str:
                return "' OR 2=2--"

        class FakeValidator:
            def validate(self, _template, _mutated) -> SimpleNamespace:
                return SimpleNamespace(is_valid=True, reason="")

            def clean(self, mutated: str) -> str:
                return mutated

        original = source_template(1)
        memory = MutationMemory(source_templates=[original])
        mutator = PayloadMutator(
            llm=FakeLlm(),
            model="test-model",
            memory=memory,
            infer_types=False,
        )

        with patch(
            "synthesis.payload_mutation.payload_mutator.PayloadValidator",
            return_value=FakeValidator(),
        ):
            result = mutator.mutate(original)

        self.assertIsNotNone(result)
        self.assertEqual(result["template"]["payload"], "' OR 2=2--")
        self.assertTrue(REQUIRED_TEMPLATE_FIELDS <= set(result["template"]))
        stored = memory.get_category(ATTACK_TYPE, INFO_FEATURE).mutated_templates
        self.assertEqual(stored, [result["template"]])


if __name__ == "__main__":
    unittest.main()
