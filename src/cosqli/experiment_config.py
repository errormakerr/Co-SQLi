"""Current experiment settings and their validated YAML representation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict

from cosqli.paths import PROJECT_ROOT
from cosqli.prompting import PromptMode, parse_prompt_mode
from cosqli.utils.yaml_operation import load_yaml_to_dict


@dataclass(frozen=True)
class ExperimentConfig:
    """All parameters that define an adversarial training run."""

    schema_version: int
    random_seed: int
    prompt_mode: PromptMode
    num_rounds: int
    num_training_sqls: int
    initial_benign_ratio: float
    mix_benign_sources: bool
    attacker_gamma_start: float
    attacker_gamma_end: float
    attacker_strategy: str
    attacker_clusters_per_round: int
    attacker_weight_exponent: float
    verifier_update: str
    verifier_learning_rate: float
    verifier_reward_smoothing_alpha: float
    verifier_reward_smoothing_beta: float
    verifier_benign_fpr_target: float
    verifier_benign_ratio_step_size: float
    verifier_benign_error_ema_decay: float
    verifier_benign_ratio_min: float
    verifier_benign_ratio_max: float
    payload_mutation_enabled: bool
    payload_mutation_probability_start: float
    payload_mutation_probability_end: float
    payload_mutation_weight_scale_min: float
    payload_mutation_effective_probability_max: float
    payload_mutation_llm_temperature: float
    payload_mutation_llm_max_tokens: int
    payload_mutation_info_focused_probability: float
    payload_mutation_infer_expected_types: bool
    payload_mutation_types_inference_temperature: float
    payload_mutation_types_inference_max_tokens: int
    payload_mutation_fewshot_examples: int
    payload_mutation_model: str | None
    synthesis_cepp_rational_explanation_probability: float
    synthesis_cepp_llm_max_tokens: int
    synthesis_cepp_llm_max_retries: int

    def as_dict(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the resolved run settings."""
        return asdict(self)

    def with_cli_overrides(
        self,
        *,
        num_rounds: int | None,
        num_training_sqls: int | None,
        prompt_mode: PromptMode | str | None = None,
        random_seed: int | None = None,
    ) -> "ExperimentConfig":
        """Apply supported execution overrides to one complete configuration."""
        updates: Dict[str, Any] = {}
        if num_rounds is not None:
            updates["num_rounds"] = num_rounds
        if num_training_sqls is not None:
            updates["num_training_sqls"] = num_training_sqls
        if prompt_mode is not None:
            resolved_prompt_mode = parse_prompt_mode(prompt_mode)
            updates["prompt_mode"] = resolved_prompt_mode
            if resolved_prompt_mode is PromptMode.SCHEMA_AWARE:
                # External benign pools contain SQL text without database
                # metadata and are therefore unavailable to schema-aware SFT.
                updates["mix_benign_sources"] = False
        if random_seed is not None:
            updates["random_seed"] = random_seed
        return replace(self, **updates)


DEFAULT_EXPERIMENT_CONFIG_PATH = PROJECT_ROOT / "config" / "experiment_config.yaml"


