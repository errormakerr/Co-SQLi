"""Co-SQLi adversarial training loop (attack, defend, verify)."""

import argparse
from datetime import datetime, timezone
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from cosqli.attacker.attacker import Attacker
from cosqli.defender.defender import Defender
from cosqli.paths import (
    PROJECT_ROOT,
    get_config_path,
    require_artifacts_root,
    require_external_path,
    validate_run_id,
)
from cosqli.verifier.verifier import Verifier
from cosqli.utils.cluster import (
    TAXONOMY_VERSION,
    all_attack_cluster_keys,
    cluster_injection_sqls,
    get_injection_cluster_keys,
)
from cosqli.utils.json_operation import read_json_file, read_jsonl_file, write_jsonl_file, write_json_file
from cosqli.utils.logging_config import setup_logging
from cosqli.utils.yaml_operation import load_yaml_to_dict


# ==================== Configuration Constants ====================

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
    def create(cls, run_id: str | None = None) -> "ProjectPaths":
        """Load runtime inputs and create an external, isolated run directory."""
        project_root = PROJECT_ROOT
        config_dir = project_root / "config"
        runtime_config_path = get_config_path("runtime_config.yaml")
        if not runtime_config_path.is_file():
            raise FileNotFoundError(
                "Missing runtime configuration: "
                f"{runtime_config_path}. Copy config/runtime_config.yaml.example "
                "to COSQLI_CONFIG_DIR and set the required environment variables."
            )

        runtime_config = load_yaml_to_dict(str(runtime_config_path))
        required_keys = {"base_model_path_env", "artifacts_root"}
        missing_keys = required_keys.difference(runtime_config)
        if missing_keys:
            raise ValueError(
                f"{runtime_config_path} is missing required keys: "
                f"{', '.join(sorted(missing_keys))}"
            )

        model_env_name = runtime_config["base_model_path_env"]
        if not isinstance(model_env_name, str) or not model_env_name:
            raise ValueError("base_model_path_env must name a non-empty environment variable")
        model_path_value = os.environ.get(model_env_name)
        if not model_path_value:
            raise EnvironmentError(
                f"Set {model_env_name} to the local base-model directory before running Co-SQLi."
            )
        base_model_path = Path(model_path_value).expanduser().resolve()
        artifacts_root = require_artifacts_root(runtime_config["artifacts_root"])
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

        return cls(
            project_root=project_root,
            source_data_dir=project_root / "data" / "source",
            benchmark_dir=project_root / "data" / "benchmark",
            run_dir=run_dir,
            config_dir=config_dir,
            base_model_path=base_model_path,
        )


# ==================== Training Parameters ====================

NUM_ROUNDS = 8
NUM_TRAINING_SQLS = 300
ATTACKER_GAMMA = 0.7
VERIFIER_GAMMA = 0.3
ATTACKER_STRATEGY = "by_probability"  # EXP3 probability sampling for every round
ATTACKER_K = 6
INITIAL_BENIGN_RATIO = 0.25

# ==================== Payload Mutation Parameters ====================

ENABLE_PAYLOAD_MUTATION = True       # Whether to enable payload mutation
MODIFY_PAYLOAD_PROB_START = 0.1      # Mutation probability at the first round
MODIFY_PAYLOAD_PROB_END = 0.4        # Mutation probability at later rounds
MUTATION_MODEL = None                # Model for mutation; None uses config default


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

