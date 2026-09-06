"""Co-SQLi adversarial training loop (attack, defend, verify)."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from cosqli.attacker.attacker import Attacker
from cosqli.defender.defender import Defender
from cosqli.experiment_config import (
    DEFAULT_EXPERIMENT_CONFIG_PATH,
    ExperimentConfig,
    experiment_config_sha256,
    load_experiment_config,
    resolved_experiment_config_sha256,
)
from cosqli.paths import (
    PROJECT_ROOT,
    get_config_path,
    require_external_path,
    resolve_runtime_artifacts_root,
    resolve_runtime_base_model_path,
    validate_run_id,
)
from cosqli.prompting import (
    PROMPT_MODES,
    SFT_FILENAMES_BY_PROMPT_MODE,
    all_sft_filenames,
    sft_filename,
)
from cosqli.reporting import write_experiment_reports
from cosqli.telemetry import measure_stage, utc_timestamp
from cosqli.verifier.verifier import Verifier
from cosqli.utils.cluster import (
    TAXONOMY_VERSION,
    all_attack_cluster_keys,
    cluster_injection_sqls,
    get_single_key_of_injection_sql,
    get_injection_cluster_keys,
)
from cosqli.utils.json_operation import read_json_file, read_jsonl_file, write_jsonl_file, write_json_file
from cosqli.utils.logging_config import setup_logging
from cosqli.utils.yaml_operation import load_yaml_to_dict
import numpy as np


# ==================== Configuration Constants ====================

BENCHMARK_SOURCE_FILENAMES = (
    "payload_template.json",
    "sql_data_with_injection_point.json",
    "schema.json",
    "system_table_schema.json",
    "system_var.json",
    "comment_repository.json",
    "normal_sqls.json",
)
BENCHMARK_ARTIFACT_FILENAMES = {
    "train_sqls.json",
    "valid_sqls.json",
    "test_sqls.json",
} | all_sft_filenames()

_LEGACY_BENCHMARK_SCHEMA_VERSION = 2
_DERIVED_BENCHMARK_SCHEMA_VERSION = 3
_DERIVED_BENCHMARK_TYPE = "derived_train_subsample"
_DERIVED_SELECTION_FILENAME = "train_selection.json"
_DERIVED_SAMPLING_METHOD = "uniform_stratified_by_attack_cluster"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

@dataclass
class ProjectPaths:
    """Project directory paths configuration."""

    project_root: Path
    source_data_dir: Path
    benchmark_dir: Path
    run_dir: Path
    config_dir: Path
    base_model_path: Path

    @classmethod
    def create(
        cls,
        run_id: str | None = None,
        benchmark_dir: str | Path | None = None,
    ) -> "ProjectPaths":
        """Load runtime inputs and create an external, isolated run directory."""
        project_root = PROJECT_ROOT
        config_dir = project_root / "config"
        runtime_config_path = get_config_path("runtime_config.yaml")
        if not runtime_config_path.is_file():
            raise FileNotFoundError(
                "Missing runtime configuration: "
                f"{runtime_config_path}. Add it to the repository config directory "
                "or set COSQLI_CONFIG_DIR to an explicit override."
            )

        runtime_config = load_yaml_to_dict(str(runtime_config_path))
        if not isinstance(runtime_config, dict):
            raise ValueError(f"Runtime configuration must be a mapping: {runtime_config_path}")
        base_model_path = resolve_runtime_base_model_path(runtime_config)
        artifacts_root = resolve_runtime_artifacts_root(runtime_config)
        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
        run_dir = artifacts_root / validate_run_id(run_id)
        require_external_path(run_dir, purpose="run output")
        if not base_model_path.is_dir():
            raise FileNotFoundError(
                f"Configured base model directory does not exist: {base_model_path}"
            )
        if (
            base_model_path == run_dir
            or base_model_path in run_dir.parents
            or run_dir in base_model_path.parents
        ):
            raise ValueError(
                "run output must not be the base model directory or a directory within it."
            )

        configured_benchmark_dir = benchmark_dir or os.environ.get("COSQLI_BENCHMARK_DIR")
        if not configured_benchmark_dir:
            raise ValueError(
                "Provide an external benchmark directory with --benchmark-dir "
                "or COSQLI_BENCHMARK_DIR."
            )
        resolved_benchmark_dir = require_external_path(
            configured_benchmark_dir,
            purpose="benchmark directory",
        )
        if not resolved_benchmark_dir.is_dir():
            raise FileNotFoundError(
                f"Configured benchmark directory does not exist: {resolved_benchmark_dir}"
            )

        return cls(
            project_root=project_root,
            source_data_dir=project_root / "data" / "source",
            benchmark_dir=resolved_benchmark_dir,
            run_dir=run_dir,
            config_dir=config_dir,
            base_model_path=base_model_path,
        )


# ==================== Experiment Configuration ====================

ACTIVE_EXPERIMENT_CONFIG = load_experiment_config()
ACTIVE_EXPERIMENT_CONFIG_PATH = DEFAULT_EXPERIMENT_CONFIG_PATH
NUM_ROUNDS = ACTIVE_EXPERIMENT_CONFIG.num_rounds
NUM_TRAINING_SQLS = ACTIVE_EXPERIMENT_CONFIG.num_training_sqls
ATTACKER_GAMMA_START = ACTIVE_EXPERIMENT_CONFIG.attacker_gamma_start
ATTACKER_GAMMA_END = ACTIVE_EXPERIMENT_CONFIG.attacker_gamma_end
VERIFIER_LEARNING_RATE = ACTIVE_EXPERIMENT_CONFIG.verifier_learning_rate
ATTACKER_STRATEGY = ACTIVE_EXPERIMENT_CONFIG.attacker_strategy
ATTACKER_K = ACTIVE_EXPERIMENT_CONFIG.attacker_clusters_per_round
INITIAL_BENIGN_RATIO = ACTIVE_EXPERIMENT_CONFIG.initial_benign_ratio
ENABLE_PAYLOAD_MUTATION = ACTIVE_EXPERIMENT_CONFIG.payload_mutation_enabled
MODIFY_PAYLOAD_PROB_START = ACTIVE_EXPERIMENT_CONFIG.payload_mutation_probability_start
MODIFY_PAYLOAD_PROB_END = ACTIVE_EXPERIMENT_CONFIG.payload_mutation_probability_end
MUTATION_MODEL = ACTIVE_EXPERIMENT_CONFIG.payload_mutation_model
PROMPT_MODE = ACTIVE_EXPERIMENT_CONFIG.prompt_mode


def configure_experiment(
    config: ExperimentConfig,
    config_path: str | Path,
) -> None:
    """Activate one validated configuration and seed local random sources."""
    global ACTIVE_EXPERIMENT_CONFIG, ACTIVE_EXPERIMENT_CONFIG_PATH
    global NUM_ROUNDS, NUM_TRAINING_SQLS, ATTACKER_GAMMA_START, ATTACKER_GAMMA_END
    global VERIFIER_LEARNING_RATE, ATTACKER_STRATEGY, ATTACKER_K, INITIAL_BENIGN_RATIO
    global ENABLE_PAYLOAD_MUTATION, MODIFY_PAYLOAD_PROB_START, MODIFY_PAYLOAD_PROB_END
    global MUTATION_MODEL, PROMPT_MODE

    ACTIVE_EXPERIMENT_CONFIG = config
    ACTIVE_EXPERIMENT_CONFIG_PATH = Path(config_path).expanduser().resolve()
    NUM_ROUNDS = config.num_rounds
    NUM_TRAINING_SQLS = config.num_training_sqls
    ATTACKER_GAMMA_START = config.attacker_gamma_start
    ATTACKER_GAMMA_END = config.attacker_gamma_end
    VERIFIER_LEARNING_RATE = config.verifier_learning_rate
    ATTACKER_STRATEGY = config.attacker_strategy
    ATTACKER_K = config.attacker_clusters_per_round
    INITIAL_BENIGN_RATIO = config.initial_benign_ratio
    ENABLE_PAYLOAD_MUTATION = config.payload_mutation_enabled
    MODIFY_PAYLOAD_PROB_START = config.payload_mutation_probability_start
    MODIFY_PAYLOAD_PROB_END = config.payload_mutation_probability_end
    MUTATION_MODEL = config.payload_mutation_model
    PROMPT_MODE = config.prompt_mode
    random.seed(config.random_seed)
    np.random.seed(config.random_seed)


# ==================== Utility Functions ====================

def delete_folder_if_exists(folder_path: Path) -> None:
    """Delete an external run artifact if it exists; skip silently otherwise."""
    folder_path = require_external_path(folder_path, purpose="cleanup target")
    if not folder_path.exists():
        return

    if not folder_path.is_dir():
        print(f"Warning: '{folder_path}' is a file, not a directory — skipping delete")
        return

    try:
        shutil.rmtree(folder_path)
        print(f"Deleted directory: {folder_path}")
    except OSError as e:
        print(f"Failed to delete: {e.strerror}")
    except Exception as e:
        print(f"Unexpected error: {e}")


# ==================== Core Logic ====================

def _json_fingerprint(value: Any) -> str:
    """Return a stable content fingerprint for an in-memory JSON value."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require_sha256(value: Any, *, field: str, manifest_path: Path) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Invalid {field} checksum: {manifest_path}")
    return value


