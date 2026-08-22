"""SQLI Main Entry Point — Adversarial Training Loop (Attack-Defend-Verify)"""

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from Attacker.attacker import Attacker
from Defender.defender import Defender
from Verifier.verifier import Verifier
from utils.cluster import cluster_injection_sqls, get_injection_cluster_keys
from utils.json_operation import read_json_file, read_jsonl_file, write_jsonl_file, write_json_file
from utils.logging_config import setup_logging
from utils.yaml_operation import load_yaml_to_dict


# ==================== Configuration Constants ====================

@dataclass
class ProjectPaths:
    """Project directory paths configuration."""

    project_root: Path
    raw_datas_dir: Path
    benchmark_dir: Path
    temp_datas_dir: Path
    config_dir: Path
    base_model_path: Path

    @classmethod
    def create(cls) -> "ProjectPaths":
        """Load local model and output paths from the runtime configuration."""
        project_root = Path(__file__).resolve().parents[1]
        config_dir = project_root / "config"
        runtime_config_path = config_dir / "runtime_config.yaml"
        if not runtime_config_path.is_file():
            raise FileNotFoundError(
                "Missing runtime configuration: "
                f"{runtime_config_path}. Copy runtime_config.yaml.example and "
                "set base_model_path and run_output_dir."
            )

        runtime_config = load_yaml_to_dict(str(runtime_config_path))
        required_keys = {"base_model_path", "run_output_dir"}
        missing_keys = required_keys.difference(runtime_config)
        if missing_keys:
            raise ValueError(
                f"{runtime_config_path} is missing required keys: "
                f"{', '.join(sorted(missing_keys))}"
            )

        base_model_path = Path(runtime_config["base_model_path"]).expanduser().resolve()
        run_output_dir = Path(runtime_config["run_output_dir"]).expanduser().resolve()
        if not base_model_path.is_dir():
            raise FileNotFoundError(
                f"Configured base model directory does not exist: {base_model_path}"
            )
        if base_model_path == run_output_dir or base_model_path in run_output_dir.parents:
            raise ValueError(
                "run_output_dir must not be the base model directory or a directory within it."
            )

        return cls(
            project_root=project_root,
            raw_datas_dir=project_root / "data" / "raw_datas_for_generation",
            benchmark_dir=project_root / "data" / "benchmark",
            temp_datas_dir=run_output_dir,
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

def delete_folder_if_exists(folder_path: str) -> None:
    """Delete a directory if it exists; skip silently otherwise."""
    if not os.path.exists(folder_path):
        return

    if not os.path.isdir(folder_path):
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
    test_sqls_path = paths.benchmark_dir / "test_sqls.json"
    normal_sqls_path = paths.raw_datas_dir / "normal_sqls.json"
    valid_datas_path = paths.benchmark_dir / "valid_datas_openai_format.jsonl"
    training_config_path = paths.config_dir / "training_config.yaml"
    inference_config_path = paths.config_dir / "inference_config.yaml"

    # The benign cluster is evaluated separately; EXP3 has attack-only arms.
    cluster_list = get_injection_cluster_keys(
        cluster_injection_sqls(read_json_file(test_sqls_path)).keys()
    )

    # Initialize components
    attacker = Attacker(
        number_of_training_sqls=NUM_TRAINING_SQLS,
        cluster_list=cluster_list,
        normal_sqls_path=str(normal_sqls_path),
        raw_datas_dir=str(paths.raw_datas_dir),
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
        current_model_path = paths.temp_datas_dir / f"round_{round_idx-1}" / "merged_model"

    # Create output directory for this round
    round_output_dir = paths.temp_datas_dir / f"round_{round_idx}"
    round_output_dir.mkdir(parents=True, exist_ok=True)

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
                str(round_output_dir / "mutated_payloads.json"),
                mutated_payloads,
            )
            print(f"Saved {len(mutated_payloads)} mutated payloads to mutated_payloads.json")

        # Persist MutationMemory for breakpoint recovery
        if attacker.mutation_memory is not None:
            memory_save_path = str(round_output_dir / "mutation_memory.json")
            attacker.mutation_memory.save(memory_save_path)
            print("MutationMemory saved to mutation_memory.json")

    # Step 7: Clean up the previous round's model to save disk space
    if round_idx > 0:
        prev_model_dir = paths.temp_datas_dir / f"round_{round_idx-1}" / "merged_model"
        delete_folder_if_exists(str(prev_model_dir))


def run_training_loop(start_round: int = 0, breakpoint_round: int = -1) -> None:
    """Execute the full multi-round adversarial training loop.

    Args:
        start_round:      First round index in the range.
        breakpoint_round: If >= 0, resume from this round by loading its
                          saved cluster weights, benign-ratio controller
                          state, and mutation memory.
                          Rounds <= breakpoint_round are skipped.
    """
    paths = ProjectPaths.create()
    os.chdir(paths.project_root)

    # Initialize components
    attacker, defender, verifier = initialize_components(paths)

    # If resuming from a breakpoint, load saved Verifier state and MutationMemory.
    if breakpoint_round >= 0:
        weights_file = paths.temp_datas_dir / f"round_{breakpoint_round}" / "cluster_weights.jsonl"
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
            paths.temp_datas_dir
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
            from synthesis.payload_mutation.memory import MutationMemory
            memory_file = paths.temp_datas_dir / f"round_{breakpoint_round}" / "mutation_memory.json"
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

    NUM_ROUNDS = args.num_rounds
    NUM_TRAINING_SQLS = args.num_training_sqls
    setup_logging()
    run_training_loop(start_round=0)


if __name__ == "__main__":
    main()
