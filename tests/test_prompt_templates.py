"""Regression tests for taxonomy-aware mutation and CEPP prompts."""

from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from synthesis.payload_mutation.memory import MutationMemory
from synthesis.payload_mutation.prompt_templates import (
    ATTACK_FORM_MUTATION_TEMPLATE,
    SECURITY_DECLARATION,
    SQL_STRUCTURE_MUTATION_TEMPLATE,
    get_type_dimensions,
)
from synthesis.payload_mutation.type_identifier import Technique


SOURCE_TEMPLATE = {
    "technique": "tautology",
    "reference_scope": "lor",
    "payload": "' OR 1=1",
    "expected_types": None,
    "set": "train",
}


class PromptTemplateTests(unittest.TestCase):
    def test_mutation_prompts_explain_scope_and_anti_imitation_examples(self) -> None:
        memory_addons = MutationMemory([SOURCE_TEMPLATE]).get_prompt_addons(
            "tautology", "lor"
        )
        for template in (ATTACK_FORM_MUTATION_TEMPLATE, SQL_STRUCTURE_MUTATION_TEMPLATE):
            prompt = template.format(
                security_declaration=SECURITY_DECLARATION,
                technique="tautology",
                reference_scope="lor",
                payload=SOURCE_TEMPLATE["payload"],
                dimensions="guidance",
                memory_addons=memory_addons,
            )
            self.assertIn("`lor`: literal-only", prompt)
            self.assertIn("`tsr`: target-schema reference", prompt)
            self.assertIn("`scr`: system-catalog reference", prompt)
            self.assertIn("Anti-Imitation Few-Shot Context", prompt)
            self.assertIn("negative examples", prompt)
            self.assertIn("Previously Explored Payload Cores", prompt)

    def test_technique_guidance_examples_are_comment_free_cores(self) -> None:
        for technique in Technique:
            if technique is Technique.UNKNOWN:
                continue
            self.assertNotIn("--", get_type_dimensions(technique))

    def test_cepp_prompt_has_canonical_few_shot_examples(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        prompt = Environment(
            loader=FileSystemLoader(project_root / "prompt_templates")
        ).get_template("generate_comment.j2").render(
            technique="tautology",
            payload_template="' OR ($sysInfo$) IS NOT NULL",
            payload="' OR (@@sql_mode) IS NOT NULL",
        )
        self.assertEqual(prompt.count("Explanation:"), 4)
        self.assertIn("Attack technique: tautology", prompt)
        self.assertIn("Do not repeat", prompt)


if __name__ == "__main__":
    unittest.main()