def _canonical_split_specs() -> Dict[str, Dict[str, Any]]:
    return {
        "train_sqls.json": {
            "source_split": "train",
            "attack_count": 2560,
            "benign_count": 653,
        },
        "valid_sqls.json": {
            "source_split": "train",
            "attack_count": 1920,
            "benign_count": 40,
        },
        "test_sqls.json": {
            "source_split": "test",
            "attack_count": 3200,
            "benign_count": 873,
        },
    }


def _validate_derived_train_spec(
    manifest: Mapping[str, Any],
    datasets: Mapping[str, Any],
    manifest_path: Path,
) -> None:
    """Validate schema-v3 provenance before accepting a sampled train split."""
    if manifest.get("benchmark_type") != _DERIVED_BENCHMARK_TYPE:
        raise ValueError(f"Invalid derived benchmark type: {manifest_path}")
    derivation = manifest.get("derivation")
    if not isinstance(derivation, dict):
        raise ValueError(f"Missing derived benchmark provenance: {manifest_path}")
    if derivation.get("method") != _DERIVED_SAMPLING_METHOD:
        raise ValueError(f"Unsupported derived benchmark sampling method: {manifest_path}")
    if derivation.get("content_generation") != "none":
        raise ValueError(f"Derived benchmark must not claim new content generation: {manifest_path}")
    if not isinstance(derivation.get("sampling_seed"), int) or isinstance(
        derivation.get("sampling_seed"), bool
    ):
        raise ValueError(f"Derived benchmark must declare an integer sampling seed: {manifest_path}")

    parent = derivation.get("parent")
    if not isinstance(parent, dict) or not isinstance(parent.get("directory_name"), str):
        raise ValueError(f"Invalid parent benchmark provenance: {manifest_path}")
    _require_sha256(
        parent.get("build_manifest_sha256"),
        field="parent build manifest",
        manifest_path=manifest_path,
    )
    _require_sha256(
        parent.get("train_sqls_sha256"),
        field="parent train SQL",
        manifest_path=manifest_path,
    )

    train_spec = datasets.get("train_sqls.json")
    target_train = derivation.get("target_train")
    if not isinstance(train_spec, dict) or not isinstance(target_train, dict):
        raise ValueError(f"Invalid derived train specification: {manifest_path}")
    if train_spec.get("source_split") != "train" or target_train != {
        "attack_count": train_spec.get("attack_count"),
        "benign_count": train_spec.get("benign_count"),
    }:
        raise ValueError(f"Derived train target does not match datasets: {manifest_path}")
    attack_count = train_spec.get("attack_count")
    benign_count = train_spec.get("benign_count")
    cluster_count = len(all_attack_cluster_keys())
    if (
        not isinstance(attack_count, int)
        or isinstance(attack_count, bool)
        or attack_count < cluster_count
        or attack_count % cluster_count != 0
        or not isinstance(benign_count, int)
        or isinstance(benign_count, bool)
        or benign_count < 0
    ):
        raise ValueError(
            "Derived train split must have a non-negative benign count and an equal, "
            f"non-zero attack quota for each of {cluster_count} clusters: {manifest_path}"
        )

    if derivation.get("selection_file") != _DERIVED_SELECTION_FILENAME:
        raise ValueError(f"Invalid derived selection filename: {manifest_path}")
    _require_sha256(
        derivation.get("selection_file_sha256"),
        field="derived selection",
        manifest_path=manifest_path,
    )


