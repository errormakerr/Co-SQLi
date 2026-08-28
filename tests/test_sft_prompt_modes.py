"""Regression coverage for model-visible schema and query-only prompts."""

from __future__ import annotations

import unittest

from cosqli.prompting import PromptMode
from cosqli.synthesis.sft_formatter import batch_process_to_sft, create_sft_format


SCHEMA = {
    "sample_db": {
        "database_name": "sample_db",
        "tables": [
            {
                "table_name": "users",
                "columns": [{"column_name": "id", "data_type": "int"}],
            }
        ],
    }
}


class SftPromptModeTests(unittest.TestCase):
    def test_query_only_prompt_contains_only_the_sql_query(self) -> None:
        record = create_sft_format(
            {"sql": "SELECT * FROM users WHERE id = 7", "label": True},
            schemas=None,
            prompt_mode=PromptMode.QUERY_ONLY,
        )
        self.assertEqual(
            record["messages"][1]["content"],
            "SQL Query:\nSELECT * FROM users WHERE id = 7",
        )
        self.assertEqual(record["prompt_mode"], "query_only")
        self.assertNotIn("Schema", record["messages"][1]["content"])

    def test_schema_aware_prompt_contains_resolved_ddl(self) -> None:
        record = create_sft_format(
            {"sql": "SELECT * FROM users", "db": "sample_db", "label": True},
            schemas=SCHEMA,
            prompt_mode=PromptMode.SCHEMA_AWARE,
        )
        user_prompt = record["messages"][1]["content"]
        self.assertIn("Database Schema:", user_prompt)
        self.assertIn("CREATE TABLE `users`", user_prompt)
        self.assertEqual(record["prompt_mode"], "schema_aware")

    def test_schema_aware_prompt_rejects_missing_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "no schema"):
            create_sft_format(
                {"sql": "SELECT 1", "db": "missing", "label": True},
                schemas=SCHEMA,
                prompt_mode=PromptMode.SCHEMA_AWARE,
            )

    def test_query_only_batch_never_drops_records_without_database_metadata(self) -> None:
        records = batch_process_to_sft(
            [
                {"sql": "SELECT 1", "label": True},
                {"sql": "SELECT 2", "label": True, "db": "missing"},
            ],
            schemas=None,
            prompt_mode=PromptMode.QUERY_ONLY,
        )
        self.assertEqual([record["sql"] for record in records], ["SELECT 1", "SELECT 2"])


if __name__ == "__main__":
    unittest.main()
