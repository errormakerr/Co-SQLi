"""
Mutation Memory Module

Key Design: Maintain separate memory for each of 18 categories
(6 attack types × 3 info features)

Features:
1. Deduplication: Prevent generating duplicate payloads
2. Few-shot: Record successful examples (as format reference, NOT for imitation)
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Set
from dataclasses import dataclass, field


@dataclass
class CategoryMemory:
    """
    Memory for a single category (attack_type + info_feature combination)
    
    Each of 18 categories maintains its own:
    - Successful examples (by prompt type)
    - Payload fingerprints (for deduplication)
    """
    attack_type: str
    info_feature: str
    
    # Successful examples by prompt_type
    type_focused_examples: List[Dict] = field(default_factory=list)
    info_focused_examples: List[Dict] = field(default_factory=list)
    
    # Fingerprints for deduplication
    fingerprints: Set[str] = field(default_factory=set)
    
    def add_success(self, original: str, mutated: str, prompt_type: str, max_examples: int = 5):
        """Record a successful mutation."""
        examples = self.type_focused_examples if prompt_type == "type_focused" else self.info_focused_examples
        
        # Remove oldest if at limit
        if len(examples) >= max_examples:
            examples.pop(0)
        
        examples.append({"original": original, "mutated": mutated})
        self.fingerprints.add(self._get_fingerprint(mutated))
    
    def is_duplicate(self, payload: str) -> bool:
        """Check if payload already exists."""
        return self._get_fingerprint(payload) in self.fingerprints
    
    def add_fingerprint(self, payload: str):
        """Add payload fingerprint."""
        self.fingerprints.add(self._get_fingerprint(payload))
    
    def get_prompt_addons(self, prompt_type: str) -> str:
        """Get memory-enhanced prompt additions."""
        parts = []
        
        # Few-shot examples (emphasize NOT to imitate)
        examples = self.type_focused_examples if prompt_type == "type_focused" else self.info_focused_examples
        if examples:
            parts.append(self._format_fewshot(examples))
        
        return "\n\n".join(parts)
    
    def _format_fewshot(self, examples: List[Dict]) -> str:
        """Format few-shot examples with guidance on their purpose."""
        lines = [
            "## Past Successful Mutations",
            "",
            "The following are examples of mutations that were previously accepted as valid.",
            "These examples serve two purposes:",
            "1. **Success criteria reference**: They demonstrate what kind of mutations meet the requirements - the output format, placeholder preservation, and structural validity.",
            "2. **Diversity guidance**: Since these have already been generated, you MUST explore DIFFERENT mutation dimensions. Do NOT produce outputs that are identical or highly similar to these examples.",
            "",
            "**Important**: Use these as a reference for understanding valid output format, but choose a DIFFERENT mutation approach from what you see below.",
            ""
        ]
        for i, ex in enumerate(examples[-2:], 1):  # Only show last 2
            lines.append(f"Example {i}:")
            lines.append(f"  Original: {ex['original']}")
            lines.append(f"  Mutated:  {ex['mutated']}")
            lines.append("")
        lines.append("Your mutation MUST be meaningfully different from the above examples. Explore other dimensions described in the Mutation Guidance section.")
        return "\n".join(lines)
    
    def _get_fingerprint(self, payload: str) -> str:
        """Generate payload fingerprint."""
        normalized = " ".join(payload.split()).lower()
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()


class MutationMemory:
    """
    Main Memory Module
    
    Maintains 18 separate CategoryMemory instances:
    - 6 attack types × 3 info features
    """
    
    def __init__(self):
        self.categories: Dict[str, CategoryMemory] = {}
        
        # Global fingerprints (cross-category deduplication)
        self.global_fingerprints: Set[str] = set()
    
    def _get_key(self, attack_type: str, info_feature: str) -> str:
        """Generate category key."""
        return f"{attack_type}|{info_feature}"
    
    def get_category(self, attack_type: str, info_feature: str) -> CategoryMemory:
        """Get or create CategoryMemory for the specified category."""
        key = self._get_key(attack_type, info_feature)
        if key not in self.categories:
            self.categories[key] = CategoryMemory(attack_type, info_feature)
        return self.categories[key]
    
    def record_success(
        self,
        attack_type: str,
        info_feature: str,
        original: str,
        mutated: str,
        prompt_type: str
    ):
        """Record a successful mutation."""
        category = self.get_category(attack_type, info_feature)
        category.add_success(original, mutated, prompt_type)
        
        # Also add to global fingerprints
        fp = category._get_fingerprint(mutated)
        self.global_fingerprints.add(fp)
    
    def is_duplicate(self, payload: str, attack_type: str = None, info_feature: str = None) -> bool:
        """
        Check if payload is duplicate.
        
        Uses global fingerprints for cross-category deduplication.
        """
        normalized = " ".join(payload.split()).lower()
        fp = hashlib.md5(normalized.encode('utf-8')).hexdigest()
        return fp in self.global_fingerprints
    
    def add_fingerprint(self, payload: str):
        """Add payload to global fingerprints."""
        normalized = " ".join(payload.split()).lower()
        fp = hashlib.md5(normalized.encode('utf-8')).hexdigest()
        self.global_fingerprints.add(fp)
    
    def get_prompt_addons(self, attack_type: str, info_feature: str, prompt_type: str) -> str:
        """Get memory-enhanced prompt additions for the specified category."""
        category = self.get_category(attack_type, info_feature)
        return category.get_prompt_addons(prompt_type)
    
    def get_stats(self) -> Dict:
        """Get memory statistics."""
        total_examples = sum(
            len(c.type_focused_examples) + len(c.info_focused_examples)
            for c in self.categories.values()
        )
        
        return {
            "categories_count": len(self.categories),
            "global_fingerprints": len(self.global_fingerprints),
            "total_examples": total_examples,
            "category_details": {
                key: {
                    "type_focused_examples": len(c.type_focused_examples),
                    "info_focused_examples": len(c.info_focused_examples),
                    "fingerprints": len(c.fingerprints)
                }
                for key, c in self.categories.items()
            }
        }
    
    def save(self, path: str) -> None:
        """
        Serialize memory state to a JSON file.
        Call this at the end of each training round so breakpoint recovery
        can restore the full mutation history.
        """
        data = {
            "global_fingerprints": list(self.global_fingerprints),
            "categories": {}
        }
        for key, cat in self.categories.items():
            data["categories"][key] = {
                "attack_type": cat.attack_type,
                "info_feature": cat.info_feature,
                "type_focused_examples": cat.type_focused_examples,
                "info_focused_examples": cat.info_focused_examples,
                "fingerprints": list(cat.fingerprints),
            }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "MutationMemory":
        """
        Deserialize memory state from a JSON file saved by ``save()``.
        Returns an empty MutationMemory if the file does not exist.
        """
        memory = cls()
        p = Path(path)
        if not p.exists():
            return memory
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        memory.global_fingerprints = set(data.get("global_fingerprints", []))
        for key, cat_data in data.get("categories", {}).items():
            cat = CategoryMemory(
                attack_type=cat_data["attack_type"],
                info_feature=cat_data["info_feature"],
            )
            cat.type_focused_examples = cat_data.get("type_focused_examples", [])
            cat.info_focused_examples = cat_data.get("info_focused_examples", [])
            cat.fingerprints = set(cat_data.get("fingerprints", []))
            memory.categories[key] = cat
        return memory

    def clear(self):
        """Clear all memory."""
        self.categories.clear()
        self.global_fingerprints.clear()