def _validate_derived_train_selection(
    benchmark_dir: Path,
    manifest: Mapping[str, Any],
) -> None:
    """Bind every derived train record to a declared parent-record fingerprint."""
    manifest_path = benchmark_dir / "build_manifest.json"
    derivation = manifest["derivation"]
    selection_path = benchmark_dir / _DERIVED_SELECTION_FILENAME
    if (
        not selection_path.is_file()
        or _sha256(selection_path) != derivation["selection_file_sha256"]
    ):
        raise ValueError(f"Derived selection checksum mismatch: {selection_path}")
    selection = read_json_file(str(selection_path))
    if not isinstance(selection, dict) or selection.get("schema_version") != 1:
        raise ValueError(f"Invalid derived selection manifest: {selection_path}")
    if (
        selection.get("method") != derivation["method"]
        or selection.get("sampling_seed") != derivation["sampling_seed"]
        or selection.get("parent") != derivation["parent"]
    ):
        raise ValueError(f"Derived selection provenance mismatch: {selection_path}")

    records = read_json_file(str(benchmark_dir / "train_sqls.json"))
    selected_records = selection.get("records")
    if not isinstance(records, list) or not isinstance(selected_records, list):
        raise ValueError(f"Invalid derived train records: {manifest_path}")
    train_spec = manifest["datasets"]["train_sqls.json"]
    if len(records) != len(selected_records) or len(records) != (
        train_spec["attack_count"] + train_spec["benign_count"]
    ):
        raise ValueError(f"Derived train selection count mismatch: {selection_path}")

    parent_indices = set()
    observed_attack_counts = {cluster: 0 for cluster in all_attack_cluster_keys()}
    observed_benign_count = 0
    for output_index, (record, selected) in enumerate(zip(records, selected_records)):
        if not isinstance(record, dict) or not isinstance(selected, dict):
            raise ValueError(f"Invalid derived selection record: {selection_path}")
        parent_index = selected.get("parent_index")
        label = record.get("label")
        if (
            selected.get("output_index") != output_index
            or not isinstance(parent_index, int)
            or isinstance(parent_index, bool)
            or parent_index < 0
            or parent_index in parent_indices
            or selected.get("record_sha256") != _json_fingerprint(record)
            or not isinstance(label, bool)
            or selected.get("label") != label
        ):
            raise ValueError(f"Derived selection record mismatch at index {output_index}")
        parent_indices.add(parent_index)
        cluster = get_single_key_of_injection_sql(record)
        if selected.get("cluster") != cluster:
            raise ValueError(f"Derived selection cluster mismatch at index {output_index}")
        if label:
            observed_benign_count += 1
        else:
            observed_attack_counts[cluster] = observed_attack_counts.get(cluster, 0) + 1

    expected_quota = train_spec["attack_count"] // len(observed_attack_counts)
    if (
        observed_benign_count != train_spec["benign_count"]
        or set(observed_attack_counts) != set(all_attack_cluster_keys())
        or any(count != expected_quota for count in observed_attack_counts.values())
    ):
        raise ValueError(f"Derived train stratification mismatch: {selection_path}")


