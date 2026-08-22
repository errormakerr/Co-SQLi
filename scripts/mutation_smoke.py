#!/usr/bin/env python3
"""Perform one LLM-backed payload mutation without logging payload contents."""

from __future__ import annotations

from Attacker.attacker import Attacker
from main import ENABLE_PAYLOAD_MUTATION, INITIAL_BENIGN_RATIO, ProjectPaths
from utils.cluster import cluster_injection_sqls, get_injection_cluster_keys
from utils.json_operation import read_json_file


def main() -> None:
    if not ENABLE_PAYLOAD_MUTATION:
        raise RuntimeError("Payload mutation is disabled in the current configuration")

    paths = ProjectPaths.create()
    cluster_list = get_injection_cluster_keys(
        cluster_injection_sqls(read_json_file(paths.benchmark_dir / "test_sqls.json")).keys()
    )
    attacker = Attacker(
        number_of_training_sqls=1,
        cluster_list=cluster_list,
        normal_sqls_path=str(paths.raw_datas_dir / "normal_sqls.json"),
        raw_datas_dir=str(paths.raw_datas_dir),
        benign_ratio=INITIAL_BENIGN_RATIO,
        enable_payload_mutation=True,
    )
    if attacker.payload_mutator is None:
        raise RuntimeError("Payload mutator was not initialized")

    template = next(
        payload
        for payload in attacker.train_payloads
        if payload.get("information_features") == "constant"
        and payload.get("expected_types") is None
    )
    result = attacker.payload_mutator.mutate_without_types(template)
    if result is None:
        raise RuntimeError("LLM-backed payload mutation was rejected or returned no content")

    print(
        "Mutation smoke test passed; "
        f"attack_type={result['attack_type']}, info_feature={result['info_feature']}"
    )


if __name__ == "__main__":
    main()
