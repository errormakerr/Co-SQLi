"""
Centralized logging configuration for the SQLI project.

Call :func:`setup_logging` once at application startup (e.g. in ``main.py``)
to replace ad-hoc ``print()`` calls with structured logging.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
) -> None:
    """Configure the root logger with console (and optional file) output.

    Args:
        level:    Minimum log level (default ``INFO``).
        log_file: If provided, also write logs to this file path.
                  Parent directories are created automatically.
    """
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]

    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
        force=True,
    )