def _validate_benchmark_contract(benchmark_dir: Path) -> None:
    """Require a canonical or provenance-bound derived external benchmark."""
    manifest_path = benchmark_dir / "build_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            "Benchmark directory is missing build_manifest.json. "
            "Build a fresh external benchmark with the Co-SQLi-Benchmark project."
        )
    manifest = read_json_file(str(manifest_path))
    if not isinstance(manifest, dict):
        raise ValueError(f"Benchmark manifest must be a JSON object: {manifest_path}")
    schema_version = manifest.get("schema_version")
    if schema_version not in {
        _LEGACY_BENCHMARK_SCHEMA_VERSION,
        _DERIVED_BENCHMARK_SCHEMA_VERSION,
    }:
        raise ValueError(f"Unsupported benchmark manifest schema: {manifest_path}")
    expected_prompt_modes = [mode.value for mode in PROMPT_MODES]
    if manifest.get("prompt_modes") != expected_prompt_modes:
        raise ValueError(f"Invalid benchmark prompt modes: {manifest_path}")
    expected_sft_files = {
        mode.value: dict(SFT_FILENAMES_BY_PROMPT_MODE[mode])
        for mode in PROMPT_MODES
    }
    if manifest.get("sft_files") != expected_sft_files:
        raise ValueError(f"Invalid benchmark SFT file mapping: {manifest_path}")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError(f"Invalid benchmark manifest datasets section: {manifest_path}")

    expected = _canonical_split_specs()
    if schema_version == _DERIVED_BENCHMARK_SCHEMA_VERSION:
        _validate_derived_train_spec(manifest, datasets, manifest_path)
        expected.pop("train_sqls.json")
    for filename, expected_spec in expected.items():
        observed = datasets.get(filename)
        if not isinstance(observed, dict) or any(
            observed.get(key) != value for key, value in expected_spec.items()
        ):
            raise ValueError(
                f"Benchmark contract mismatch for {filename}: "
                f"expected={expected_spec}, observed={observed}"
            )
    source_hashes = manifest.get("source_files_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(
        BENCHMARK_SOURCE_FILENAMES
    ):
        raise ValueError(f"Invalid benchmark source hashes: {manifest_path}")
    for filename in BENCHMARK_SOURCE_FILENAMES:
        source_file = PROJECT_ROOT / "data" / "source" / filename
        if source_hashes.get(filename) != _sha256(source_file):
            raise ValueError(f"Benchmark source checksum mismatch: {source_file}")

    artifact_hashes = manifest.get("artifact_files_sha256")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != BENCHMARK_ARTIFACT_FILENAMES:
        raise ValueError(f"Invalid benchmark artifact hashes: {manifest_path}")
    for filename in BENCHMARK_ARTIFACT_FILENAMES:
        artifact = benchmark_dir / filename
        if not artifact.is_file() or artifact_hashes.get(filename) != _sha256(artifact):
            raise ValueError(f"Benchmark artifact checksum mismatch: {artifact}")
    if schema_version == _DERIVED_BENCHMARK_SCHEMA_VERSION:
        _validate_derived_train_selection(benchmark_dir, manifest)


