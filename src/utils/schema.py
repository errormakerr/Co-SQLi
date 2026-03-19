"""
Schema lookup utilities.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def get_schema(db: str, schemas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find and return the schema dict for the given database name.

    Args:
        db:      The ``database_name`` to look up.
        schemas: List of schema dicts, each containing a ``database_name`` key.

    Returns:
        The matching schema dict, or ``None`` if not found.
    """
    for item in schemas:
        if item["database_name"] == db:
            return item
    return None
