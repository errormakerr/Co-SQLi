"""
Cluster utilities for grouping and keying SQL injection samples.

Provides helper functions to cluster raw payloads and generated injection
SQL examples by their attack-type / information-feature / annotator / comment
combination, as well as a frozen dataclass for structured cluster keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Boolean helper
# ---------------------------------------------------------------------------

def str_to_bool(s: str) -> bool:
    """Convert a case-insensitive ``"true"``/``"false"`` string to a Python bool.

    Args:
        s: The string to convert.

    Returns:
        ``True`` if *s* is ``"true"``, ``False`` if *s* is ``"false"``.

    Raises:
        ValueError: If the string is not exactly ``"true"`` or ``"false"``
                    (case-insensitive).
    """
    v = s.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    raise ValueError(f"Cannot convert {s!r} to bool — expected 'true' or 'false'")


# ---------------------------------------------------------------------------
# Payload-template clustering
# ---------------------------------------------------------------------------

def get_single_key_of_payload_template(data_item: Dict[str, Any]) -> str:
    """Return the cluster key for a payload template: ``type||information_features``."""
    return f"{data_item['type']}||{data_item['information_features']}"


def cluster_payload_templates(datas: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group a list of payload template dicts by ``type||information_features``.

    Args:
        datas: List of payload template dictionaries.

    Returns:
        Dict mapping each cluster key to its list of matching payload templates.
    """
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for item in datas:
        key = get_single_key_of_payload_template(item)
        clusters.setdefault(key, []).append(item)
    return clusters


# ---------------------------------------------------------------------------
# Injection-SQL clustering
# ---------------------------------------------------------------------------

def get_single_key_of_injection_sql(data_item: Dict[str, Any]) -> str:
    """Return the cluster key for a generated injection SQL example.

    Format: ``type||annotator||information_features||comment``
    Normal (benign) samples use the fixed key ``"normal||normal||normal||normal"``.
    """
    if not data_item["label"]:
        payload_type = data_item["payload_template"]["type"]
        annotator = data_item["original_sql"]["annotator"]
        info_features = data_item["payload_template"]["information_features"]
        comment = data_item.get("comment")
        return f"{payload_type}||{annotator}||{info_features}||{comment}"
    return "normal||normal||normal||normal"


def cluster_injection_sqls(datas: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group a list of injection SQL dicts by their cluster key.

    Args:
        datas: List of injection SQL example dicts.

    Returns:
        Dict mapping each cluster key to its list of matching injection SQL examples.
    """
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for item in datas:
        key = get_single_key_of_injection_sql(item)
        clusters.setdefault(key, []).append(item)
    return clusters


# ---------------------------------------------------------------------------
# Structured cluster key
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClusterKey:
    """Immutable, structured representation of a four-part cluster key.

    Format: ``payload_type||annotator||information_features||comment``
    """

    payload_type: str
    annotator: bool
    information_features: str
    comment: bool

    @classmethod
    def from_str(cls, s: str) -> ClusterKey:
        """Parse a cluster key string into a :class:`ClusterKey` instance.

        Args:
            s: String in the form ``type||annotator||info_features||comment``.

        Returns:
            Parsed :class:`ClusterKey`.

        Raises:
            ValueError: If the string does not have exactly four
                        ``||``-separated parts.
        """
        parts = s.split("||")
        if len(parts) != 4:
            raise ValueError(
                f"ClusterKey.from_str: invalid cluster key {s!r} — "
                f"expected 4 parts (type||annotator||information_features||comment), "
                f"got {len(parts)}"
            )
        payload_type, annotator_str, info_feat, comment_str = parts
        return cls(
            payload_type=payload_type,
            annotator=str_to_bool(annotator_str),
            information_features=info_feat,
            comment=str_to_bool(comment_str),
        )

    def payload_cluster_key(self) -> str:
        """Return the two-part payload-level cluster key.

        Format: ``payload_type||information_features``
        """
        return f"{self.payload_type}||{self.information_features}"
