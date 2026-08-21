"""
Attacker module — adversarial SQL injection sample generator.

Responsibilities
----------------
1. Maintain a MAB-informed cluster probability distribution over injection
   attack categories.
2. On each training round, sample *k* clusters and generate
   ``expected_injection_num`` injection SQL examples + ``expected_normal_num``
   normal SQL examples to form the round's training set.
3. Optionally mutate payload templates using a LLM-backed ``PayloadMutator``
   to increase sample diversity.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils.cluster import NORMAL_CLUSTER_KEY, ClusterKey, cluster_payload_templates
from utils.json_operation import read_json_file
from utils.LLM import LLM
from utils.yaml_operation import load_yaml_to_dict
from synthesis.sft_formatter import batch_process_to_sft

from synthesis.injection_pipeline import pipeline
from synthesis.payload_mutation import MutationMemory, PayloadMutator

# ---------------------------------------------------------------------------
# Named constants (extracted from inline magic numbers)
# ---------------------------------------------------------------------------

NORMAL_CLUSTER_WEIGHT_MULTIPLIER = 10.0
"""Normal cluster probability is scaled by this factor when computing the injection ratio."""

DEFAULT_MODIFY_PROBABILITY = 0.5
"""Default probability of mutating a payload template."""

MUTATION_PROB_LOWER_SCALE = 0.5
"""Lower-bound factor applied to the base mutation probability."""

MUTATION_PROB_UPPER_BOUND = 0.8
"""Absolute upper bound for the effective mutation probability."""


class Attacker:
    """
    Adversarial SQL injection sample generator with MAB-guided cluster sampling.

    Args:
        number_of_training_sqls: Total number of SQL samples (injection +
            normal) to generate per round.
        cluster_list:            Complete list of cluster key strings
            (as returned by ``cluster_injection_sqls``), including the normal
            cluster ``NORMAL_CLUSTER_KEY``.
        normal_sqls_path:        Path to ``normal_sqls.json``.
        raw_datas_dir:           Directory containing ``payloads.json``,
            ``sql_data_with_injection_point.json``, ``schema.json``, etc.
        enable_payload_mutation: Whether to activate LLM-based payload
            mutation.  Requires a valid LLM config at ``config/gpt_config.yaml``.
        mutation_model:          Override the LLM model name used for mutation.
            Defaults to the value in ``gpt_config.yaml``.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        number_of_training_sqls: int,
        cluster_list: List[str],
        normal_sqls_path: Optional[str] = None,
        raw_datas_dir: Optional[str] = None,
        enable_payload_mutation: bool = True,
        mutation_model: Optional[str] = None,
    ) -> None:
        if not cluster_list:
            raise ValueError("cluster_list must not be empty")
        if normal_sqls_path is None:
            raise ValueError("normal_sqls_path must be provided")
        if raw_datas_dir is None:
            raise ValueError("raw_datas_dir must be provided")

        self.cluster_list = cluster_list
        self.number_of_training_sqls = number_of_training_sqls

        # Initialise uniform cluster probability distribution
        init_prob = 1.0 / len(cluster_list)
        self.clusters_probability_distribution: Dict[str, float] = {
            key: init_prob for key in cluster_list
        }

        # Injection ratio: derived from the normal cluster's probability
        # (normal cluster weight is 10× its probability in the training set)
        self.rate_of_injection_sqls = (
            1.0 - NORMAL_CLUSTER_WEIGHT_MULTIPLIER * self.clusters_probability_distribution[NORMAL_CLUSTER_KEY]
        )

        # Load raw data files
        self.normal_sqls: List[Dict[str, Any]] = read_json_file(normal_sqls_path)

        raw_sqls = read_json_file(f"{raw_datas_dir}/sql_data_with_injection_point.json")
        self.train_raw_sqls: List[Dict[str, Any]] = [
            sql for sql in raw_sqls if sql.get("set") == "train"
        ]

        payloads = read_json_file(f"{raw_datas_dir}/payloads.json")
        self.train_payloads: List[Dict[str, Any]] = [
            p for p in payloads if p.get("set") == "train"
        ]
        self.train_payloads_clusters: Dict[str, List[Dict[str, Any]]] = (
            cluster_payload_templates(self.train_payloads)
        )

        self.db_schemas = read_json_file(f"{raw_datas_dir}/schema.json")
        self.sys_schemas = read_json_file(f"{raw_datas_dir}/system_table_schema.json")
        self.system_vars = read_json_file(f"{raw_datas_dir}/system_var.json")
        self.comment_list = read_json_file(f"{raw_datas_dir}/comment_repository.json")

        # Payload mutation setup
        self.enable_payload_mutation = enable_payload_mutation
        self.payload_mutator: Optional[PayloadMutator] = None
        self.mutation_memory: Optional[MutationMemory] = None

        # Per-round list of successfully mutated payloads (for logging/saving)
        self.mutated_payloads: List[Dict[str, Any]] = []

        if enable_payload_mutation:
            self._init_payload_mutator(mutation_model)

    # ------------------------------------------------------------------
    # Normal SQL sampling
    # ------------------------------------------------------------------

    def _sample_normal_sqls(
        self, k: int, replace: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Sample *k* normal SQL examples from ``self.normal_sqls``.

        Args:
            k:       Number of samples requested.
            replace: Allow sampling with replacement when ``True``.

        Raises:
            RuntimeError: If ``normal_sqls`` is empty.
            ValueError:   If without-replacement sampling requests more than
                          available examples.
        """
        total = len(self.normal_sqls)
        if total == 0:
            raise RuntimeError("normal_sqls is empty — cannot sample")
        if not replace and k > total:
            raise ValueError(
                f"Without-replacement sampling failed: requested {k} items "
                f"but only {total} are available"
            )
        if replace and k > total:
            return random.choices(self.normal_sqls, k=k)
        return random.sample(self.normal_sqls, k=k)

    # ------------------------------------------------------------------
    # MAB cluster probability distribution
    # ------------------------------------------------------------------

    def _update_clusters_probability_distribution(
        self,
        gamma: float,
        clusters_weight_distribution: Dict[str, float],
    ) -> None:
        """
        Update ``clusters_probability_distribution`` using the MAB EXP3 rule.

        The update blends the weight-proportional distribution with a uniform
        prior controlled by *gamma* (exploration rate):

            p(k) = (1 - γ) × w(k) / Σw  +  γ / N

        Args:
            gamma:                        Exploration coefficient (0 < γ ≤ 1).
            clusters_weight_distribution: Current MAB weights from the Verifier.
        """
        weights = {
            key: float(clusters_weight_distribution.get(key, 0.0))
            for key in self.cluster_list
        }
        total_weight = sum(weights.values())

        n = len(self.cluster_list)

        if total_weight <= 0:
            uniform = 1.0 / n
            self.clusters_probability_distribution = {k: uniform for k in self.cluster_list}
            return

        new_dist: Dict[str, float] = {
            key: (1.0 - gamma) * (weights[key] / total_weight) + gamma / n
            for key in self.cluster_list
        }

        dist_sum = sum(new_dist.values())
        if dist_sum <= 0:
            uniform = 1.0 / n
            self.clusters_probability_distribution = {k: uniform for k in self.cluster_list}
        else:
            self.clusters_probability_distribution = {
                k: v / dist_sum for k, v in new_dist.items()
            }

    def _select_clusters(self, strategy: str = "by_probability", k: int = 10) -> List[str]:
        """
        Select *k* non-normal clusters for the current training round.

        Args:
            strategy: ``"by_probability"`` — weighted random sampling without
                      replacement; ``"top_k"`` — deterministically pick the *k*
                      highest-probability clusters.
            k:        Number of clusters to select.

        Returns:
            List of *k* cluster key strings.

        Raises:
            ValueError: If *k* is non-positive or exceeds the number of
                        non-normal clusters.
        """
        # Exclude the "normal" cluster from selection
        non_normal = {
            key: prob
            for key, prob in self.clusters_probability_distribution.items()
            if key != NORMAL_CLUSTER_KEY
        }

        if k <= 0:
            raise ValueError(f"_select_clusters: k must be > 0, got {k}")
        if k > len(non_normal):
            raise ValueError(
                f"_select_clusters: k={k} exceeds the number of non-normal "
                f"clusters ({len(non_normal)})"
            )

        if strategy == "top_k":
            return [
                key
                for key, _ in sorted(non_normal.items(), key=lambda x: x[1], reverse=True)[:k]
            ]

        if strategy == "by_probability":
            keys = list(non_normal.keys())
            probs = np.array(list(non_normal.values()), dtype=float)
            total = probs.sum()
            probs = probs / total if total > 0 else np.full(len(probs), 1.0 / len(probs))
            indices = np.random.default_rng().choice(len(keys), size=k, replace=False, p=probs)
            return [keys[i] for i in indices]

        raise ValueError(f"_select_clusters: unsupported strategy {strategy!r}")

    # ------------------------------------------------------------------
    # Raw data lookup
    # ------------------------------------------------------------------

    def _get_raw_data_by_cluster_feature(
        self, cluster: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
        """
        Randomly sample a (sql_example, payload_template, comment_flag) tuple
        matching *cluster*.

        Args:
            cluster: A four-part cluster key string
                     ``type||annotator||information_features||comment``.

        Returns:
            ``(sql_example, payload_template, comment_flag)``

        Raises:
            RuntimeError: If no matching raw SQL or payload template is found.
        """
        cluster_key = ClusterKey.from_str(cluster)

        sql_candidates = [
            sql for sql in self.train_raw_sqls
            if sql.get("annotator") == cluster_key.annotator
        ]
        if not sql_candidates:
            raise RuntimeError(
                f"No train_raw_sqls found for annotator={cluster_key.annotator!r} "
                f"(cluster={cluster!r})"
            )
        sql_example = random.choice(sql_candidates)

        payload_key = cluster_key.payload_cluster_key()
        payload_candidates = self.train_payloads_clusters.get(payload_key)
        if not payload_candidates:
            raise RuntimeError(
                f"No payload templates found for payload cluster {payload_key!r} "
                f"(cluster={cluster!r})"
            )
        payload_example = random.choice(payload_candidates)

        return sql_example, payload_example, cluster_key.comment

    # ------------------------------------------------------------------
    # Payload mutation
    # ------------------------------------------------------------------

    def _init_payload_mutator(self, mutation_model: Optional[str] = None) -> None:
        """
        Initialise the ``PayloadMutator`` and ``MutationMemory``.

        Falls back gracefully by disabling mutation when initialisation fails.
        """
        try:
            project_root = Path(__file__).resolve().parents[2]
            gpt_config = load_yaml_to_dict(str(project_root / "config" / "gpt_config.yaml"))

            llm = LLM(
                api_key=gpt_config["api_key"],
                base_url=gpt_config.get("base_url"),
                request_extra_body=gpt_config.get("extra_body"),
            )
            model = mutation_model or gpt_config.get("model")

            self.mutation_memory = MutationMemory()
            self.payload_mutator = PayloadMutator(llm, model, self.mutation_memory)

            print(f"✓ PayloadMutator initialised with model: {model}")

        except Exception as e:
            print(f"⚠ PayloadMutator initialisation failed: {e}")
            print("  Payload mutation disabled — using raw templates.")
            self.enable_payload_mutation = False
            self.payload_mutator = None
            self.mutation_memory = None

    def _modify_raw_payload_template(
        self,
        payload_template: Dict[str, Any],
        modify_probability: float = DEFAULT_MODIFY_PROBABILITY,
    ) -> Dict[str, Any]:
        """
        Attempt to mutate *payload_template* using the LLM.

        Mutation is skipped with probability ``1 - modify_probability`` to
        preserve sample diversity between mutated and original templates.

        Args:
            payload_template:   Original payload template dict.
            modify_probability: Probability of attempting mutation (0–1).

        Returns:
            A shallow copy of the (possibly mutated) payload template dict.
            The copy has extra debug keys ``_original_payload``,
            ``_mutation_type``, and ``_expected_types_inferred`` when mutation
            succeeds.
        """
        if not self.enable_payload_mutation or self.payload_mutator is None:
            return payload_template.copy()

        if random.random() > modify_probability:
            return payload_template.copy()

        try:
            result = self.payload_mutator.mutate(payload_template)
            if result is None:
                return payload_template.copy()

            mutated = payload_template.copy()
            mutated["payload"] = result["payload"]
            mutated["_original_payload"] = payload_template["payload"]
            mutated["_mutation_type"] = result.get("mutation_type", "unknown")

            if result.get("expected_types") is not None:
                mutated["expected_types"] = result["expected_types"]
                mutated["_expected_types_inferred"] = True
            else:
                mutated["_expected_types_inferred"] = False

            return mutated

        except Exception as e:
            print(f"⚠ Payload mutation error: {e}")
            return payload_template.copy()

    # ------------------------------------------------------------------
    # Stats accessors
    # ------------------------------------------------------------------

    def get_mutation_stats(self) -> Optional[Dict]:
        """Return mutation statistics from the ``PayloadMutator``, or ``None``."""
        if self.payload_mutator is not None:
            return self.payload_mutator.get_stats()
        return None

    def get_memory_stats(self) -> Optional[Dict]:
        """Return statistics from the ``MutationMemory``, or ``None``."""
        if self.mutation_memory is not None:
            return self.mutation_memory.get_stats()
        return None

    def get_mutated_payloads(self) -> List[Dict[str, Any]]:
        """Return a copy of the mutation log for the current round."""
        return self.mutated_payloads.copy()

    def clear_mutated_payloads(self) -> None:
        """Reset the per-round mutation log.  Call at the start of each round."""
        self.mutated_payloads = []

    # ------------------------------------------------------------------
    # Main public API
    # ------------------------------------------------------------------

    def generate_training_sqls(
        self,
        gamma: float,
        clusters_weight_distribution: Dict[str, float],
        strategy: str,
        k: int,
        expected_example_num: Optional[int] = None,
        modify_payload_prob: float = DEFAULT_MODIFY_PROBABILITY,
    ) -> Tuple[List[Any], Dict[str, float]]:
        """
        Generate a mixed set of injection + normal SQL examples for one round.

        The method:
        1. Updates the cluster probability distribution via the MAB rule.
        2. Selects *k* target clusters.
        3. Generates ``expected_injection_num`` injection SQL examples by
           cycling over the selected clusters and (optionally) mutating the
           sampled payload.  The mutation probability for each cluster is
           scaled by its MAB weight relative to the mean weight.
        4. Samples ``expected_normal_num`` normal SQL examples.
        5. Shuffles and returns the combined list.

        Args:
            gamma:                        MAB exploration coefficient.
            clusters_weight_distribution: Per-cluster MAB weights from the
                                          Verifier.
            strategy:                     Cluster selection strategy
                                          (``"by_probability"`` or ``"top_k"``).
            k:                            Number of clusters to select.
            expected_example_num:         Override the configured
                                          ``number_of_training_sqls``.
            modify_payload_prob:          Base payload mutation probability.

        Returns:
            ``(training_sqls, clusters_probability_distribution)`` where
            *training_sqls* is a shuffled list of formatted SFT training records.
        """
        expected_example_num = (
            self.number_of_training_sqls
            if expected_example_num is None
            else expected_example_num
        )
        if expected_example_num <= 0:
            raise ValueError(
                f"expected_example_num must be > 0, got {expected_example_num}"
            )

        self._update_clusters_probability_distribution(gamma, clusters_weight_distribution)

        self.rate_of_injection_sqls = (
            1.0 - NORMAL_CLUSTER_WEIGHT_MULTIPLIER * self.clusters_probability_distribution[NORMAL_CLUSTER_KEY]
        )
        expected_injection_num = int(expected_example_num * self.rate_of_injection_sqls)
        expected_normal_num = expected_example_num - expected_injection_num

        target_clusters = self._select_clusters(strategy=strategy, k=k)
        print(f"Selected clusters: {target_clusters}")

        # Pre-compute per-cluster effective mutation probabilities, scaled by
        # MAB weight relative to the mean weight.  Clusters where the model
        # struggles (high weight) receive a proportionally higher mutation
        # probability to generate more diverse, challenging training examples.
        active_weights = {
            cl: float(clusters_weight_distribution.get(cl, 1.0))
            for cl in target_clusters
        }
        mean_weight = sum(active_weights.values()) / max(len(active_weights), 1)

        injection_sql_examples: List[Any] = []
        mutation_count = 0
        count = 0

        self.clear_mutated_payloads()

        while count < expected_injection_num:
            for cluster in target_clusters:
                sql_example, payload_example, comment_flag = (
                    self._get_raw_data_by_cluster_feature(cluster)
                )

                # MAB-guided dynamic mutation probability:
                # clusters with higher weight (harder for the model) get a
                # proportionally higher effective mutation rate.
                cluster_weight = active_weights.get(cluster, mean_weight)
                scale = cluster_weight / mean_weight if mean_weight > 0 else 1.0
                effective_prob = float(
                    np.clip(
                        modify_payload_prob * scale,
                        modify_payload_prob * MUTATION_PROB_LOWER_SCALE,
                        MUTATION_PROB_UPPER_BOUND,
                    )
                )

                modified_payload = self._modify_raw_payload_template(
                    payload_template=payload_example,
                    modify_probability=effective_prob,
                )

                # Record successful mutations for later inspection / saving
                if modified_payload.get("_mutation_type") is not None:
                    mutation_count += 1
                    self.mutated_payloads.append(
                        {
                            "original_payload": modified_payload.get("_original_payload"),
                            "mutated_payload": modified_payload.get("payload"),
                            "mutation_type": modified_payload.get("_mutation_type"),
                            "attack_type": payload_example.get("type"),
                            "information_features": payload_example.get("information_features"),
                            "original_expected_types": payload_example.get("expected_types"),
                            "inferred_expected_types": modified_payload.get("expected_types"),
                            "expected_types_inferred": modified_payload.get(
                                "_expected_types_inferred", False
                            ),
                            "sql_db": sql_example.get("db"),
                            "sql_raw": sql_example.get("sql_raw"),
                            "sql_with_injection_point": sql_example.get("sql"),
                            "sql_query_columns": sql_example.get("query_columns"),
                            "sql_source": sql_example.get("source"),
                            "sql_annotator": sql_example.get("annotator"),
                            "cluster": cluster,
                            "comment_flag": comment_flag,
                        }
                    )

                injection_sql_example = pipeline(
                    sql_example=sql_example,
                    payload_template=modified_payload,
                    db_schemas=self.db_schemas,
                    sys_schemas=self.sys_schemas,
                    system_vars=self.system_vars,
                    comment_list=self.comment_list,
                    comment_flag=comment_flag,
                )
                if injection_sql_example is not None:
                    injection_sql_examples.append(injection_sql_example)
                    count += 1
                if count >= expected_injection_num:
                    break

        # Print mutation summary
        if self.enable_payload_mutation:
            print(
                f"Mutation stats: {mutation_count}/{count} samples used mutated payloads"
            )
            if self.payload_mutator is not None:
                stats = self.payload_mutator.get_stats()
                print(f"  Success rate:   {stats['success_rate']:.2%}")
                print(
                    f"  Attempts: {stats['total_attempts']}  "
                    f"Success: {stats['successful']}  "
                    f"Failed: {stats['failed']}  "
                    f"Duplicates: {stats['duplicates']}"
                )
                print(f"  Expected types inferred: {stats['types_inferred']}")
                if "types_inferrer_stats" in stats:
                    ts = stats["types_inferrer_stats"]
                    print(
                        f"  Type inference: LLM success={ts['llm_success']}, "
                        f"heuristic fallback={ts['fallback_used']}"
                    )

        normal_sql_examples = self._sample_normal_sqls(k=expected_normal_num, replace=False)

        training_sqls = injection_sql_examples + normal_sql_examples
        random.shuffle(training_sqls)
        
        # Format to SFT format
        formatted_training_sqls = batch_process_to_sft(training_sqls, self.db_schemas, format_type="openai")
        
        return formatted_training_sqls, self.clusters_probability_distribution
