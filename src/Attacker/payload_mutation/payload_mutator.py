"""
Payload Mutator - Core Orchestrator

Integrates:
- Type identification
- Prompt routing (Type-Focused vs Info-Focused)
- Memory module (18 categories)
- LLM mutation
- Validation
- Expected types inference (separate task)
"""

import random
import sys
from typing import Dict, Optional, Tuple, List

from .type_identifier import identify, AttackType, InfoFeature
from .prompt_templates import (
    SECURITY_DECLARATION,
    TYPE_FOCUSED_TEMPLATE,
    INFO_FOCUSED_TEMPLATE,
    get_type_dimensions,
    get_info_dimensions
)
from .memory import MutationMemory
from .validator import validate_mutation, PayloadValidator
from .expected_types_inferrer import ExpectedTypesInferrer


class PayloadMutator:
    """
    Core payload mutation orchestrator.
    
    Workflow:
    1. Identify payload type (attack_type, info_feature)
    2. Route to appropriate prompt template
    3. Enhance prompt with category-specific memory
    4. Call LLM for mutation
    5. Validate result and update memory
    6. Infer expected_types for the mutated payload (separate task)
    """
    
    def __init__(
        self, 
        llm, 
        model: str, 
        memory: MutationMemory = None,
        infer_types: bool = True,
        types_inference_model: str = None
    ):
        """
        Initialize mutator.
        
        Args:
            llm: LLM instance with generate() method
            model: Model name for LLM mutation calls
            memory: Optional shared memory instance
            infer_types: Whether to infer expected_types after mutation
            types_inference_model: Model for types inference (defaults to same as mutation model)
        """
        self.llm = llm
        self.model = model
        self.memory = memory or MutationMemory()
        
        # Types inference
        self.infer_types = infer_types
        self.types_inferrer = ExpectedTypesInferrer(
            llm=llm,
            model=types_inference_model or model
        ) if infer_types else None
        
        # Statistics
        self._stats = {
            "attempts": 0, 
            "success": 0, 
            "failed": 0, 
            "duplicates": 0,
            "types_inferred": 0
        }
    
    def mutate(
        self, 
        template: Dict,
        infer_types: bool = None
    ) -> Optional[Dict]:
        """
        Mutate a payload template.
        
        Args:
            template: Payload template dict with 'payload', 'type', 'information_features'
            infer_types: Override instance setting for types inference
        
        Returns:
            Dict with mutation result including expected_types, or None if failed
        """
        self._stats["attempts"] += 1
        
        # 1. Identify payload type
        attack_type, info_feature = identify(template)
        attack_type_str = template.get("type", attack_type.value)
        info_feature_str = template.get("information_features", info_feature.value)
        
        # 2. Decide prompt type (type_focused or info_focused)
        prompt_type = self._decide_prompt_type(attack_type, info_feature)
        
        # 3. Build prompt with memory enhancement
        prompt = self._build_prompt(
            template, attack_type, info_feature, 
            attack_type_str, info_feature_str, prompt_type
        )
        
        # 4. Call LLM for mutation
        try:
            # Check if base_url is HKUST to decide which method to use
            use_hkust = "hkust" in self.llm.base_url.lower() if hasattr(self.llm, 'base_url') and self.llm.base_url else False
            
            if use_hkust:
                response = self.llm.generate_by_hkust(prompt, self.model, temperature=0.7, max_tokens=2000)
            else:
                response = self.llm.generate(prompt, self.model, temperature=0.7, max_tokens=2000)
            
            mutated = response.strip() if response else ""
        except Exception as e:
            self._stats["failed"] += 1
            # Only print first few errors to avoid spam
            if self._stats["failed"] <= 3:
                print(f"[DEBUG] LLM mutation call failed: {type(e).__name__}: {e}", file=sys.stderr)
            return None
        
        if not mutated:
            self._stats["failed"] += 1
            if self._stats["failed"] <= 3:
                print(f"[DEBUG] LLM returned empty response. Original response: {repr(response)}", file=sys.stderr)
            return None
        
        # 5. Validate mutation result
        _validator = PayloadValidator()
        validation = _validator.validate(template, mutated)
        
        if not validation.is_valid:
            self._stats["failed"] += 1
            return None
        
        # 清理 LLM 原始输出，得到单行、去除前缀的最终 payload
        mutated = _validator.clean(mutated)
        
        # 6. Check duplicate
        if self.memory.is_duplicate(mutated):
            self._stats["duplicates"] += 1
            return None
        
        # 7. Record success
        self._stats["success"] += 1
        self.memory.record_success(
            attack_type_str, info_feature_str,
            template["payload"], mutated, prompt_type
        )
        
        # 8. Infer expected_types (separate task)
        should_infer = infer_types if infer_types is not None else self.infer_types
        expected_types = None
        
        if should_infer and self.types_inferrer is not None:
            expected_types = self.types_inferrer.infer(
                payload=mutated,
                attack_type=attack_type_str,
                info_features=info_feature_str,
                use_llm=True
            )
            if expected_types:
                self._stats["types_inferred"] += 1
        
        return {
            "payload": mutated,
            "expected_types": expected_types,
            "original": template["payload"],
            "attack_type": attack_type_str,
            "info_feature": info_feature_str,
            "mutation_type": prompt_type
        }
    
    def mutate_without_types(self, template: Dict) -> Optional[Dict]:
        """
        Mutate a payload template without inferring expected_types.
        
        Convenience method that skips the types inference step.
        """
        return self.mutate(template, infer_types=False)
    
    def infer_expected_types(
        self, 
        payload: str,
        attack_type: str = "",
        info_features: str = "",
        use_llm: bool = True
    ) -> Optional[List[str]]:
        """
        Standalone method to infer expected_types for a payload.
        
        Useful when you want to infer types for payloads that weren't mutated.
        
        Args:
            payload: The SQL injection payload template
            attack_type: Attack type (e.g., "Error base attack")
            info_features: Information features (e.g., "system information")
            use_llm: Whether to use LLM for inference
        
        Returns:
            List of expected_types, or None if payload has no placeholders
        """
        if self.types_inferrer is None:
            self.types_inferrer = ExpectedTypesInferrer(
                llm=self.llm,
                model=self.model
            )
        
        return self.types_inferrer.infer(
            payload=payload,
            attack_type=attack_type,
            info_features=info_features,
            use_llm=use_llm
        )
    
    def _decide_prompt_type(self, attack_type: AttackType, info_feature: InfoFeature) -> str:
        """
        Decide whether to use type_focused or info_focused prompt.
        
        Strategy:
        - constant: Always type_focused (no placeholders to change)
        - specific_database: 30% info_focused, 70% type_focused
          (Attack-form diversity is more valuable than structural complexity;
           over-weighting info_focused produces overly complex multi-JOIN payloads
           that degrade training quality)
        - system_information: Always type_focused
          (sysInfo payloads have limited structural variation room)
        """
        if info_feature == InfoFeature.CONSTANT:
            return "type_focused"
        elif info_feature == InfoFeature.SPECIFIC_DB:
            return "info_focused" if random.random() < 0.3 else "type_focused"
        else:  # SYSTEM_INFO
            return "type_focused"
    
    def _build_prompt(
        self,
        template: Dict,
        attack_type: AttackType,
        info_feature: InfoFeature,
        attack_type_str: str,
        info_feature_str: str,
        prompt_type: str
    ) -> str:
        """Build the complete prompt for LLM mutation."""
        payload = template.get("payload", "")
        
        # Get memory addons for this specific category
        memory_addons = self.memory.get_prompt_addons(
            attack_type_str, info_feature_str, prompt_type
        )
        
        # Select template and dimensions
        if prompt_type == "type_focused":
            tmpl = TYPE_FOCUSED_TEMPLATE
            dimensions = get_type_dimensions(attack_type)
        else:
            tmpl = INFO_FOCUSED_TEMPLATE
            dimensions = get_info_dimensions()
        
        return tmpl.format(
            security_declaration=SECURITY_DECLARATION,
            attack_type=attack_type_str,
            info_feature=info_feature_str,
            payload=payload,
            dimensions=dimensions,
            memory_addons=memory_addons
        )
    
    def get_routing_info(self, template: Dict) -> Dict:
        """Get routing information for a template (for debugging/analysis)."""
        attack_type, info_feature = identify(template)
        prompt_type = self._decide_prompt_type(attack_type, info_feature)
        
        return {
            "attack_type": template.get("type", attack_type.value),
            "info_feature": template.get("information_features", info_feature.value),
            "prompt_type": prompt_type,
            "reason": self._get_routing_reason(info_feature)
        }
    
    def _get_routing_reason(self, info_feature: InfoFeature) -> str:
        """Get human-readable routing reason."""
        reasons = {
            InfoFeature.CONSTANT: "No placeholders → type_focused only",
            InfoFeature.SPECIFIC_DB: "Attack-form diversity → prefer type_focused (70%); info_focused (30%)",
            InfoFeature.SYSTEM_INFO: "System queries → type_focused only"
        }
        return reasons.get(info_feature, "default")
    
    def get_stats(self) -> Dict:
        """Get mutation statistics."""
        stats = {
            "total_attempts": self._stats["attempts"],
            "successful": self._stats["success"],
            "failed": self._stats["failed"],
            "duplicates": self._stats["duplicates"],
            "success_rate": self._stats["success"] / self._stats["attempts"] if self._stats["attempts"] > 0 else 0,
            "types_inferred": self._stats["types_inferred"]
        }
        
        # Add types inferrer stats if available
        if self.types_inferrer:
            stats["types_inferrer_stats"] = self.types_inferrer.get_stats()
        
        return stats
    
    def reset_stats(self):
        """Reset statistics (keep memory)."""
        self._stats = {
            "attempts": 0, 
            "success": 0, 
            "failed": 0, 
            "duplicates": 0,
            "types_inferred": 0
        }
        if self.types_inferrer:
            self.types_inferrer.reset_stats()
    
    def build_prompt_for_inspection(self, template: Dict) -> Tuple[str, str, Dict]:
        """
        Build prompt and return full text, memory addons, and routing info.
        
        Used for detailed evaluation recording.
        
        Args:
            template: Payload template dict
        
        Returns:
            (full_prompt, memory_addons, routing_info)
        """
        attack_type, info_feature = identify(template)
        attack_type_str = template.get("type", attack_type.value)
        info_feature_str = template.get("information_features", info_feature.value)
        prompt_type = self._decide_prompt_type(attack_type, info_feature)
        
        # Get memory addons
        memory_addons = self.memory.get_prompt_addons(
            attack_type_str, info_feature_str, prompt_type
        )
        
        # Build full prompt
        full_prompt = self._build_prompt(
            template, attack_type, info_feature,
            attack_type_str, info_feature_str, prompt_type
        )
        
        # Routing info
        routing_info = {
            "attack_type": attack_type_str,
            "info_feature": info_feature_str,
            "prompt_type": prompt_type,
            "reason": self._get_routing_reason(info_feature)
        }
        
        return full_prompt, memory_addons, routing_info
