"""Project, configuration, and external-artifact path helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
"""Repository root when Co-SQLi is run from a source checkout."""


def get_config_dir() -> Path:
    """Return the optional external config directory or the checked-in template directory."""
    configured_dir = os.environ.get("COSQLI_CONFIG_DIR")
    if configured_dir:
        return Path(configured_dir).expanduser().resolve()
    return PROJECT_ROOT / "config"


def get_config_path(filename: str) -> Path:
    """Resolve a named config file without embedding host-specific paths in code."""
    return get_config_dir() / filename


def require_external_path(path: Path | str, *, purpose: str) -> Path:
    """Resolve *path* and reject any project-local output destination."""
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        return resolved
    raise ValueError(
        f"{purpose} must be outside the Co-SQLi repository: {resolved}"
    )


def require_artifacts_root(path: Path | str) -> Path:
    """Validate the configured external artifact root."""
    return require_external_path(path, purpose="artifacts_root")


def resolve_runtime_base_model_path(runtime_config: dict) -> Path:
    """Resolve the base model from its declared environment variable."""
    environment_key = runtime_config.get("base_model_path_env")
    if isinstance(environment_key, str) and environment_key:
        value = os.environ.get(environment_key)
        if not value:
            raise EnvironmentError(
                f"Set {environment_key} to the local base-model directory before running Co-SQLi."
            )
        return Path(value).expanduser().resolve()

    value = os.environ.get("COSQLI_BASE_MODEL_PATH")
    if value:
        return Path(value).expanduser().resolve()

    raise ValueError(
        "runtime_config.yaml must provide a non-empty base_model_path_env or "
        "COSQLI_BASE_MODEL_PATH must be set."
    )


def resolve_runtime_artifacts_root(runtime_config: dict) -> Path:
    """Resolve the external artifact root from its declared environment variable."""
    environment_key = runtime_config.get("artifacts_root_env")
    if isinstance(environment_key, str) and environment_key:
        value = os.environ.get(environment_key)
        if not value:
            raise EnvironmentError(
                f"Set {environment_key} to an external artifact directory before running Co-SQLi."
            )
        return require_artifacts_root(value)

    value = os.environ.get("COSQLI_ARTIFACTS_ROOT")
    if value:
        return require_artifacts_root(value)

    raise ValueError(
        "runtime_config.yaml must provide a non-empty artifacts_root_env or "
        "COSQLI_ARTIFACTS_ROOT must be set."
    )


def validate_run_id(run_id: str) -> str:
    """Ensure a run identifier cannot escape the artifact root."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError(
            "run_id may contain only letters, digits, dots, underscores, and hyphens"
        )
    return run_id


def require_secret(config: dict, key: str) -> str:
    """Read a configured secret, requiring explicit opt-in for inline values."""
    environment_key = config.get(f"{key}_env")
    if isinstance(environment_key, str) and environment_key:
        value = os.environ.get(environment_key)
        if not value:
            raise EnvironmentError(f"Set {environment_key} before running Co-SQLi.")
        return value

    if os.environ.get("COSQLI_ALLOW_INLINE_SECRETS") == "1":
        value = config.get(key)
        if isinstance(value, str) and value:
            return value

    raise ValueError(
        f"Configuration must provide a non-empty {key}_env; set "
        "COSQLI_ALLOW_INLINE_SECRETS=1 to use an inline value from an external config."
    )
