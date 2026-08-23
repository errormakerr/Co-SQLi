"""Canonical SQL-injection taxonomy and cluster helpers.

Attack samples are classified by exactly three dimensions:

``(technique, reference_scope, comment_state)``.

The MAB arm set is declared here, rather than inferred from a benchmark file.
This prevents an incomplete dataset from silently removing attack arms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


TAXONOMY_VERSION = 3
"""Version of the persisted taxonomy and cluster-key contract."""

NORMAL_CLUSTER_KEY = "benign"
"""Fixed key used only for benign / normal SQL examples."""

TECHNIQUES: Tuple[str, ...] = (
    "tautology",
    "union_query",
    "piggy_backed",
    "error_based",
    "boolean_blind",
    "time_blind",
)

REFERENCE_SCOPES: Tuple[str, ...] = ("lor", "tsr", "scr")
COMMENT_STATES: Tuple[str, ...] = ("no_comment", "clean_comment", "cepp")

# The two omitted combinations follow the paper's semantic pruning rules:
# boolean-blind/LOR collapses to tautology and piggy-backed/LOR has no
# meaningful exploit effect.
_PRUNED_PAYLOAD_CATEGORIES = frozenset({
    ("boolean_blind", "lor"),
    ("piggy_backed", "lor"),
})

VALID_PAYLOAD_CATEGORIES: Tuple[Tuple[str, str], ...] = tuple(
    (technique, reference_scope)
    for technique in TECHNIQUES
    for reference_scope in REFERENCE_SCOPES
    if (technique, reference_scope) not in _PRUNED_PAYLOAD_CATEGORIES
)


def is_valid_payload_category(technique: str, reference_scope: str) -> bool:
    """Return whether a technique/scope pair is a valid payload category."""
    return (technique, reference_scope) in VALID_PAYLOAD_CATEGORIES


@dataclass(frozen=True)
class PayloadCategoryKey:
    """Technique/scope key for payload templates and mutation memory."""

    technique: str
    reference_scope: str

    def __post_init__(self) -> None:
        if not is_valid_payload_category(self.technique, self.reference_scope):
            raise ValueError(
                "Invalid payload category "
                f"({self.technique!r}, {self.reference_scope!r})"
            )

    @classmethod
    def from_str(cls, value: str) -> "PayloadCategoryKey":
        parts = value.split("||")
        if len(parts) != 2:
            raise ValueError(
                f"PayloadCategoryKey requires technique||reference_scope, got {value!r}"
            )
        return cls(*parts)

    def __str__(self) -> str:
        return f"{self.technique}||{self.reference_scope}"


@dataclass(frozen=True)
class ClusterKey:
    """Three-part MAB cluster identity for an attack sample."""

    technique: str
    reference_scope: str
    comment_state: str

    def __post_init__(self) -> None:
        PayloadCategoryKey(self.technique, self.reference_scope)
        if self.comment_state not in COMMENT_STATES:
            raise ValueError(
                f"Invalid comment_state {self.comment_state!r}; "
                f"expected one of {COMMENT_STATES}"
            )

    @classmethod
    def from_str(cls, value: str) -> "ClusterKey":
        parts = value.split("||")
        if len(parts) != 3:
            raise ValueError(
                "ClusterKey requires technique||reference_scope||comment_state, "
                f"got {value!r}"
            )
        return cls(*parts)

    def payload_category_key(self) -> PayloadCategoryKey:
        """Return the mutation/template category that underlies this MAB arm."""
        return PayloadCategoryKey(self.technique, self.reference_scope)

    def __str__(self) -> str:
        return f"{self.technique}||{self.reference_scope}||{self.comment_state}"


def all_attack_cluster_keys() -> List[str]:
    """Return all 48 legal MAB attack arms in stable canonical order."""
    return [
        str(ClusterKey(technique, reference_scope, comment_state))
        for technique, reference_scope in VALID_PAYLOAD_CATEGORIES
        for comment_state in COMMENT_STATES
    ]


def get_injection_cluster_keys(cluster_keys: Iterable[str]) -> List[str]:
    """Return attack keys from an ordered collection, excluding benign samples."""
    return [key for key in cluster_keys if key != NORMAL_CLUSTER_KEY]


def get_single_key_of_payload_template(data_item: Dict[str, Any]) -> str:
    """Return the two-part category key for a canonical payload template."""
    return str(
        PayloadCategoryKey(
            data_item["technique"],
            data_item["reference_scope"],
        )
    )


def cluster_payload_templates(
    datas: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group payload templates by their technique/scope category."""
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for item in datas:
        clusters.setdefault(get_single_key_of_payload_template(item), []).append(item)
    return clusters


def get_single_key_of_injection_sql(data_item: Dict[str, Any]) -> str:
    """Return the taxonomy key for one generated or inferred sample."""
    if data_item["label"]:
        return NORMAL_CLUSTER_KEY
    return str(
        ClusterKey(
            data_item["technique"],
            data_item["reference_scope"],
            data_item["comment_state"],
        )
    )


def cluster_injection_sqls(
    datas: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group generated injection SQL records by canonical cluster identity."""
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for item in datas:
        clusters.setdefault(get_single_key_of_injection_sql(item), []).append(item)
    return clusters
