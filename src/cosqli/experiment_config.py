"""Current experiment settings and their validated YAML representation."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict

from cosqli.paths import PROJECT_ROOT
from cosqli.utils.yaml_operation import load_yaml_to_dict


@dataclass(frozen=True)
class ExperimentConfig:
    """All parameters that define an adversarial training run."""

    schema_version: int
    random_seed: int
    num_rounds: int
    num_training_sqls: int
    initial_benign_ratio: float
    attacker_gamma_start: float
    attacker_gamma_end: float
    attacker_strategy: str
    attacker_clusters_per_round: int
    attacker_weight_exponent: float
    verifier_update: str
    verifier_learning_rate: float
    payload_mutation_enabled: bool
    payload_mutation_probability_start: float
    payload_mutation_probability_end: float
    payload_mutation_model: str | None

    def as_dict(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the resolved run settings."""
        return asdict(self)

    def with_cli_overrides(
        self,
        *,
        num_rounds: int | None,
        num_training_sqls: int | None,
    ) -> "ExperimentConfig":
        """Apply the two supported execution-size overrides."""
        updates: Dict[str, int] = {}
        if num_rounds is not None:
            updates["num_rounds"] = num_rounds
        if num_training_sqls is not None:
            updates["num_training_sqls"] = num_training_sqls
        return replace(self, **updates)


DEFAULT_EXPERIMENT_CONFIG_PATH = PROJECT_ROOT / "config" / "experiment_config.yaml"


def experiment_config_sha256(path: Path) -> str:
    """Return the SHA-256 fingerprint for a versioned experiment config."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: Any, key: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"experiment config field {key!r} must be a mapping")
    return value


def load_experiment_config(path: str | Path | None = None) -> ExperimentConfig:
    """Load and validate a complete current experiment configuration."""
    config_path = Path(path or DEFAULT_EXPERIMENT_CONFIG_PATH).expanduser().resolve()
    raw = load_yaml_to_dict(str(config_path))
    attacker = _mapping(raw.get("attacker"), "attacker")
    verifier = _mapping(raw.get("verifier"), "verifier")
    mutation = _mapping(raw.get("payload_mutation"), "payload_mutation")
    try:
        config = ExperimentConfig(
            schema_version=int(raw["schema_version"]),
            random_seed=int(raw["random_seed"]),
            num_rounds=int(raw["num_rounds"]),
            num_training_sqls=int(raw["num_training_sqls"]),
            initial_benign_ratio=float(raw["initial_benign_ratio"]),
            attacker_gamma_start=float(attacker["gamma_start"]),
            attacker_gamma_end=float(attacker["gamma_end"]),
            attacker_strategy=str(attacker["strategy"]),
            attacker_clusters_per_round=int(attacker["clusters_per_round"]),
            attacker_weight_exponent=float(attacker["weight_exponent"]),
            verifier_update=str(verifier["update"]),
            verifier_learning_rate=float(verifier["learning_rate"]),
            payload_mutation_enabled=bool(mutation["enabled"]),
            payload_mutation_probability_start=float(mutation["probability_start"]),
            payload_mutation_probability_end=float(mutation["probability_end"]),
            payload_mutation_model=mutation["model"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid experiment config: {config_path}") from error

    if config.schema_version != 1:
        raise ValueError(f"Unsupported experiment config schema: {config.schema_version}")
    if config.num_rounds <= 0 or config.num_training_sqls <= 0:
        raise ValueError("num_rounds and num_training_sqls must be positive")
    if not 0.0 <= config.initial_benign_ratio <= 1.0:
        raise ValueError("initial_benign_ratio must be in [0, 1]")
    if not 0.0 < config.attacker_gamma_end <= config.attacker_gamma_start <= 1.0:
        raise ValueError("attacker gamma values must satisfy 0 < end <= start <= 1")
    if config.attacker_strategy not in {"by_probability", "top_k"}:
        raise ValueError("attacker strategy must be by_probability or top_k")
    if config.attacker_clusters_per_round <= 0:
        raise ValueError("attacker clusters_per_round must be positive")
    if config.attacker_weight_exponent <= 0.0:
        raise ValueError("attacker weight_exponent must be positive")
    if config.verifier_update != "centered_full_information_exponential":
        raise ValueError("verifier update must be centered_full_information_exponential")
    if config.verifier_learning_rate <= 0.0:
        raise ValueError("verifier learning_rate must be positive")
    if not 0.0 <= config.payload_mutation_probability_start <= 1.0:
        raise ValueError("payload mutation probability_start must be in [0, 1]")
    if not 0.0 <= config.payload_mutation_probability_end <= 1.0:
        raise ValueError("payload mutation probability_end must be in [0, 1]")
    if config.payload_mutation_model is not None and not isinstance(
        config.payload_mutation_model, str
    ):
        raise ValueError("payload mutation model must be a string or null")
    return config