def initialize_components(paths: ProjectPaths) -> Tuple[Attacker, Defender, Verifier]:
    """Initialize all training-loop components.

    Returns:
        Tuple of (Attacker, Defender, Verifier).
    """
    # Load paths
    normal_sqls_path = paths.source_data_dir / "normal_sqls.json"
    valid_datas_path = paths.benchmark_dir / "valid_datas_openai_format.jsonl"
    training_config_path = paths.config_dir / "training_config.yaml"
    inference_config_path = paths.config_dir / "inference_config.yaml"

    # MAB arms are fixed by taxonomy, never inferred from a dataset's contents.
    cluster_list = all_attack_cluster_keys()
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
    )

    defender = Defender(
        valid_file=str(valid_datas_path),
        training_config_path=str(training_config_path),
        inference_config_path=str(inference_config_path),
    )

    verifier = Verifier(
        cluster_list=cluster_list,
        benign_ratio=INITIAL_BENIGN_RATIO,
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


def run_training_round(
    round_idx: int,
    paths: ProjectPaths,
    attacker: Attacker,
    defender: Defender,
    verifier: Verifier,
    strategy: str = None,
) -> None:
    """Execute a single adversarial training round.

    Args:
        round_idx: Current round index (0-based).
        paths:     Project path configuration.
        attacker:  Attacker component.
        defender:  Defender component.
        verifier:  Verifier component.
        strategy:  Sampling strategy; ``None`` uses the configured EXP3 default.
    """
    print(f"\n{'=' * 50}")
    print(f"Round {round_idx}")
    print(f"{'=' * 50}")

    # Keep the full run exploratory: EXP3 probabilities select clusters every round.
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
    write_json_file(
        str(round_output_dir / "round_metadata.json"),
        {
            "taxonomy_version": TAXONOMY_VERSION,
            "attack_clusters": attacker.cluster_list,
        },
    )

    # Compute current-round payload mutation probability (linearly increases)
    modify_payload_prob = MODIFY_PAYLOAD_PROB_START + \
        (MODIFY_PAYLOAD_PROB_END - MODIFY_PAYLOAD_PROB_START) * (round_idx / max(NUM_ROUNDS - 1, 1))

    if ENABLE_PAYLOAD_MUTATION:
        print(f"Payload mutation probability: {modify_payload_prob:.2%}")

    # Step 1: Generate training SQLs
    train_datas, clusters_probability_distribution = attacker.generate_training_sqls(
        gamma=ATTACKER_GAMMA,
        clusters_weight_distribution=verifier.get_weights(),
        strategy=strategy,
        k=ATTACKER_K,
        modify_payload_prob=modify_payload_prob,
    )

    # Step 2: Save SFT training format
    train_datas_path = round_output_dir / "train_datas.jsonl"
    write_jsonl_file(str(train_datas_path), train_datas)

    # Step 3: Fine-tune and evaluate the model
    results = defender.run_all(
        base_model=str(current_model_path),
        train_file=str(train_datas_path),
        output_root=str(round_output_dir),
        do_inference=True,
    )

    if results is None:
        raise RuntimeError(
            "Defender pipeline failed before producing inference results. "
            "See the preceding fine-tuning, merge, or inference output."
        )

    # Step 4: Update attack-cluster and benign-ratio feedback for next round.
    verifier.update_reward(results=results)
    verifier.update_weight(
        gamma=VERIFIER_GAMMA,
        cluster_probability_distribution=clusters_probability_distribution,
    )
    attacker.set_benign_ratio(verifier.update_benign_ratio(results=results))

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


def run_training_loop(
    start_round: int = 0,
    breakpoint_round: int = -1,
    run_id: str | None = None,
) -> None:
    """Execute the full multi-round adversarial training loop.

    Args:
        start_round:      First round index in the range.
        breakpoint_round: If >= 0, resume from this round by loading its
                          saved cluster weights, benign-ratio controller
                          state, and mutation memory.
                          Rounds <= breakpoint_round are skipped.
    """
    paths = ProjectPaths.create(run_id=run_id)
    os.chdir(paths.project_root)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(log_file=str(paths.run_dir / "co-sqli.log"))
    write_json_file(
        str(paths.run_dir / "run_manifest.json"),
        {
            "project": "Co-SQLi",
            "taxonomy_version": TAXONOMY_VERSION,
            "attack_clusters": all_attack_cluster_keys(),
        },
    )

    # Initialize components
    attacker, defender, verifier = initialize_components(paths)

    # If resuming from a breakpoint, load saved Verifier state and MutationMemory.
    if breakpoint_round >= 0:
        metadata_file = paths.run_dir / f"round_{breakpoint_round}" / "round_metadata.json"
        if not metadata_file.exists():
            raise ValueError(
                "Cannot restore a pre-taxonomy-v3 checkpoint. Start a new run instead."
            )
        round_metadata = read_json_file(str(metadata_file))
        if (
            round_metadata.get("taxonomy_version") != TAXONOMY_VERSION
            or round_metadata.get("attack_clusters") != verifier.cluster_list
        ):
            raise ValueError(
                "Checkpoint taxonomy mismatch; start a new taxonomy-v3 run instead."
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


# ==================== Entry Point ====================

def parse_args() -> argparse.Namespace:
    """Parse optional overrides used for small-scale validation runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--num-rounds",
        type=int,
        default=NUM_ROUNDS,
        help=f"Number of adversarial rounds to run (default: {NUM_ROUNDS}).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="External artifact directory name; reuse it only to resume a v3 checkpoint.",
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
        default=NUM_TRAINING_SQLS,
        help=(
            "Training examples generated per round "
            f"(default: {NUM_TRAINING_SQLS})."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run the configured training loop."""
    global NUM_ROUNDS, NUM_TRAINING_SQLS

    args = parse_args()
    if args.num_rounds <= 0:
        raise ValueError("--num-rounds must be positive")
    if args.num_training_sqls <= 0:
        raise ValueError("--num-training-sqls must be positive")
    if args.breakpoint_round >= args.num_rounds:
        raise ValueError("--breakpoint-round must be smaller than --num-rounds")
    if args.breakpoint_round < -1:
        raise ValueError("--breakpoint-round must be -1 or a completed round index")

    NUM_ROUNDS = args.num_rounds
    NUM_TRAINING_SQLS = args.num_training_sqls
    run_training_loop(
        start_round=0,
        breakpoint_round=args.breakpoint_round,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
