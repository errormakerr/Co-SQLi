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
from utils.cluster import cluster_injection_sqls
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
ATTACKER_STRATEGY = "by_probability"  # Default strategy for early rounds
ATTACKER_STRATEGY_TOP_K = "top_k"     # Strategy for later rounds
ATTACKER_K = 8

# Strategy switchover: use probability sampling for the first PROBABILITY_ROUNDS,
# then switch to top-k sampling.
PROBABILITY_ROUNDS = NUM_ROUNDS - 2  # First 6 rounds: probability; last 2: top-k

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

    # Build cluster list from benchmark test data
    cluster_list = list(cluster_injection_sqls(read_json_file(test_sqls_path)).keys())

    # Initialize components
    attacker = Attacker(
        number_of_training_sqls=NUM_TRAINING_SQLS,
        cluster_list=cluster_list,
        normal_sqls_path=str(normal_sqls_path),
        raw_datas_dir=str(paths.raw_datas_dir),
        enable_payload_mutation=ENABLE_PAYLOAD_MUTATION,
        mutation_model=MUTATION_MODEL,
    )

    defender = Defender(
        valid_file=str(valid_datas_path),
        training_config_path=str(training_config_path),
        inference_config_path=str(inference_config_path),
    )

    verifier = Verifier(cluster_list=cluster_list)

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
        strategy:  Sampling strategy; ``None`` selects automatically by round.
    """
    print(f"\n{'=' * 50}")
    print(f"Round {round_idx}")
    print(f"{'=' * 50}")

    # Auto-select strategy based on round index
    if strategy is None:
        if round_idx < PROBABILITY_ROUNDS:
            strategy = ATTACKER_STRATEGY
            print(f"Strategy: {strategy} (probability sampling)")
        else:
            strategy = ATTACKER_STRATEGY_TOP_K
            print(f"Strategy: {strategy} (top-k sampling, focus on high-weight clusters)")

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

    # Step 4: Update verifier weights (EXP3)
    verifier.update_reward(results=results)
    verifier.update_weight(
        gamma=VERIFIER_GAMMA,
        cluster_probability_distribution=clusters_probability_distribution,
    )

    # Step 5: Persist cluster weights
    current_weights = verifier.get_weights()
    weights_data = [
        {"cluster": key, "weight": weight}
        for key, weight in current_weights.items()
    ]
    write_jsonl_file(
        str(round_output_dir / "cluster_weights.jsonl"),
        weights_data,
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
                          saved cluster weights and mutation memory.
                          Rounds <= breakpoint_round are skipped.
    """
    paths = ProjectPaths.create()
    os.chdir(paths.project_root)

    # Initialize components
    attacker, defender, verifier = initialize_components(paths)

    # If resuming from a breakpoint, load saved weights and MutationMemory
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

        # Restore MutationMemory (if mutation is enabled)
        if ENABLE_PAYLOAD_MUTATION and attacker.mutation_memory is not None:
            from synthesis.payload_mutation.memory import MutationMemory
            memory_file = paths.temp_datas_dir / f"round_{breakpoint_round}" / "mutation_memory.json"
            if memory_file.exists():
                restored_memory = MutationMemory.load(str(memory_file))
                # Merge restored state into the existing memory object
                # (preserves the mutator's internal reference)
                attacker.mutation_memory.categories = restored_memory.categories
                attacker.mutation_memory.global_fingerprints = restored_memory.global_fingerprints
                print(f"Restored MutationMemory from round {breakpoint_round} "
                      f"({len(restored_memory.global_fingerprints)} fingerprints, "
                      f"{len(restored_memory.categories)} categories)")
            else:
                print(f"Warning: breakpoint MutationMemory file not found: {memory_file} — using empty memory")

    # Run training rounds
    for round_idx in range(start_round, NUM_ROUNDS):
        if breakpoint_round >= 0 and round_idx <= breakpoint_round:
            continue

        # Strategy is auto-selected inside run_training_round (None = auto)
        run_training_round(
            round_idx=round_idx,
            paths=paths,
            attacker=attacker,
            defender=defender,
            verifier=verifier,
            strategy=None,  # Auto-select based on round index
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
    global NUM_ROUNDS, NUM_TRAINING_SQLS, PROBABILITY_ROUNDS

    args = parse_args()
    if args.num_rounds <= 0:
        raise ValueError("--num-rounds must be positive")
    if args.num_training_sqls <= 0:
        raise ValueError("--num-training-sqls must be positive")

    NUM_ROUNDS = args.num_rounds
    NUM_TRAINING_SQLS = args.num_training_sqls
    PROBABILITY_ROUNDS = NUM_ROUNDS - 2
    setup_logging()
    run_training_loop(start_round=0)


if __name__ == "__main__":
    main()
