"""
Payload Mutator — core orchestrator for LLM-based payload mutation.

Workflow
--------
1. Identify the payload's ``AttackType`` and ``InfoFeature``.
2. Route to the appropriate prompt template (``type_focused`` vs ``info_focused``).
3. Augment the prompt with category-specific few-shot examples from memory.
4. Call the LLM for mutation.
5. Validate the result; update memory on success.
6. Infer ``expected_types`` for the mutated payload (separate LLM call).
"""

import random
import sys
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Named constants
# ---------------------------------------------------------------------------

MUTATION_LLM_TEMPERATURE = 0.7
"""LLM sampling temperature for mutation generation."""

MUTATION_MAX_TOKENS = 2000
"""Maximum tokens allowed in a mutation LLM response."""

INFO_FOCUSED_PROMPT_PROBABILITY = 0.3
"""Probability of choosing info-focused (vs type-focused) for specific_db payloads."""

from .type_identifier import identify, AttackType, InfoFeature
from .prompt_templates import (
    SECURITY_DECLARATION,
    ATTACK_FORM_MUTATION_TEMPLATE,
    SQL_STRUCTURE_MUTATION_TEMPLATE,
    get_type_dimensions,
    get_info_dimensions,
)
from .memory import MutationMemory
from .validator import validate_mutation, PayloadValidator
from .expected_types_inferrer import ExpectedTypesInferrer