def _sha256(path: Path) -> str:
    """Return a SHA-256 fingerprint for a persisted run input."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision() -> str | None:
    """Return the checked-out revision when the source tree is a Git checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def initialize_components(paths: ProjectPaths) -> Tuple[Attacker, Defender, Verifier]:
    """Initialize all training-loop components.

    Returns:
        Tuple of (Attacker, Defender, Verifier).
    """
    # Load paths
    normal_sqls_path = paths.source_data_dir / "normal_sqls.json"
    validation_datas_path = paths.benchmark_dir / sft_filename("valid_sqls.json", PROMPT_MODE)
    test_datas_path = paths.benchmark_dir / sft_filename("test_sqls.json", PROMPT_MODE)
    training_config_path = paths.config_dir / "training_config.yaml"
    inference_config_path = paths.config_dir / "inference_config.yaml"

    # MAB arms are fixed by taxonomy, never inferred from a dataset's contents.
    cluster_list = all_attack_cluster_keys()
    _validate_benchmark_contract(paths.benchmark_dir)
    _validate_benchmark_coverage(paths.benchmark_dir / "train_sqls.json", cluster_list)
    _validate_benchmark_coverage(paths.benchmark_dir / "valid_sqls.json", cluster_list)
    _validate_benchmark_coverage(paths.benchmark_dir / "test_sqls.json", cluster_list)

    # Initialize components
    attacker = Attacker(
        number_of_training_sqls=NUM_TRAINING_SQLS,
        cluster_list=cluster_list,
        normal_sqls_path=str(normal_sqls_path),
        source_data_dir=str(paths.source_data_dir),
        benign_ratio=INITIAL_BENIGN_RATIO,
        enable_payload_mutation=ENABLE_PAYLOAD_MUTATION,
        mutation_model=MUTATION_MODEL,
        weight_exponent=ACTIVE_EXPERIMENT_CONFIG.attacker_weight_exponent,
        random_seed=ACTIVE_EXPERIMENT_CONFIG.random_seed,
        prompt_mode=PROMPT_MODE,
        mix_benign_sources=ACTIVE_EXPERIMENT_CONFIG.mix_benign_sources,
        mutation_weight_scale_min=ACTIVE_EXPERIMENT_CONFIG.payload_mutation_weight_scale_min,
        mutation_effective_probability_max=(
            ACTIVE_EXPERIMENT_CONFIG.payload_mutation_effective_probability_max
        ),
        mutation_llm_temperature=ACTIVE_EXPERIMENT_CONFIG.payload_mutation_llm_temperature,
        mutation_llm_max_tokens=ACTIVE_EXPERIMENT_CONFIG.payload_mutation_llm_max_tokens,
        mutation_info_focused_probability=(
            ACTIVE_EXPERIMENT_CONFIG.payload_mutation_info_focused_probability
        ),
        mutation_infer_expected_types=(
            ACTIVE_EXPERIMENT_CONFIG.payload_mutation_infer_expected_types
        ),
        mutation_types_inference_temperature=(
            ACTIVE_EXPERIMENT_CONFIG.payload_mutation_types_inference_temperature
        ),
        mutation_types_inference_max_tokens=(
            ACTIVE_EXPERIMENT_CONFIG.payload_mutation_types_inference_max_tokens
        ),
        mutation_fewshot_examples=ACTIVE_EXPERIMENT_CONFIG.payload_mutation_fewshot_examples,
        cepp_rational_explanation_probability=(
            ACTIVE_EXPERIMENT_CONFIG.synthesis_cepp_rational_explanation_probability
        ),
        cepp_llm_max_tokens=ACTIVE_EXPERIMENT_CONFIG.synthesis_cepp_llm_max_tokens,
        cepp_llm_max_retries=ACTIVE_EXPERIMENT_CONFIG.synthesis_cepp_llm_max_retries,
    )

    defender = Defender(
        validation_file=str(validation_datas_path),
        test_file=str(test_datas_path),
        training_config_path=str(training_config_path),
        inference_config_path=str(inference_config_path),
        random_seed=ACTIVE_EXPERIMENT_CONFIG.random_seed,
    )

    verifier = Verifier(
        cluster_list=cluster_list,
        benign_ratio=INITIAL_BENIGN_RATIO,
        reward_smoothing_alpha=ACTIVE_EXPERIMENT_CONFIG.verifier_reward_smoothing_alpha,
        reward_smoothing_beta=ACTIVE_EXPERIMENT_CONFIG.verifier_reward_smoothing_beta,
        benign_fpr_target=ACTIVE_EXPERIMENT_CONFIG.verifier_benign_fpr_target,
        benign_ratio_step_size=ACTIVE_EXPERIMENT_CONFIG.verifier_benign_ratio_step_size,
        benign_error_ema_decay=ACTIVE_EXPERIMENT_CONFIG.verifier_benign_error_ema_decay,
        benign_ratio_min=ACTIVE_EXPERIMENT_CONFIG.verifier_benign_ratio_min,
        benign_ratio_max=ACTIVE_EXPERIMENT_CONFIG.verifier_benign_ratio_max,
    )

    return attacker, defender, verifier


def _validate_benchmark_coverage(benchmark_file: Path, expected_clusters: List[str]) -> None:
    """Fail fast when a benchmark does not cover every declared MAB arm."""
    observed = set(
        get_injection_cluster_keys(
            cluster_injection_sqls(read_json_file(str(benchmark_file))).keys()
        )
    )
    expected = set(expected_clusters)
    if observed != expected:
        raise ValueError(
            f"Benchmark taxonomy coverage mismatch in {benchmark_file}: "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )


