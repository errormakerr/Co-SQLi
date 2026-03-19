"""
JSON / JSONL file I/O utilities.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union


def read_json_file(file_path: str) -> Optional[Union[List[Any], Dict[str, Any]]]:
    """Load a JSON file and return its contents.

    Args:
        file_path: Path to the JSON file.

    Returns:
        Parsed data (list or dict), or ``None`` on error.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found — {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON — {e}")
        return None
    except Exception as e:
        print(f"Error reading file: {e}")
        return None


def write_json_file(file_path: str, data: Union[Dict[str, Any], List[Any]]) -> None:
    """Serialise *data* as pretty-printed JSON and write it to *file_path*.

    Args:
        file_path: Destination path.
        data:      JSON-serialisable object (dict or list).
    """
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"Data successfully written to {file_path}")
    except Exception as e:
        print(f"Error writing file: {e}")


def read_jsonl_file(file_path: str) -> List[Dict[str, Any]]:
    """Load a JSONL (newline-delimited JSON) file and return all records.

    Malformed lines are skipped with a warning message.

    Args:
        file_path: Path to the JSONL file.

    Returns:
        List of parsed record dicts; empty list on error.
    """
    data: List[Dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: invalid JSON on line {line_num} — {e}")
        print(f"Successfully read {len(data)} records from {file_path}")
        return data
    except FileNotFoundError:
        print(f"Error: file not found — {file_path}")
        return []
    except Exception as e:
        print(f"Error reading file: {e}")
        return []


def write_jsonl_file(
    file_path: str,
    data: Union[Dict[str, Any], List[Dict[str, Any]]],
) -> bool:
    """Write *data* to a JSONL file (one JSON object per line).

    *data* can be a single dict or a list of dicts.

    Args:
        file_path: Destination path.
        data:      A dict or a list of dicts to serialise.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            if isinstance(data, dict):
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
                count = 1
            elif isinstance(data, list):
                count = 0
                for item in data:
                    if isinstance(item, dict):
                        f.write(json.dumps(item, ensure_ascii=False) + "\n")
                        count += 1
                    else:
                        print(f"Warning: skipping non-dict item: {item}")
            else:
                raise ValueError("data must be a dict or a list of dicts")
        print(f"Successfully wrote {count} records to {file_path}")
        return True
    except Exception as e:
        print(f"Error writing file: {e}")
        return False