class PayloadMutator:
    """
    Core payload mutation orchestrator.

    Args:
        llm:                   LLM instance with a ``generate()`` method.
        model:                 Model name for LLM mutation calls.
        memory:                Optional shared ``MutationMemory`` instance.
        infer_types:           Whether to infer ``expected_types`` after
                               successful mutation.
        types_inference_model: Override model for the type-inference call.
                               Defaults to *model*.
    """

    def __init__(
        self,
        llm,
        model: str,
        memory: Optional[MutationMemory] = None,
        infer_types: bool = True,
        types_inference_model: Optional[str] = None,
    ):
        self.llm = llm
        self.model = model
        self.memory = memory or MutationMemory()

        self.infer_types = infer_types
        self.types_inferrer: Optional[ExpectedTypesInferrer] = (
            ExpectedTypesInferrer(llm=llm, model=types_inference_model or model)
            if infer_types
            else None
        )

        self._stats = {
            "attempts": 0,
            "success": 0,
            "failed": 0,
            "duplicates": 0,
            "types_inferred": 0,
        }

    # ------------------------------------------------------------------
    # Public mutation API
    # ------------------------------------------------------------------

    def mutate(
        self,
        template: Dict,
        infer_types: Optional[bool] = None,
    ) -> Optional[Dict]:
        """
        Mutate *template* and optionally infer ``expected_types``.

        Args:
            template:     Payload template dict with ``"payload"``, ``"type"``,
                          and ``"information_features"`` keys.
            infer_types:  Override the instance-level ``infer_types`` setting
                          for this call.

        Returns:
            A dict with keys ``payload``, ``expected_types``, ``original``,
            ``attack_type``, ``info_feature``, and ``mutation_type`` on
            success; ``None`` on failure.
        """
        self._stats["attempts"] += 1

        # Step 1 — identify type
        attack_type, info_feature = identify(template)
        attack_type_str = template.get("type", attack_type.value)
        info_feature_str = template.get("information_features", info_feature.value)

        # Step 2 — route to prompt template
        prompt_type = self._decide_prompt_type(attack_type, info_feature)

        # Step 3 — build prompt with memory augmentation
        prompt = self._build_prompt(
            template, attack_type, info_feature,
            attack_type_str, info_feature_str, prompt_type,
        )

        # Step 4 — LLM call
        try:
            response = self.llm.chat(prompt, self.model, temperature=MUTATION_LLM_TEMPERATURE, max_tokens=MUTATION_MAX_TOKENS)
            mutated = response.strip() if response else ""
        except Exception as e:
            self._stats["failed"] += 1
            if self._stats["failed"] <= 3:
                print(
                    f"[PayloadMutator] LLM call failed: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
            return None

        if not mutated:
            self._stats["failed"] += 1
            return None

        # Step 5 — validate
        _validator = PayloadValidator()
        validation = _validator.validate(template, mutated)
        if not validation.is_valid:
            self._stats["failed"] += 1
            return None

        # Clean LLM output to a single, prefix-stripped line
        mutated = _validator.clean(mutated)

        # Step 6 — deduplication
        if self.memory.is_duplicate(mutated):
            self._stats["duplicates"] += 1
            return None

        # Step 7 — record success
        self._stats["success"] += 1
        self.memory.record_success(
            attack_type_str, info_feature_str,
            template["payload"], mutated, prompt_type,
        )

        # Step 8 — infer expected_types (separate task)
        should_infer = infer_types if infer_types is not None else self.infer_types
        expected_types = None
        if should_infer and self.types_inferrer is not None:
            expected_types = self.types_inferrer.infer(
                payload=mutated,
                attack_type=attack_type_str,
                info_features=info_feature_str,
                use_llm=True,
            )
            if expected_types:
                self._stats["types_inferred"] += 1

        return {
            "payload": mutated,
            "expected_types": expected_types,
            "original": template["payload"],
            "attack_type": attack_type_str,
            "info_feature": info_feature_str,
            "mutation_type": prompt_type,
        }

    def mutate_without_types(self, template: Dict) -> Optional[Dict]:
        """
        Mutate *template* without the follow-up ``expected_types`` inference.

        Convenience wrapper around :meth:`mutate`.
        """
        return self.mutate(template, infer_types=False)

    def infer_expected_types(
        self,
        payload: str,
        attack_type: str = "",
        info_features: str = "",
        use_llm: bool = True,
    ) -> Optional[List[str]]:
        """
        Infer ``expected_types`` for an arbitrary payload (not necessarily mutated).

        Args:
            payload:      The SQL injection payload template string.
            attack_type:  Attack type label (e.g. ``"Error base attack"``).
            info_features: Information-feature label.
            use_llm:      Whether to use LLM inference (falls back to heuristics).

        Returns:
            List of type strings, or ``None`` if the payload has no placeholders.
        """
        if self.types_inferrer is None:
            self.types_inferrer = ExpectedTypesInferrer(llm=self.llm, model=self.model)
        return self.types_inferrer.infer(
            payload=payload,
            attack_type=attack_type,
            info_features=info_features,
            use_llm=use_llm,
        )

    # ------------------------------------------------------------------
    # Prompt routing
    # ------------------------------------------------------------------

    def _decide_prompt_type(
        self, attack_type: AttackType, info_feature: InfoFeature
    ) -> str:
        """
        Select ``"type_focused"`` or ``"info_focused"`` prompt routing.

        Strategy:
        - **constant**          → always ``type_focused`` (no placeholders to vary)
        - **specific_database** → 70 % ``type_focused``, 30 % ``info_focused``
          (attack-form diversity is more valuable than structural variation;
          over-weighting ``info_focused`` tends to produce overly complex
          multi-JOIN payloads that hurt generalisation)
        - **system_information** → always ``type_focused``
          (limited structural variation room for ``$sysInfo$`` payloads)
        """
        if info_feature == InfoFeature.CONSTANT:
            return "type_focused"
        if info_feature == InfoFeature.SPECIFIC_DB:
            return "info_focused" if random.random() < INFO_FOCUSED_PROMPT_PROBABILITY else "type_focused"
        # SYSTEM_INFO
        return "type_focused"

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        template: Dict,
        attack_type: AttackType,
        info_feature: InfoFeature,
        attack_type_str: str,
        info_feature_str: str,
        prompt_type: str,
    ) -> str:
        """Assemble the full LLM prompt with memory-augmented few-shot addons."""
        payload = template.get("payload", "")
        memory_addons = self.memory.get_prompt_addons(
            attack_type_str, info_feature_str, prompt_type
        )
        if prompt_type == "type_focused":
            tmpl = ATTACK_FORM_MUTATION_TEMPLATE
            dimensions = get_type_dimensions(attack_type)
        else:
            tmpl = SQL_STRUCTURE_MUTATION_TEMPLATE
            dimensions = get_info_dimensions()

        return tmpl.format(
            security_declaration=SECURITY_DECLARATION,
            attack_type=attack_type_str,
            info_feature=info_feature_str,
            payload=payload,
            dimensions=dimensions,
            memory_addons=memory_addons,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_routing_info(self, template: Dict) -> Dict:
        """Return routing metadata for *template* (for debugging or analysis)."""
        attack_type, info_feature = identify(template)
        prompt_type = self._decide_prompt_type(attack_type, info_feature)
        return {
            "attack_type": template.get("type", attack_type.value),
            "info_feature": template.get("information_features", info_feature.value),
            "prompt_type": prompt_type,
            "reason": self._get_routing_reason(info_feature),
        }

    def _get_routing_reason(self, info_feature: InfoFeature) -> str:
        """Return a human-readable explanation of the routing decision."""
        return {
            InfoFeature.CONSTANT: "No placeholders → type_focused only",
            InfoFeature.SPECIFIC_DB: (
                "Attack-form diversity → prefer type_focused (70 %); info_focused (30 %)"
            ),
            InfoFeature.SYSTEM_INFO: "System queries → type_focused only",
        }.get(info_feature, "default")

    def get_stats(self) -> Dict:
        """Return cumulative mutation and type-inference statistics."""
        stats = {
            "total_attempts": self._stats["attempts"],
            "successful": self._stats["success"],
            "failed": self._stats["failed"],
            "duplicates": self._stats["duplicates"],
            "success_rate": (
                self._stats["success"] / self._stats["attempts"]
                if self._stats["attempts"] > 0
                else 0.0
            ),
            "types_inferred": self._stats["types_inferred"],
        }
        if self.types_inferrer:
            stats["types_inferrer_stats"] = self.types_inferrer.get_stats()
        return stats

    def reset_stats(self) -> None:
        """Reset statistics counters while preserving memory contents."""
        self._stats = {
            "attempts": 0,
            "success": 0,
            "failed": 0,
            "duplicates": 0,
            "types_inferred": 0,
        }
        if self.types_inferrer:
            self.types_inferrer.reset_stats()

    def build_prompt_for_inspection(
        self, template: Dict
    ) -> Tuple[str, str, Dict]:
        """
        Build and return the full prompt together with routing metadata.

        Useful for logging or evaluating the mutation process.

        Returns:
            ``(full_prompt, memory_addons, routing_info)``
        """
        attack_type, info_feature = identify(template)
        attack_type_str = template.get("type", attack_type.value)
        info_feature_str = template.get("information_features", info_feature.value)
        prompt_type = self._decide_prompt_type(attack_type, info_feature)

        memory_addons = self.memory.get_prompt_addons(
            attack_type_str, info_feature_str, prompt_type
        )
        full_prompt = self._build_prompt(
            template, attack_type, info_feature,
            attack_type_str, info_feature_str, prompt_type,
        )
        routing_info = {
            "attack_type": attack_type_str,
            "info_feature": info_feature_str,
            "prompt_type": prompt_type,
            "reason": self._get_routing_reason(info_feature),
        }
        return full_prompt, memory_addons, routing_info
