"""Regression coverage for structured live-value fallback provenance."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pymysql

from cosqli.synthesis.template_fillers.specific_db_filler import (
    SpecificDatabaseTemplateFiller,
)


class TemplateFillerAuditTests(unittest.TestCase):
    def test_table_read_failure_is_retained_as_structured_warning(self) -> None:
        filler = SpecificDatabaseTemplateFiller(
            {
                "database_name": "mysql",
                "tables": [
                    {
                        "table_name": "user",
                        "columns": [{"column_name": "User", "data_type": "varchar"}],
                    }
                ],
            },
            {"host": "localhost", "port": 3306, "user": "test", "password": "test"},
        )
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = pymysql.err.OperationalError(1142, "denied")

        with patch.object(filler, "_get_mysql_connection", return_value=connection):
            samples = filler._get_table_samples("user", ["User"])

        self.assertEqual(samples, {"User": "NULL"})
        self.assertEqual(
            filler.synthesis_warnings,
            [
                {
                    "kind": "table_sample_read_failed",
                    "database": "mysql",
                    "table": "user",
                    "error_type": "OperationalError",
                    "mysql_error_code": 1142,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