def attacker_gamma_for_round(round_idx: int, num_rounds: int) -> float:
    """Linearly schedule attack-distribution exploration for the active run."""
    if num_rounds <= 0:
        raise ValueError("num_rounds must be positive")
    if not 0 <= round_idx < num_rounds:
        raise ValueError(f"round_idx must be in [0, {num_rounds}), got {round_idx}")
    if num_rounds == 1:
        return ATTACKER_GAMMA_START
    return ATTACKER_GAMMA_START - (
        (ATTACKER_GAMMA_START - ATTACKER_GAMMA_END)
        * round_idx
        / (num_rounds - 1)
    )


def run_training_round(
    round_idx: int,
    paths: ProjectPaths,
    attacker: Attacker,
    defender: Defender,
    verifier: Verifier,
    strategy: str | None = None,
) -> None:
    """Execute a single adversarial training round.

    Args:
        round_idx: Current round index (0-based).
        paths:     Project path configuration.
        attacker:  Attacker component.
        defender:  Defender component.
        verifier:  Verifier component.
        strategy:  Sampling strategy; ``None`` uses the configured default.
    """
    round_started_at = time.perf_counter()
    stage_durations: Dict[str, float] = {}
    print(f"\n{'=' * 50}")
    print(f"Round {round_idx}")
    print(f"{'=' * 50}")

    # A caller may still provide an explicit strategy for an ablation experiment.
    if strategy is None:
        strategy = ATTACKER_STRATEGY
    print(f"Strategy: {strategy}")

    # Determine the current model path
    if round_idx == 0:
        current_model_path = paths.base_model_path
    else:
        current_model_path = paths.run_dir / f"round_{round_idx-1}" / "merged_model"

    # Create output directory for this round
    round_output_dir = paths.run_dir / f"round_{round_idx}"
    require_external_path(round_output_dir, purpose="round output")
    round_output_dir.mkdir(parents=True, exist_ok=True)
    attacker_gamma = attacker_gamma_for_round(round_idx, NUM_ROUNDS)
    round_metadata = {
        "taxonomy_version": TAXONOMY_VERSION,
        "attack_clusters": attacker.cluster_list,
        "attacker_gamma": attacker_gamma,
        "attacker_k": ATTACKER_K,
        "num_training_sqls": NUM_TRAINING_SQLS,
        "prompt_mode": PROMPT_MODE.value,
        "mix_benign_sources": ACTIVE_EXPERIMENT_CONFIG.mix_benign_sources,
        "verifier_update": ACTIVE_EXPERIMENT_CONFIG.verifier_update,
        "verifier_learning_rate": VERIFIER_LEARNING_RATE,
    }
    write_json_file(
        str(round_output_dir / "round_metadata.json"),
        round_metadata,
    )

    # Compute current-round payload mutation probability (linearly increases)
    modify_payload_prob = MODIFY_PAYLOAD_PROB_START + \
        (MODIFY_PAYLOAD_PROB_END - MODIFY_PAYLOAD_PROB_START) * (round_idx / max(NUM_ROUNDS - 1, 1))

    if ENABLE_PAYLOAD_MUTATION:
        print(f"Payload mutation probability: {modify_payload_prob:.2%}")
    print(f"Attacker gamma: {attacker_gamma:.4f}")

    # Step 1: Generate training SQLs
    with measure_stage(paths.run_dir, round_index=round_idx, stage="attack_generation") as timing:
        train_datas, _clusters_probability_distribution = attacker.generate_training_sqls(
            gamma=attacker_gamma,
            clusters_weight_distribution=verifier.get_weights(),
            strategy=strategy,
            k=ATTACKER_K,
            modify_payload_prob=modify_payload_prob,
        )
    stage_durations["attack_generation_seconds"] = timing["duration_seconds"]
    generation_stats = attacker.get_generation_stats()
    round_metadata["generation"] = generation_stats
    write_json_file(str(round_output_dir / "round_metadata.json"), round_metadata)
    write_json_file(str(round_output_dir / "generation_stats.json"), generation_stats)

    # Step 2: Save SFT training format
    train_datas_path = round_output_dir / "train_datas.jsonl"
    with measure_stage(paths.run_dir, round_index=round_idx, stage="training_data_write") as timing:
        write_jsonl_file(str(train_datas_path), train_datas)
    stage_durations["training_data_write_seconds"] = timing["duration_seconds"]

    # Step 3: Fine-tune and evaluate the model
    with measure_stage(paths.run_dir, round_index=round_idx, stage="defender_pipeline") as timing:
        defender_output = defender.run_all(
            base_model=str(current_model_path),
            train_file=str(train_datas_path),
            output_root=str(round_output_dir),
            do_inference=True,
        )
    stage_durations["defender_pipeline_seconds"] = timing["duration_seconds"]

    if defender_output is None:
        raise RuntimeError(
            "Defender pipeline failed before producing inference results. "
            "See the preceding fine-tuning, merge, or inference output."
        )
    stage_durations.update(defender_output.stages)

    # Step 4: Update attack-cluster and benign-ratio feedback for next round.
    # Validation observes every arm, so use centered full-information updates.
    validation_results = defender_output.validation.results
    with measure_stage(paths.run_dir, round_index=round_idx, stage="verifier_update") as timing:
        verifier.update_reward(results=validation_results)
        verifier.update_weight(
            learning_rate=VERIFIER_LEARNING_RATE,
        )
        attacker.set_benign_ratio(verifier.update_benign_ratio(results=validation_results))
    stage_durations["verifier_update_seconds"] = timing["duration_seconds"]
    round_metadata["verifier_reward_baseline"] = verifier.get_last_reward_baseline()

    persistence_started_at = time.perf_counter()
    # Step 5: Persist the complete Verifier feedback state.
    current_weights = verifier.get_weights()
    weights_data = [
        {"cluster": key, "weight": weight}
        for key, weight in current_weights.items()
    ]
    write_jsonl_file(
        str(round_output_dir / "cluster_weights.jsonl"),
        weights_data,
    )
    write_json_file(
        str(round_output_dir / "verifier_state.json"),
        verifier.get_benign_state(),
    )
    write_json_file(str(round_output_dir / "round_metadata.json"), round_metadata)

    # Step 6: Save mutated payloads (if mutation is enabled)
    if ENABLE_PAYLOAD_MUTATION:
        mutated_payloads = attacker.get_mutated_payloads()
        if mutated_payloads:
            write_json_file(
                str(round_output_dir / "mutated_payload_template.json"),
                mutated_payloads,
            )
            print(f"Saved {len(mutated_payloads)} mutated payloads to mutated_payload_template.json")

        # Persist MutationMemory for breakpoint recovery
        if attacker.mutation_memory is not None:
            memory_save_path = str(round_output_dir / "mutation_memory.json")
            attacker.mutation_memory.save(memory_save_path)
            print("MutationMemory saved to mutation_memory.json")

    # Step 7: Clean up the previous round's model to save disk space
    if round_idx > 0:
        prev_model_dir = paths.run_dir / f"round_{round_idx-1}" / "merged_model"
        delete_folder_if_exists(prev_model_dir)

    stage_durations["artifact_persistence_seconds"] = time.perf_counter() - persistence_started_at
    write_json_file(
        str(round_output_dir / "performance.json"),
        {
            "schema_version": 1,
            "round": round_idx,
            "completed_at": utc_timestamp(),
            "round_duration_seconds": time.perf_counter() - round_started_at,
            "stages": stage_durations,
        },
    )
    write_experiment_reports(paths.run_dir)


