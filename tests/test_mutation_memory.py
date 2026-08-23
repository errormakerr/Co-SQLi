"""Regression tests for taxonomy-v3 payload-core mutation memory."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cosqli.synthesis.payload_mutation.memory import MutationMemory
from cosqli.synthesis.payload_mutation.payload_mutator import PayloadMutator
from cosqli.utils.cluster import TAXONOMY_VERSION


TECHNIQUE = "tautology"
REFERENCE_SCOPE = "lor"
REQUIRED_TEMPLATE_FIELDS = {
    "technique",
    "payload",
    "expected_types",
    "reference_scope",
    "set",
}


def source_template(index: int) -> dict:
    return {
        "technique": TECHNIQUE,
        "payload": f"' OR {index}={index}",
        "expected_types": None,
        "reference_scope": REFERENCE_SCOPE,
        "set": "train",
    }


def mutated_template(index: int) -> dict:
    template = source_template(index)
    template["payload"] = f"' OR MUTATED_{index}=MUTATED_{index}"
    return template


class MutationMemoryTests(unittest.TestCase):
    def test_fewshot_prioritizes_mutations_then_source_without_cap(self) -> None:
        memory = MutationMemory(source_templates=[source_template(index) for index in range(6)])
        memory.record_success(mutated_template(0))
        memory.record_success(mutated_template(1))

        fewshot = memory.get_fewshot_templates(TECHNIQUE, REFERENCE_SCOPE)
        fewshot_payloads = {template["payload"] for template in fewshot}
        self.assertEqual(len(fewshot), 5)
        self.assertTrue({mutated_template(0)["payload"], mutated_template(1)["payload"]} <= fewshot_payloads)
        self.assertTrue(all(REQUIRED_TEMPLATE_FIELDS <= set(template) for template in fewshot))

        for index in range(2, 8):
            memory.record_success(mutated_template(index))
        category = memory.get_category(TECHNIQUE, REFERENCE_SCOPE)
        self.assertEqual(len(category.mutated_templates), 8)
        self.assertEqual(memory.get_prompt_addons(TECHNIQUE, REFERENCE_SCOPE).count("Example "), 5)

    def test_memory_rejects_comment_delimiters_and_old_checkpoints(self) -> None:
        invalid = source_template(0)
        invalid["payload"] += "-- "
        with self.assertRaisesRegex(ValueError, "comment-free"):
            MutationMemory(source_templates=[invalid])

        with tempfile.TemporaryDirectory() as temporary_directory:
            legacy_path = Path(temporary_directory) / "legacy_memory.json"
            legacy_path.write_text(json.dumps({"format_version": 0, "categories": {}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "taxonomy mismatch"):
                MutationMemory.load(str(legacy_path))

    def test_checkpoint_restores_complete_templates(self) -> None:
        sources = [source_template(index) for index in range(3)]
        memory = MutationMemory(source_templates=sources)
        memory.record_success(mutated_template(0))
        with tempfile.TemporaryDirectory() as temporary_directory:
            checkpoint_path = Path(temporary_directory) / "memory.json"
            memory.save(str(checkpoint_path))
            checkpoint = MutationMemory.load(str(checkpoint_path))
            self.assertEqual(
                json.loads(checkpoint_path.read_text(encoding="utf-8"))["taxonomy_version"],
                TAXONOMY_VERSION,
            )
            restored = MutationMemory(source_templates=sources)
            restored.restore_mutations_from(checkpoint)
        self.assertEqual(
            restored.get_category(TECHNIQUE, REFERENCE_SCOPE).mutated_templates,
            [mutated_template(0)],
        )

    def test_mutator_records_complete_comment_free_template(self) -> None:
        class FakeLlm:
            def chat(self, *_args, **_kwargs) -> str:
                return "' OR 2=2"

        class FakeValidator:
            def validate(self, _template, _mutated) -> SimpleNamespace:
                return SimpleNamespace(is_valid=True, reason="")

            def clean(self, mutated: str) -> str:
                return mutated

        original = source_template(1)
        memory = MutationMemory(source_templates=[original])
        mutator = PayloadMutator(llm=FakeLlm(), model="test-model", memory=memory, infer_types=False)
        with patch("cosqli.synthesis.payload_mutation.payload_mutator.PayloadValidator", return_value=FakeValidator()):
            result = mutator.mutate(original)

        self.assertIsNotNone(result)
        self.assertEqual(result["template"]["payload"], "' OR 2=2")
        self.assertEqual(result["technique"], TECHNIQUE)
        self.assertTrue(REQUIRED_TEMPLATE_FIELDS <= set(result["template"]))
        stored = memory.get_category(TECHNIQUE, REFERENCE_SCOPE).mutated_templates
        self.assertEqual(stored, [result["template"]])


if __name__ == "__main__":
    unittest.main()
