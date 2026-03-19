"""
YAML file loading utility.
"""

import yaml
from typing import Any, Dict


def load_yaml_to_dict(file_path: str) -> Dict[str, Any]:
    """
    Parse a YAML file and return its top-level mapping as a dict.

    Args:
        file_path: Path to the YAML configuration file.

    Returns:
        A dict containing the parsed YAML data.
        Returns an empty dict if the file is empty.

    Raises:
        TypeError: If the top-level YAML structure is not a mapping.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError(
            f"Expected a top-level YAML mapping, got: {type(data)}"
        )
    return data
