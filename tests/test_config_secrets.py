"""Secret-source regression tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosqli.paths import (
    require_secret,
    resolve_runtime_artifacts_root,
    resolve_runtime_base_model_path,
)
from cosqli.synthesis import injection_pipeline


class SecretConfigurationTests(unittest.TestCase):
    def test_environment_secret_is_the_default(self) -> None:
        with patch.dict(os.environ, {"TEST_SQL_PASSWORD": "from-env"}, clear=True):
            self.assertEqual(
                require_secret({"password_env": "TEST_SQL_PASSWORD"}, "password"),
                "from-env",
            )

    def test_inline_secret_requires_explicit_opt_in(self) -> None:
        config = {"api_key": "inline-value"}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "COSQLI_ALLOW_INLINE_SECRETS"):
                require_secret(config, "api_key")
        with patch.dict(os.environ, {"COSQLI_ALLOW_INLINE_SECRETS": "1"}, clear=True):
            self.assertEqual(require_secret(config, "api_key"), "inline-value")

    def test_runtime_paths_are_provided_by_environment_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = {
                "base_model_path_env": "TEST_MODEL_DIR",
                "artifacts_root_env": "TEST_ARTIFACTS_DIR",
            }
            with patch.dict(
                os.environ,
                {
                    "TEST_MODEL_DIR": temporary_directory,
                    "TEST_ARTIFACTS_DIR": temporary_directory,
                },
                clear=True,
            ):
                self.assertEqual(resolve_runtime_base_model_path(config), Path(temporary_directory))
                self.assertEqual(resolve_runtime_artifacts_root(config), Path(temporary_directory))

    def test_runtime_paths_fall_back_to_standard_environment_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {
                    "COSQLI_BASE_MODEL_PATH": temporary_directory,
                    "COSQLI_ARTIFACTS_ROOT": temporary_directory,
                },
                clear=True,
            ):
                self.assertEqual(resolve_runtime_base_model_path({}), Path(temporary_directory))
                self.assertEqual(resolve_runtime_artifacts_root({}), Path(temporary_directory))

    def test_mysql_port_can_be_overridden_for_an_isolated_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "database_connection.yaml"
            config_path.write_text(
                "host: 127.0.0.1\nport: 13306\nuser: test\npassword_env: TEST_DB_PASSWORD\n",
                encoding="utf-8",
            )
            with patch.object(injection_pipeline, "_MYSQL_CONFIG_CACHE", None), patch.dict(
                os.environ,
                {"TEST_DB_PASSWORD": "test", "COSQLI_MYSQL_PORT": "24567"},
                clear=True,
            ):
                config = injection_pipeline.get_mysql_config(config_path)
            self.assertEqual(config["port"], 24567)
