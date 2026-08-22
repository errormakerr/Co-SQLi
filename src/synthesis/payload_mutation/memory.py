"""Memory for diverse payload-template mutation prompts.

The mutation prompt deliberately does not use a defender error bank.  Instead,
it samples known payload templates in the current mutation category: successful
mutations first, then source templates from the training library when needed.
Examples are anti-imitation context, so they map out explored payload forms
rather than prescribing a direction for the next mutation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


NUM_FEWSHOT_EXAMPLES = 5
"""Maximum number of anti-imitation payload templates shown in one prompt."""

_LEGACY_ORIGINAL_PAYLOAD_KEY = "_legacy_original_payload"


@dataclass
class CategoryMemory:
    """Successful mutated templates and fingerprints for one payload category."""

    attack_type: str
    info_feature: str
    mutated_templates: List[Dict[str, Any]] = field(default_factory=list)
    fingerprints: Set[str] = field(default_factory=set)

    def add_success(self, template: Dict[str, Any]) -> None:
        """Append one successful full payload template without truncating history."""
        snapshot = copy.deepcopy(template)
        self.mutated_templates.append(snapshot)
        self.fingerprints.add(self._get_fingerprint(snapshot["payload"]))

    @staticmethod
    def _get_fingerprint(payload: str) -> str:
        normalized = " ".join(payload.split()).lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()


class MutationMemory:
    """Category-scoped mutation history plus immutable source-template pools.

    ``source_templates`` are raw training-library templates and are never
    persisted because they are reloaded from the repository on each run.  Only
    successful mutations are checkpointed, with all payload-template fields.
    """

    def __init__(
        self,
        source_templates: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> None:
        self.categories: Dict[str, CategoryMemory] = {}
        self.global_fingerprints: Set[str] = set()
        self._source_templates: Dict[str, List[Dict[str, Any]]] = {}
        self._source_fingerprints: Set[str] = set()

        for template in source_templates or []:
            self._add_source_template(template)

    @staticmethod
    def _get_key(attack_type: str, info_feature: str) -> str:
        return f"{attack_type}|{info_feature}"

    @staticmethod
    def _get_fingerprint(payload: str) -> str:
        normalized = " ".join(payload.split()).lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def _add_source_template(self, template: Dict[str, Any]) -> None:
        attack_type = template.get("type")
        info_feature = template.get("information_features")
        payload = template.get("payload")
        if not all(isinstance(value, str) for value in (attack_type, info_feature, payload)):
            raise ValueError("source templates require type, information_features, and payload")

        key = self._get_key(attack_type, info_feature)
        self._source_templates.setdefault(key, []).append(copy.deepcopy(template))
        self._source_fingerprints.add(self._get_fingerprint(payload))

    def get_category(self, attack_type: str, info_feature: str) -> CategoryMemory:
        """Get or create the successful-mutation store for one category."""
        key = self._get_key(attack_type, info_feature)
        if key not in self.categories:
            self.categories[key] = CategoryMemory(attack_type, info_feature)
        return self.categories[key]

    def record_success(self, template: Dict[str, Any]) -> None:
        """Store a successful mutation as a complete payload template."""
        attack_type = template.get("type")
        info_feature = template.get("information_features")
        payload = template.get("payload")
        if not all(isinstance(value, str) for value in (attack_type, info_feature, payload)):
            raise ValueError("successful templates require type, information_features, and payload")

        category = self.get_category(attack_type, info_feature)
        category.add_success(template)
        self.global_fingerprints.add(self._get_fingerprint(payload))

    def is_duplicate(
        self,
        payload: str,
        attack_type: Optional[str] = None,
        info_feature: Optional[str] = None,
    ) -> bool:
        """Return whether a candidate duplicates a source or successful mutation."""
        del attack_type, info_feature
        fingerprint = self._get_fingerprint(payload)
        return (
            fingerprint in self._source_fingerprints
            or fingerprint in self.global_fingerprints
        )

    def add_fingerprint(self, payload: str) -> None:
        """Register a payload fingerprint without creating a success record."""
        self.global_fingerprints.add(self._get_fingerprint(payload))

    def get_fewshot_templates(
        self,
        attack_type: str,
        info_feature: str,
    ) -> List[Dict[str, Any]]:
        """Sample up to five templates, prioritizing successful mutations.

        The result contains complete template dictionaries.  If fewer than five
        successful mutations are available, the remaining slots are filled from
        the original training-library templates for the same category.
        """
        key = self._get_key(attack_type, info_feature)
        category = self.categories.get(key)
        mutated = category.mutated_templates if category is not None else []
        selected_mutated = random.sample(
            mutated,
            k=min(NUM_FEWSHOT_EXAMPLES, len(mutated)),
        )

        remaining = NUM_FEWSHOT_EXAMPLES - len(selected_mutated)
        source = self._source_templates.get(key, [])
        selected_source = random.sample(source, k=min(remaining, len(source)))
        return [
            copy.deepcopy(template)
            for template in selected_mutated + selected_source
        ]

    def _get_fewshot_entries(
        self,
        attack_type: str,
        info_feature: str,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Return sampled templates with their source labels for prompt rendering."""
        key = self._get_key(attack_type, info_feature)
        category = self.categories.get(key)
        mutated = category.mutated_templates if category is not None else []
        selected_mutated = random.sample(
            mutated,
            k=min(NUM_FEWSHOT_EXAMPLES, len(mutated)),
        )
        remaining = NUM_FEWSHOT_EXAMPLES - len(selected_mutated)
        source = self._source_templates.get(key, [])
        selected_source = random.sample(source, k=min(remaining, len(source)))
        return [
            ("successful mutation", copy.deepcopy(template))
            for template in selected_mutated
        ] + [
            ("original training library", copy.deepcopy(template))
            for template in selected_source
        ]

    def get_prompt_addons(
        self,
        attack_type: str,
        info_feature: str,
    ) -> str:
        """Render category-local anti-imitation few-shot context."""
        entries = self._get_fewshot_entries(attack_type, info_feature)
        if not entries:
            return ""

        lines = [
            "## Existing Payload Templates",
            "",
            "The following valid templates show payload forms already present in the training library or produced by prior successful mutations.",
            "Use them only to understand valid template structure and the space that has already been explored.",
            "Do NOT copy, lightly edit, or closely imitate any example. Choose a meaningfully different mutation form.",
            "",
        ]
        for index, (source, template) in enumerate(entries, start=1):
            lines.append(f"Example {index} ({source}):")
            lines.append(f"  {json.dumps(template, ensure_ascii=False, sort_keys=True)}")
            lines.append("")
        lines.append("Your mutation must be meaningfully different from every example above.")
        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Return source and successful-mutation memory statistics."""
        successful_templates = sum(
            len(category.mutated_templates)
            for category in self.categories.values()
        )
        source_templates = sum(
            len(templates)
            for templates in self._source_templates.values()
        )
        return {
            "categories_count": len(self.categories),
            "global_fingerprints": len(self.global_fingerprints),
            "source_templates": source_templates,
            "successful_mutated_templates": successful_templates,
            "total_examples": successful_templates,
            "category_details": {
                key: {
                    "mutated_templates": len(category.mutated_templates),
                    "fingerprints": len(category.fingerprints),
                }
                for key, category in self.categories.items()
            },
        }

    def save(self, path: str) -> None:
        """Persist all successful full templates for breakpoint recovery."""
        data = {
            "format_version": 2,
            "global_fingerprints": sorted(self.global_fingerprints),
            "categories": {
                key: {
                    "attack_type": category.attack_type,
                    "info_feature": category.info_feature,
                    "mutated_templates": category.mutated_templates,
                    "fingerprints": sorted(category.fingerprints),
                }
                for key, category in self.categories.items()
            },
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "MutationMemory":
        """Load v2 checkpoints and upgrade legacy string-only entries lazily."""
        memory = cls()
        checkpoint = Path(path)
        if not checkpoint.exists():
            return memory

        with open(checkpoint, "r", encoding="utf-8") as file:
            data = json.load(file)

        memory.global_fingerprints = set(data.get("global_fingerprints", []))
        for key, category_data in data.get("categories", {}).items():
            category = CategoryMemory(
                attack_type=category_data["attack_type"],
                info_feature=category_data["info_feature"],
            )
            templates = category_data.get("mutated_templates")
            if templates is None:
                templates = [
                    {
                        "payload": example["mutated"],
                        _LEGACY_ORIGINAL_PAYLOAD_KEY: example["original"],
                    }
                    for example in (
                        category_data.get("type_focused_examples", [])
                        + category_data.get("info_focused_examples", [])
                    )
                ]
            category.mutated_templates = copy.deepcopy(templates)
            category.fingerprints = set(category_data.get("fingerprints", []))
            memory.categories[key] = category
        return memory

    def restore_mutations_from(self, checkpoint: "MutationMemory") -> None:
        """Restore checkpointed successes while retaining local source templates.

        Legacy checkpoint entries only contain strings.  When their source
        template remains in the local training library, this upgrades them to a
        complete template before retaining them.
        """
        self.categories.clear()
        self.global_fingerprints = set(checkpoint.global_fingerprints)

        for key, previous in checkpoint.categories.items():
            category = CategoryMemory(previous.attack_type, previous.info_feature)
            category.fingerprints = set(previous.fingerprints)
            category.mutated_templates = [
                self._upgrade_legacy_template(template, previous.attack_type, previous.info_feature)
                for template in previous.mutated_templates
            ]
            for template in category.mutated_templates:
                self.global_fingerprints.add(self._get_fingerprint(template["payload"]))
                category.fingerprints.add(self._get_fingerprint(template["payload"]))
            self.categories[key] = category

    def _upgrade_legacy_template(
        self,
        template: Dict[str, Any],
        attack_type: str,
        info_feature: str,
    ) -> Dict[str, Any]:
        """Expand an old string-only success entry from its known source template."""
        snapshot = copy.deepcopy(template)
        original_payload = snapshot.pop(_LEGACY_ORIGINAL_PAYLOAD_KEY, None)
        if original_payload is None:
            return snapshot

        key = self._get_key(attack_type, info_feature)
        for source_template in self._source_templates.get(key, []):
            if source_template.get("payload") == original_payload:
                upgraded = copy.deepcopy(source_template)
                upgraded["payload"] = snapshot["payload"]
                return upgraded
        return snapshot

    def clear(self) -> None:
        """Clear successful mutations while retaining static source templates."""
        self.categories.clear()
        self.global_fingerprints.clear()
