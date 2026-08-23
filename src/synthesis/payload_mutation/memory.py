"""Versioned mutation memory for canonical, comment-free payload templates."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

from utils.cluster import PayloadCategoryKey, TAXONOMY_VERSION


NUM_FEWSHOT_EXAMPLES = 5
MUTATION_MEMORY_FORMAT_VERSION = 3


def _fingerprint(payload: str) -> str:
    normalized = " ".join(payload.split()).lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _require_core_template(template: Dict[str, Any], context: str) -> Tuple[str, str, str]:
    technique = template.get("technique")
    reference_scope = template.get("reference_scope")
    payload = template.get("payload")
    if not all(isinstance(value, str) for value in (technique, reference_scope, payload)):
        raise ValueError(
            f"{context} requires technique, reference_scope, and payload strings"
        )
    PayloadCategoryKey(technique, reference_scope)
    if "--" in payload or "#" in payload:
        raise ValueError(f"{context} must contain a comment-free payload core")
    return technique, reference_scope, payload


@dataclass
class CategoryMemory:
    """Successful full payload templates for one payload category."""

    technique: str
    reference_scope: str
    mutated_templates: List[Dict[str, Any]] = field(default_factory=list)
    fingerprints: Set[str] = field(default_factory=set)

    def add_success(self, template: Dict[str, Any]) -> None:
        snapshot = copy.deepcopy(template)
        self.mutated_templates.append(snapshot)
        self.fingerprints.add(_fingerprint(snapshot["payload"]))


class MutationMemory:
    """Category-scoped successes plus immutable source-template pools."""

    def __init__(self, source_templates: Iterable[Dict[str, Any]] | None = None) -> None:
        self.categories: Dict[str, CategoryMemory] = {}
        self.global_fingerprints: Set[str] = set()
        self._source_templates: Dict[str, List[Dict[str, Any]]] = {}
        self._source_fingerprints: Set[str] = set()
        for template in source_templates or []:
            self._add_source_template(template)

    @staticmethod
    def _get_key(technique: str, reference_scope: str) -> str:
        return str(PayloadCategoryKey(technique, reference_scope))

    def _add_source_template(self, template: Dict[str, Any]) -> None:
        technique, reference_scope, payload = _require_core_template(template, "source template")
        key = self._get_key(technique, reference_scope)
        self._source_templates.setdefault(key, []).append(copy.deepcopy(template))
        self._source_fingerprints.add(_fingerprint(payload))

    def get_category(self, technique: str, reference_scope: str) -> CategoryMemory:
        key = self._get_key(technique, reference_scope)
        if key not in self.categories:
            self.categories[key] = CategoryMemory(technique, reference_scope)
        return self.categories[key]

    def record_success(self, template: Dict[str, Any]) -> None:
        technique, reference_scope, payload = _require_core_template(
            template, "successful template"
        )
        self.get_category(technique, reference_scope).add_success(template)
        self.global_fingerprints.add(_fingerprint(payload))

    def is_duplicate(self, payload: str) -> bool:
        fingerprint = _fingerprint(payload)
        return fingerprint in self._source_fingerprints or fingerprint in self.global_fingerprints

    def get_fewshot_templates(
        self, technique: str, reference_scope: str
    ) -> List[Dict[str, Any]]:
        return [template for _, template in self._get_fewshot_entries(technique, reference_scope)]

    def _get_fewshot_entries(
        self, technique: str, reference_scope: str
    ) -> List[Tuple[str, Dict[str, Any]]]:
        key = self._get_key(technique, reference_scope)
        category = self.categories.get(key)
        mutated = category.mutated_templates if category else []
        selected_mutated = random.sample(mutated, k=min(NUM_FEWSHOT_EXAMPLES, len(mutated)))
        remainder = NUM_FEWSHOT_EXAMPLES - len(selected_mutated)
        source = self._source_templates.get(key, [])
        selected_source = random.sample(source, k=min(remainder, len(source)))
        return [
            ("successful mutation", copy.deepcopy(template)) for template in selected_mutated
        ] + [
            ("original training library", copy.deepcopy(template)) for template in selected_source
        ]

    def get_prompt_addons(self, technique: str, reference_scope: str) -> str:
        entries = self._get_fewshot_entries(technique, reference_scope)
        if not entries:
            return ""
        lines = [
            "### Previously Explored Payload Cores",
            "",
            "These are anti-imitation few-shot examples for the same technique and reference scope.",
            "They identify forms already explored, not patterns to reproduce or combine.",
            "Keep the taxonomy fixed, avoid copying or lightly editing any example, and do not introduce SQL line-comment delimiters (``--`` or ``#``).",
            "",
        ]
        for index, (source, template) in enumerate(entries, start=1):
            lines.extend((
                f"Example {index} ({source}):",
                f"  {json.dumps(template, ensure_ascii=False, sort_keys=True)}",
                "",
            ))
        lines.append("Produce a meaningfully different payload core.")
        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        successful_templates = sum(len(category.mutated_templates) for category in self.categories.values())
        source_templates = sum(len(templates) for templates in self._source_templates.values())
        return {
            "categories_count": len(self.categories),
            "global_fingerprints": len(self.global_fingerprints),
            "source_templates": source_templates,
            "successful_mutated_templates": successful_templates,
            "category_details": {
                key: {
                    "mutated_templates": len(category.mutated_templates),
                    "fingerprints": len(category.fingerprints),
                }
                for key, category in self.categories.items()
            },
        }

    def save(self, path: str) -> None:
        data = {
            "format_version": MUTATION_MEMORY_FORMAT_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "global_fingerprints": sorted(self.global_fingerprints),
            "categories": {
                key: {
                    "technique": category.technique,
                    "reference_scope": category.reference_scope,
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
        checkpoint = Path(path)
        if not checkpoint.exists():
            return cls()
        with checkpoint.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if data.get("format_version") != MUTATION_MEMORY_FORMAT_VERSION or data.get("taxonomy_version") != TAXONOMY_VERSION:
            raise ValueError(
                "Mutation memory taxonomy mismatch; start a new taxonomy-v3 run "
                "instead of restoring this checkpoint."
            )

        memory = cls()
        memory.global_fingerprints = set(data.get("global_fingerprints", []))
        for category_data in data.get("categories", {}).values():
            category = memory.get_category(
                category_data["technique"], category_data["reference_scope"]
            )
            for template in category_data.get("mutated_templates", []):
                _require_core_template(template, "checkpoint template")
                category.add_success(template)
                memory.global_fingerprints.add(_fingerprint(template["payload"]))
            category.fingerprints.update(category_data.get("fingerprints", []))
        return memory

    def restore_mutations_from(self, checkpoint: "MutationMemory") -> None:
        self.categories = copy.deepcopy(checkpoint.categories)
        self.global_fingerprints = set(checkpoint.global_fingerprints)

    def clear(self) -> None:
        self.categories.clear()
        self.global_fingerprints.clear()