def run_training_loop(
    start_round: int = 0,
    breakpoint_round: int = -1,
    run_id: str | None = None,
    benchmark_dir: str | Path | None = None,
) -> None:
    """Execute the full multi-round adversarial training loop.

    Args:
        start_round:      First round index in the range.
        breakpoint_round: If >= 0, resume from this round by loading its
                          saved cluster weights, benign-ratio controller
                          state, and mutation memory.
                          Rounds <= breakpoint_round are skipped.
    """
    paths = ProjectPaths.create(run_id=run_id, benchmark_dir=benchmark_dir)
    os.chdir(paths.project_root)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(log_file=str(paths.run_dir / "logs" / "co-sqli.log"))

    # Validate runtime inputs before recording a manifest for this run.
    attacker, defender, verifier = initialize_components(paths)

    # If resuming from a breakpoint, load saved Verifier state and MutationMemory.
    if breakpoint_round >= 0:
        metadata_file = paths.run_dir / f"round_{breakpoint_round}" / "round_metadata.json"
        if not metadata_file.exists():
            raise ValueError(
                "Checkpoint metadata is missing; start a new run instead."
            )
        round_metadata = read_json_file(str(metadata_file))
        if (
            round_metadata.get("taxonomy_version") != TAXONOMY_VERSION
            or round_metadata.get("attack_clusters") != verifier.cluster_list
            or round_metadata.get("prompt_mode") != PROMPT_MODE.value
            or round_metadata.get("mix_benign_sources", False)
            != ACTIVE_EXPERIMENT_CONFIG.mix_benign_sources
        ):
            raise ValueError(
                "Checkpoint metadata does not match the current taxonomy, prompt mode, "
                "or benign sampling mode."
            )

        weights_file = paths.run_dir / f"round_{breakpoint_round}" / "cluster_weights.jsonl"
        if weights_file.exists():
            current_weights = read_jsonl_file(str(weights_file))
            verifier.set_weights({
                item["cluster"]: item["weight"]
                for item in current_weights
            })
            print(f"Restored cluster weights from round {breakpoint_round}")
        else:
            print(f"Warning: breakpoint weights file not found: {weights_file}")

        verifier_state_file = (
            paths.run_dir
            / f"round_{breakpoint_round}"
            / "verifier_state.json"
        )
        if verifier_state_file.exists():
            verifier_state = read_json_file(str(verifier_state_file))
            if not isinstance(verifier_state, dict):
                raise ValueError(
                    f"Invalid verifier state file: {verifier_state_file}"
                )
            try:
                verifier.set_benign_state(
                    benign_ratio=verifier_state["benign_ratio"],
                    benign_error_ema=verifier_state["benign_error_ema"],
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid verifier state file: {verifier_state_file}"
                ) from error
            attacker.set_benign_ratio(verifier.get_benign_ratio())
            print(f"Restored benign-ratio state from round {breakpoint_round}")
        else:
            print(
                "Warning: breakpoint verifier state file not found: "
                f"{verifier_state_file} — using the initial benign ratio"
            )

        # Restore MutationMemory (if mutation is enabled)
        if ENABLE_PAYLOAD_MUTATION and attacker.mutation_memory is not None:
            from cosqli.synthesis.payload_mutation.memory import MutationMemory
            memory_file = paths.run_dir / f"round_{breakpoint_round}" / "mutation_memory.json"
            if memory_file.exists():
                restored_memory = MutationMemory.load(str(memory_file))
                # Preserve the mutator's reference and static source templates.
                attacker.mutation_memory.restore_mutations_from(restored_memory)
                print(f"Restored MutationMemory from round {breakpoint_round} "
                      f"({len(restored_memory.global_fingerprints)} fingerprints, "
                      f"{len(restored_memory.categories)} categories)")
            else:
                print(f"Warning: breakpoint MutationMemory file not found: {memory_file} — using empty memory")

    write_json_file(
        str(paths.run_dir / "run_manifest.json"),
        {
            "project": "Co-SQLi",
            "run_id": paths.run_dir.name,
            "taxonomy_version": TAXONOMY_VERSION,
            "attack_clusters": all_attack_cluster_keys(),
            "code_revision": _git_revision(),
            "experiment_config": ACTIVE_EXPERIMENT_CONFIG.as_dict(),
            "prompt_mode": PROMPT_MODE.value,
            "experiment_config_source_sha256": experiment_config_sha256(
                ACTIVE_EXPERIMENT_CONFIG_PATH
            ),
            "resolved_experiment_config_sha256": resolved_experiment_config_sha256(
                ACTIVE_EXPERIMENT_CONFIG
            ),
            "verifier_update": ACTIVE_EXPERIMENT_CONFIG.verifier_update,
            "verifier_learning_rate": VERIFIER_LEARNING_RATE,
            "benchmark_dir": str(paths.benchmark_dir),
            "benchmark_manifest_sha256": _sha256(
                paths.benchmark_dir / "build_manifest.json"
            ),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "started_at": utc_timestamp(),
        },
    )

    # Run training rounds
    for round_idx in range(start_round, NUM_ROUNDS):
        if breakpoint_round >= 0 and round_idx <= breakpoint_round:
            continue

        run_training_round(
            round_idx=round_idx,
            paths=paths,
            attacker=attacker,
            defender=defender,
            verifier=verifier,
            strategy=ATTACKER_STRATEGY,
        )

    write_experiment_reports(paths.run_dir)