def experiment_config_sha256(path: Path) -> str:
    """Return the SHA-256 fingerprint for a source experiment YAML file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolved_experiment_config_sha256(config: ExperimentConfig) -> str:
    """Return a stable fingerprint of the complete effective experiment config."""
    serialized = json.dumps(
        config.as_dict(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _mapping(value: Any, key: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"experiment config field {key!r} must be a mapping")
    return value


def _bool_field(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"experiment config field {key!r} must be a boolean")
    return value


def load_experiment_config(path: str | Path | None = None) -> ExperimentConfig:
    """Load and validate a complete current experiment configuration."""
    config_path = Path(path or DEFAULT_EXPERIMENT_CONFIG_PATH).expanduser().resolve()
    raw = load_yaml_to_dict(str(config_path))
    attacker = _mapping(raw.get("attacker"), "attacker")
    verifier = _mapping(raw.get("verifier"), "verifier")
    mutation = _mapping(raw.get("payload_mutation"), "payload_mutation")
    mix_benign_sources = _bool_field(
        raw.get("mix_benign_sources", False), "mix_benign_sources"
    )
    prompt_mode = parse_prompt_mode(raw["prompt_mode"])
    if prompt_mode is PromptMode.SCHEMA_AWARE:
        # Schema-aware examples require a database/schema pair. The external
        # benign pools are query-only records, so resolve this mode's default
        # to local train benign SQL even if the shared YAML defaults to true.
        mix_benign_sources = False
    try:
        schema_version = int(raw["schema_version"])
        if schema_version == 3:
            synthesis = _mapping(raw.get("synthesis"), "synthesis")
            cepp = _mapping(synthesis.get("cepp"), "synthesis.cepp")
        else:
            # Version 2 configurations predate the explicit CEPP settings.
            cepp = {}
        config = ExperimentConfig(
            schema_version=schema_version,
            random_seed=int(raw["random_seed"]),
            prompt_mode=prompt_mode,
            num_rounds=int(raw["num_rounds"]),
            num_training_sqls=int(raw["num_training_sqls"]),
            initial_benign_ratio=float(raw["initial_benign_ratio"]),
            mix_benign_sources=mix_benign_sources,
            attacker_gamma_start=float(attacker["gamma_start"]),
            attacker_gamma_end=float(attacker["gamma_end"]),
            attacker_strategy=str(attacker["strategy"]),
            attacker_clusters_per_round=int(attacker["clusters_per_round"]),
            attacker_weight_exponent=float(attacker["weight_exponent"]),
            verifier_update=str(verifier["update"]),
            verifier_learning_rate=float(verifier["learning_rate"]),
            verifier_reward_smoothing_alpha=float(
                verifier["reward_smoothing_alpha"]
                if schema_version == 3
                else verifier.get("reward_smoothing_alpha", 1.0)
            ),
            verifier_reward_smoothing_beta=float(
                verifier["reward_smoothing_beta"]
                if schema_version == 3
                else verifier.get("reward_smoothing_beta", 1.0)
            ),
            verifier_benign_fpr_target=float(
                verifier["benign_fpr_target"]
                if schema_version == 3
                else verifier.get("benign_fpr_target", 0.05)
            ),
            verifier_benign_ratio_step_size=float(
                verifier["benign_ratio_step_size"]
                if schema_version == 3
                else verifier.get("benign_ratio_step_size", 0.5)
            ),
            verifier_benign_error_ema_decay=float(
                verifier["benign_error_ema_decay"]
                if schema_version == 3
                else verifier.get("benign_error_ema_decay", 0.7)
            ),
            verifier_benign_ratio_min=float(
                verifier["benign_ratio_min"]
                if schema_version == 3
                else verifier.get("benign_ratio_min", 0.15)
            ),
            verifier_benign_ratio_max=float(
                verifier["benign_ratio_max"]
                if schema_version == 3
                else verifier.get("benign_ratio_max", 0.35)
            ),
            payload_mutation_enabled=_bool_field(
                mutation["enabled"], "payload_mutation.enabled"
            ),
            payload_mutation_probability_start=float(mutation["probability_start"]),
            payload_mutation_probability_end=float(mutation["probability_end"]),
            payload_mutation_weight_scale_min=float(
                mutation["weight_scale_min"]
                if schema_version == 3
                else mutation.get("weight_scale_min", 0.5)
            ),
            payload_mutation_effective_probability_max=float(
                mutation["effective_probability_max"]
                if schema_version == 3
                else mutation.get("effective_probability_max", 0.8)
            ),
            payload_mutation_llm_temperature=float(
                mutation["llm_temperature"]
                if schema_version == 3
                else mutation.get("llm_temperature", 0.7)
            ),
            payload_mutation_llm_max_tokens=int(
                mutation["llm_max_tokens"]
                if schema_version == 3
                else mutation.get("llm_max_tokens", 2000)
            ),
            payload_mutation_info_focused_probability=float(
                mutation["info_focused_probability"]
                if schema_version == 3
                else mutation.get("info_focused_probability", 0.3)
            ),
            payload_mutation_infer_expected_types=_bool_field(
                mutation["infer_expected_types"]
                if schema_version == 3
                else mutation.get("infer_expected_types", True),
                "payload_mutation.infer_expected_types",
            ),
            payload_mutation_types_inference_temperature=float(
                mutation["types_inference_temperature"]
                if schema_version == 3
                else mutation.get("types_inference_temperature", 0.3)
            ),
            payload_mutation_types_inference_max_tokens=int(
                mutation["types_inference_max_tokens"]
                if schema_version == 3
                else mutation.get("types_inference_max_tokens", 500)
            ),
            payload_mutation_fewshot_examples=int(
                mutation["fewshot_examples"]
                if schema_version == 3
                else mutation.get("fewshot_examples", 5)
            ),
            payload_mutation_model=mutation["model"],
            synthesis_cepp_rational_explanation_probability=float(
                cepp["rational_explanation_probability"]
                if schema_version == 3
                else 0.20
            ),
            synthesis_cepp_llm_max_tokens=int(
                cepp["llm_max_tokens"] if schema_version == 3 else 96
            ),
            synthesis_cepp_llm_max_retries=int(
                cepp["llm_max_retries"] if schema_version == 3 else 0
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid experiment config: {config_path}: {error}") from error

    if config.schema_version not in {2, 3}:
        raise ValueError(f"Unsupported experiment config schema: {config.schema_version}")
    if config.num_rounds <= 0 or config.num_training_sqls <= 0:
        raise ValueError("num_rounds and num_training_sqls must be positive")
    if not 0.0 <= config.initial_benign_ratio <= 1.0:
        raise ValueError("initial_benign_ratio must be in [0, 1]")
    if (
        config.mix_benign_sources
        and config.prompt_mode is not PromptMode.QUERY_ONLY
    ):
        raise ValueError("mix_benign_sources is only supported for query_only prompts")
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
    for name, value in (
        ("verifier reward_smoothing_alpha", config.verifier_reward_smoothing_alpha),
        ("verifier reward_smoothing_beta", config.verifier_reward_smoothing_beta),
        ("verifier benign_ratio_step_size", config.verifier_benign_ratio_step_size),
    ):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and positive")
    if not 0.0 <= config.verifier_benign_fpr_target <= 1.0:
        raise ValueError("verifier benign_fpr_target must be in [0, 1]")
    if not 0.0 <= config.verifier_benign_error_ema_decay <= 1.0:
        raise ValueError("verifier benign_error_ema_decay must be in [0, 1]")
    if not (
        0.0
        <= config.verifier_benign_ratio_min
        <= config.verifier_benign_ratio_max
        <= 1.0
    ):
        raise ValueError(
            "verifier benign ratio bounds must satisfy 0 <= min <= max <= 1"
        )
    if not (
        config.verifier_benign_ratio_min
        <= config.initial_benign_ratio
        <= config.verifier_benign_ratio_max
    ):
        raise ValueError(
            "initial_benign_ratio must fall within the verifier benign ratio bounds"
        )
    if not 0.0 <= config.payload_mutation_probability_start <= 1.0:
        raise ValueError("payload mutation probability_start must be in [0, 1]")
    if not 0.0 <= config.payload_mutation_probability_end <= 1.0:
        raise ValueError("payload mutation probability_end must be in [0, 1]")
    if (
        not math.isfinite(config.payload_mutation_weight_scale_min)
        or config.payload_mutation_weight_scale_min < 0.0
    ):
        raise ValueError(
            "payload mutation weight_scale_min must be finite and non-negative"
        )
    if not 0.0 <= config.payload_mutation_effective_probability_max <= 1.0:
        raise ValueError("payload mutation effective_probability_max must be in [0, 1]")
    if (
        not math.isfinite(config.payload_mutation_llm_temperature)
        or config.payload_mutation_llm_temperature < 0.0
    ):
        raise ValueError(
            "payload mutation llm_temperature must be finite and non-negative"
        )
    if config.payload_mutation_llm_max_tokens <= 0:
        raise ValueError("payload mutation llm_max_tokens must be positive")
    if not 0.0 <= config.payload_mutation_info_focused_probability <= 1.0:
        raise ValueError("payload mutation info_focused_probability must be in [0, 1]")
    if (
        not math.isfinite(config.payload_mutation_types_inference_temperature)
        or config.payload_mutation_types_inference_temperature < 0.0
    ):
        raise ValueError(
            "payload mutation types_inference_temperature must be finite and non-negative"
        )
    if config.payload_mutation_types_inference_max_tokens <= 0:
        raise ValueError("payload mutation types_inference_max_tokens must be positive")
    if config.payload_mutation_fewshot_examples < 0:
        raise ValueError("payload mutation fewshot_examples must be non-negative")
    if config.payload_mutation_model is not None and not isinstance(
        config.payload_mutation_model, str
    ):
        raise ValueError("payload mutation model must be a string or null")
    if not 0.0 <= config.synthesis_cepp_rational_explanation_probability <= 1.0:
        raise ValueError(
            "synthesis CEPP rational_explanation_probability must be in [0, 1]"
        )
    if config.synthesis_cepp_llm_max_tokens <= 0:
        raise ValueError("synthesis CEPP llm_max_tokens must be positive")
    if config.synthesis_cepp_llm_max_retries < 0:
        raise ValueError("synthesis CEPP llm_max_retries must be non-negative")
    return config
