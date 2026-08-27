"""Small, dependency-free helpers for run timing and resource telemetry."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cosqli.paths import require_external_path


def utc_timestamp() -> str:
    """Return an unambiguous UTC timestamp for persisted telemetry."""
    return datetime.now(timezone.utc).isoformat()


def append_stage_event(
    run_dir: Path | str,
    *,
    round_index: int | None,
    stage: str,
    event: str,
    duration_seconds: float | None = None,
) -> None:
    """Append one structured stage lifecycle event to a run's telemetry log."""
    resolved_run_dir = require_external_path(run_dir, purpose="telemetry output")
    destination = resolved_run_dir / "telemetry" / "stage_events.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "timestamp": utc_timestamp(),
        "unix_timestamp": time.time(),
        "round": round_index,
        "stage": stage,
        "event": event,
    }
    if duration_seconds is not None:
        record["duration_seconds"] = duration_seconds
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


@contextmanager
def measure_stage(
    run_dir: Path | str,
    *,
    round_index: int | None,
    stage: str,
) -> Iterator[dict[str, float]]:
    """Measure a stage and write matching start/completion telemetry events."""
    append_stage_event(run_dir, round_index=round_index, stage=stage, event="started")
    started = time.perf_counter()
    result: dict[str, float] = {}
    try:
        yield result
    finally:
        duration_seconds = time.perf_counter() - started
        result["duration_seconds"] = duration_seconds
        append_stage_event(
            run_dir,
            round_index=round_index,
            stage=stage,
            event="completed",
            duration_seconds=duration_seconds,
        )


def directory_size_bytes(directory: Path | str) -> int:
    """Return the total size of regular files beneath *directory*."""
    total = 0
    for path in Path(directory).rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total