# ==================== Entry Point ====================

def parse_args() -> argparse.Namespace:
    """Parse run identity, benchmark input, and configuration overrides."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment-config",
        default=str(DEFAULT_EXPERIMENT_CONFIG_PATH),
        help="Path to a complete experiment configuration YAML file.",
    )
    parser.add_argument(
        "--num-rounds",
        type=int,
        default=None,
        help="Override num_rounds in the experiment configuration.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="External artifact directory name; reuse it only to resume a matching checkpoint.",
    )
    parser.add_argument(
        "--breakpoint-round",
        type=int,
        default=-1,
        help="Last completed round to restore from within --run-id (default: no restore).",
    )
    parser.add_argument(
        "--num-training-sqls",
        type=int,
        default=None,
        help="Override num_training_sqls in the experiment configuration.",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=[mode.value for mode in PROMPT_MODES],
        default=None,
        help="Override the model-visible SQL prompt context for this run.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override random_seed in the experiment configuration.",
    )
    parser.add_argument(
        "--benchmark-dir",
        type=str,
        default=os.environ.get("COSQLI_BENCHMARK_DIR"),
        help="External benchmark directory built by the Co-SQLi-Benchmark project.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the configured training loop."""
    args = parse_args()
    config_path = Path(args.experiment_config).expanduser().resolve()
    config = load_experiment_config(config_path).with_cli_overrides(
        num_rounds=args.num_rounds,
        num_training_sqls=args.num_training_sqls,
        prompt_mode=args.prompt_mode,
        random_seed=args.seed,
    )
    if config.num_rounds <= 0 or config.num_training_sqls <= 0:
        raise ValueError("--num-rounds and --num-training-sqls must be positive")
    if args.breakpoint_round >= config.num_rounds:
        raise ValueError("--breakpoint-round must be smaller than --num-rounds")
    if args.breakpoint_round < -1:
        raise ValueError("--breakpoint-round must be -1 or a completed round index")

    configure_experiment(config, config_path)
    run_training_loop(
        start_round=0,
        breakpoint_round=args.breakpoint_round,
        run_id=args.run_id,
        benchmark_dir=args.benchmark_dir,
    )


if __name__ == "__main__":
    main()
