"""Tiny .env loader.

Why not `python-dotenv`?
    We only need a few dozen lines, and avoiding one more pip dependency
    keeps the deployment README short.  Shape-compatible with the common
    `.env` conventions:

      - lines of the form `KEY=value`
      - `#` starts a comment (line-level or trailing)
      - leading `export ` is tolerated
      - value may be quoted with '...' or "..."
      - blank lines / whitespace are ignored
      - existing os.environ values WIN (env overrides .env, just like
        python-dotenv's default behaviour)

Usage
-----
    from config import load_env, get_str, get_int, get_bool
    load_env()                         # loads ./.env into os.environ
    ADMIN_KEY = get_str("EXPERT_AUDIT_ADMIN_KEY", "letmein")
"""
from __future__ import annotations

import os
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENV_FILE = os.path.join(HERE, ".env")

_loaded = False


def _strip_inline_comment(v: str) -> str:
    # only strip a trailing comment when the '#' is NOT inside quotes
    out, in_q, q = [], False, ""
    for ch in v:
        if in_q:
            out.append(ch)
            if ch == q:
                in_q = False
        elif ch in ("'", '"'):
            in_q = True; q = ch; out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def load_env(path: str = DEFAULT_ENV_FILE, override: bool = False) -> dict:
    """Load `path` into os.environ. Returns the dict of loaded pairs.

    If `override` is False (default), values already set in os.environ
    are left untouched — this lets a real environment variable take
    precedence over .env, which matches the usual conventions.
    """
    global _loaded
    loaded: dict = {}
    if not os.path.exists(path):
        _loaded = True
        return loaded
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if not k or not k.replace("_", "").isalnum():
                continue
            v = _unquote(_strip_inline_comment(v))
            loaded[k] = v
            if override or k not in os.environ:
                os.environ[k] = v
    _loaded = True
    return loaded


def get_str(key: str, default: Optional[str] = None) -> Optional[str]:
    if not _loaded:
        load_env()
    return os.environ.get(key, default)


def get_int(key: str, default: int) -> int:
    v = get_str(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def get_bool(key: str, default: bool = False) -> bool:
    v = get_str(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "y", "t")
