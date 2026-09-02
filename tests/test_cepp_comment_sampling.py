"""Tests for CEPP comment strategy allocation."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from cosqli.synthesis import injection_pipeline


LOCAL_COMMENTS = [
    {"type": "Irrelevant text dilution", "comment": "irrelevant library text"},
    {"type": "Authoritative statement", "comment": "authority one"},
    {"type": "Authoritative statement", "comment": "authority two"},
]


class CeppCommentSamplingTests(unittest.TestCase):
    def test_local_sampling_uses_combined_library_pool(self) -> None:
        with patch.object(
            injection_pipeline.random,
            "choice",
            side_effect=lambda candidates: candidates[-1],
        ) as choose:
            comment = injection_pipeline.generate_comment(
                "tautology",
                "' OR 1=1",
                "' OR 1=1",
                LOCAL_COMMENTS,
                allow_llm=False,
                use_rational=False,
            )

        self.assertEqual(comment, "authority two")
        self.assertEqual(
            choose.call_args.args[0],
            ["irrelevant library text", "authority one", "authority two"],
        )

    def test_rational_explanation_uses_the_twenty_percent_branch(self) -> None:
        llm = Mock()
        llm.generate.return_value = "The predicate is a compatibility check."
        with patch.object(injection_pipeline.random, "random", return_value=0.19), patch.object(
            injection_pipeline, "_get_gpt_config", return_value={"model": "test-model"}
        ), patch.object(injection_pipeline, "_get_gpt", return_value=llm):
            comment = injection_pipeline.generate_comment(
                "tautology",
                "' OR 1=1",
                "' OR 1=1",
                LOCAL_COMMENTS,
                allow_llm=True,
                llm_timeout_seconds=12.5,
            )

        self.assertEqual(comment, "The predicate is a compatibility check.")
        llm.generate.assert_called_once()
        self.assertEqual(llm.generate.call_args.kwargs["timeout_seconds"], 12.5)
        self.assertEqual(llm.generate.call_args.kwargs["max_tokens"], 96)
        self.assertEqual(llm.generate.call_args.kwargs["max_retries"], 0)

    def test_local_branch_is_used_at_the_twenty_percent_boundary(self) -> None:
        with patch.object(injection_pipeline.random, "random", return_value=0.20), patch.object(
            injection_pipeline.random, "choice", return_value="authority one"
        ), patch.object(injection_pipeline, "_get_gpt") as get_gpt:
            comment = injection_pipeline.generate_comment(
                "tautology", "' OR 1=1", "' OR 1=1", LOCAL_COMMENTS, allow_llm=True
            )

        self.assertEqual(comment, "authority one")
        get_gpt.assert_not_called()

    def test_rational_failure_records_a_distinct_fallback_strategy(self) -> None:
        with patch.object(injection_pipeline.random, "random", return_value=0.19), patch.object(
            injection_pipeline.random, "choice", return_value="authority one"
        ), patch.object(
            injection_pipeline, "_get_gpt_config", side_effect=FileNotFoundError("missing")
        ):
            comment, strategy = injection_pipeline._generate_comment_with_strategy(
                "tautology", "' OR 1=1", "' OR 1=1", LOCAL_COMMENTS, allow_llm=True
            )

        self.assertEqual(comment, "Validate the requested condition for the current query.")
        self.assertEqual(
            strategy,
            "rational_fallback_exception_FileNotFoundError",
        )

    def test_disabled_llm_retains_the_rational_cepp_class(self) -> None:
        comment, strategy = injection_pipeline._generate_comment_with_strategy(
            "union_query",
            "' UNION SELECT remaining FROM budget",
            "' UNION SELECT remaining FROM budget",
            LOCAL_COMMENTS,
            allow_llm=False,
            use_rational=True,
        )
        self.assertEqual(comment, "Validate the requested budget operation for the current query.")
        self.assertEqual(strategy, "rational_template_explanation")

    def test_benign_comment_uses_a_dedicated_query_prompt(self) -> None:
        llm = Mock()
        llm.generate.return_value = "Retrieve matching employee records."
        prompt_template = Mock()
        prompt_template.render.return_value = "benign prompt"
        with patch.object(
            injection_pipeline, "_get_gpt_config", return_value={"model": "test-model"}
        ), patch.object(injection_pipeline, "_get_gpt", return_value=llm), patch.object(
            injection_pipeline, "load_prompt_template", return_value=prompt_template
        ) as load_template:
            comment, strategy = injection_pipeline.generate_benign_comment(
                "SELECT name FROM employees WHERE department_id = 4",
                "company",
                llm_timeout_seconds=9.0,
            )

        self.assertEqual(comment, "Retrieve matching employee records.")
        self.assertEqual(strategy, "benign_rational_explanation")
        load_template.assert_called_once_with(
            str(injection_pipeline.PROJECT_ROOT / "prompts"),
            "benign_comment_generation.j2",
        )
        prompt_template.render.assert_called_once_with(
            sql="SELECT name FROM employees WHERE department_id = 4",
            database="company",
        )
        self.assertEqual(llm.generate.call_args.kwargs["max_tokens"], 48)
        self.assertEqual(llm.generate.call_args.kwargs["timeout_seconds"], 9.0)
        self.assertEqual(llm.generate.call_args.kwargs["max_retries"], 0)

    def test_benign_comment_falls_back_to_query_specific_text(self) -> None:
        comment, strategy = injection_pipeline.generate_benign_comment(
            "SELECT COUNT(*) FROM orders WHERE status = 'pending'",
            "sales",
            allow_llm=False,
        )

        self.assertEqual(comment, "Count matching records in the orders table.")
        self.assertEqual(strategy, "benign_template_explanation")

    def test_benign_comment_rejects_unsafe_llm_text(self) -> None:
        llm = Mock()
        llm.generate.return_value = "This query is safe -- use it."
        with patch.object(
            injection_pipeline, "_get_gpt_config", return_value={"model": "test-model"}
        ), patch.object(injection_pipeline, "_get_gpt", return_value=llm):
            comment, strategy = injection_pipeline.generate_benign_comment(
                "SELECT id FROM orders", "sales"
            )

        self.assertEqual(comment, "Retrieve the requested records from the orders table.")
        self.assertEqual(strategy, "benign_rational_fallback_invalid_response")


if __name__ == "__main__":
    unittest.main()
