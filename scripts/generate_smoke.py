#!/usr/bin/env python3
"""Generate a small SFT batch to verify the Attacker, MySQL, and LLM path."""

from __future__ import annotations

import argparse

from Attacker.attacker import Attacker
from Verifier.verifier import Verifier
from main import (
    ATTACKER_GAMMA,
    ATTACKER_K,
    ATTACKER_STRATEGY,
    ENABLE_PAYLOAD_MUTATION,
    MODIFY_PAYLOAD_PROB_START,
    ProjectPaths,
)
from utils.cluster import cluster_injection_sqls
from utils.json_operation import read_json_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples",
        type=int,
        default=12,
        help="Number of SFT records to generate (default: 12).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.samples <= 0:
        raise ValueError("--samples must be positive")

    paths = ProjectPaths.create()
    cluster_list = list(
        cluster_injection_sqls(read_json_file(paths.benchmark_dir / "test_sqls.json")).keys()
    )
    attacker = Attacker(
        number_of_training_sqls=args.samples,
        cluster_list=cluster_list,
        normal_sqls_path=str(paths.raw_datas_dir / "normal_sqls.json"),
        raw_datas_dir=str(paths.raw_datas_dir),
        enable_payload_mutation=ENABLE_PAYLOAD_MUTATION,
    )
    verifier = Verifier(cluster_list=cluster_list)
    records, _ = attacker.generate_training_sqls(
        gamma=ATTACKER_GAMMA,
        clusters_weight_distribution=verifier.get_weights(),
        strategy=ATTACKER_STRATEGY,
        k=ATTACKER_K,
        expected_example_num=args.samples,
        modify_payload_prob=MODIFY_PAYLOAD_PROB_START,
    )

    if len(records) != args.samples:
        raise RuntimeError(f"Expected {args.samples} SFT records, got {len(records)}")
    if not all("messages" in record and len(record["messages"]) == 3 for record in records):
        raise RuntimeError("Generated records do not match the expected SFT message format")

    malicious = sum(not record["label"] for record in records)
    print(
        "Generation smoke test passed; "
        f"records={len(records)}, malicious={malicious}, benign={len(records) - malicious}"
    )


if __name__ == "__main__":
    main()
