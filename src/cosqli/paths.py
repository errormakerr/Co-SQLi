"""Project, configuration, and external-artifact path helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
"""Repository root when Co-SQLi is run from a source checkout."""

DEFAULT_ARTIFACTS_ROOT = Path("/hpc2hdd/home/hpan285/experiment_results")
"""The user-approved external root for generated experiment artifacts."""


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
    resolved = require_external_path(path, purpose="artifacts_root")
    if resolved != DEFAULT_ARTIFACTS_ROOT:
        raise ValueError(
            "artifacts_root must be "
            f"{DEFAULT_ARTIFACTS_ROOT}; configure another location through the CLI, not YAML."
        )
    return resolved


def validate_run_id(run_id: str) -> str:
    """Ensure a run identifier cannot escape the artifact root."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError(
            "run_id may contain only letters, digits, dots, underscores, and hyphens"
        )
    return run_id


def require_secret(config: dict, key: str) -> str:
    """Read a secret from an environment variable named by configuration."""
    environment_key = config.get(f"{key}_env")
    if not isinstance(environment_key, str) or not environment_key:
        raise ValueError(
            f"Configuration must provide {key}_env; inline {key} values are not supported."
        )
    value = os.environ.get(environment_key)
    if not value:
        raise EnvironmentError(f"Set {environment_key} before running Co-SQLi.")
    return value
