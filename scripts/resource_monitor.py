#!/usr/bin/env python3
"""Sample Slurm-job GPU and memory use without additional dependencies."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FIELDS = [
    "timestamp",
    "unix_timestamp",
    "gpu_index",
    "gpu_name",
    "gpu_utilization_percent",
    "gpu_memory_used_mib",
    "gpu_memory_total_mib",
    "gpu_temperature_celsius",
    "gpu_power_watts",
    "slurm_average_cpu",
    "slurm_average_rss_bytes",
    "slurm_max_rss_bytes",
]


def _run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _number(value: str) -> float | None:
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def _memory_bytes(value: str) -> float | None:
    text = value.strip()
    if not text or text in {"N/A", "Unknown"}:
        return None
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    suffix = text[-1].upper()
    if suffix in multipliers:
        number = _number(text[:-1])
        return number * multipliers[suffix] if number is not None else None
    return _number(text)


def _slurm_statistics(job_id: str | None) -> tuple[str, float | None, float | None]:
    if not job_id:
        return "", None, None
    output = _run_command(
        [
            "sstat",
            f"--jobs={job_id}.batch",
            "--noheader",
            "--parsable2",
            "--format=AveCPU,AveRSS,MaxRSS",
        ]
    )
    if not output:
        return "", None, None
    values = output.splitlines()[0].split("|")
    values += [""] * (3 - len(values))
    return values[0], _memory_bytes(values[1]), _memory_bytes(values[2])


def _gpu_rows(job_id: str | None) -> list[dict[str, Any]]:
    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
    )
    cpu, average_rss, max_rss = _slurm_statistics(job_id)
    now = datetime.now(timezone.utc).isoformat()
    common = {
        "timestamp": now,
        "unix_timestamp": time.time(),
        "slurm_average_cpu": cpu,
        "slurm_average_rss_bytes": average_rss,
        "slurm_max_rss_bytes": max_rss,
    }
    if not output:
        missing_values = {key: "" for key in FIELDS if key not in common}
        return [{**missing_values, **common}]

    rows: list[dict[str, Any]] = []
    for values in csv.reader(output.splitlines()):
        values += [""] * (7 - len(values))
        rows.append(
            {
                **common,
                "gpu_index": values[0],
                "gpu_name": values[1],
                "gpu_utilization_percent": _number(values[2]),
                "gpu_memory_used_mib": _number(values[3]),
                "gpu_memory_total_mib": _number(values[4]),
                "gpu_temperature_celsius": _number(values[5]),
                "gpu_power_watts": _number(values[6]),
            }
        )
    return rows


def sample(output_path: Path, interval_seconds: float, job_id: str | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not output_path.exists() or output_path.stat().st_size == 0
    with output_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if needs_header:
            writer.writeheader()
        while True:
            writer.writerows(_gpu_rows(job_id))
            handle.flush()
            time.sleep(interval_seconds)


def _summary(values: Iterable[float]) -> dict[str, float] | None:
    ordered = sorted(values)
    if not ordered:
        return None

    def percentile(quantile: float) -> float:
        index = (len(ordered) - 1) * quantile
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

    return {
        "mean": sum(ordered) / len(ordered),
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "max": ordered[-1],
    }


def _integrate_power(rows: list[dict[str, str]]) -> float:
    by_gpu: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        timestamp = _number(row.get("unix_timestamp", ""))
        power = _number(row.get("gpu_power_watts", ""))
        if timestamp is not None and power is not None:
            by_gpu[row.get("gpu_index", "")].append((timestamp, power))
    watt_seconds = 0.0
    for samples in by_gpu.values():
        for (left_time, left_power), (right_time, right_power) in zip(samples, samples[1:]):
            watt_seconds += (left_power + right_power) * (right_time - left_time) / 2
    return watt_seconds / 3600


def _resource_slice(rows: list[dict[str, str]]) -> dict[str, Any]:
    def values(column: str) -> list[float]:
        return [number for row in rows if (number := _number(row.get(column, ""))) is not None]

    return {
        "sample_count": len(rows),
        "gpu_utilization_percent": _summary(values("gpu_utilization_percent")),
        "gpu_memory_used_mib": _summary(values("gpu_memory_used_mib")),
        "gpu_temperature_celsius": _summary(values("gpu_temperature_celsius")),
        "gpu_power_watts": _summary(values("gpu_power_watts")),
        "estimated_gpu_energy_wh": _integrate_power(rows),
        "average_rss_bytes": _summary(values("slurm_average_rss_bytes")),
        "peak_rss_bytes": max(values("slurm_max_rss_bytes"), default=None),
    }


def _stage_intervals(events_path: Path) -> dict[str, tuple[float, float]]:
    if not events_path.is_file():
        return {}
    started: dict[tuple[Any, str], float] = {}
    intervals: dict[str, tuple[float, float]] = {}
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            key = (event.get("round"), event["stage"])
            timestamp = float(event["unix_timestamp"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if event.get("event") == "started":
            started[key] = timestamp
        elif event.get("event") == "completed" and key in started:
            label = f"round_{key[0]}.{key[1]}" if key[0] is not None else key[1]
            intervals[label] = (started.pop(key), timestamp)
    return intervals


def summarize(samples_path: Path, output_path: Path) -> None:
    rows: list[dict[str, str]] = []
    if samples_path.is_file():
        with samples_path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

    allocation = {
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        "memory_per_node": os.environ.get("SLURM_MEM_PER_NODE"),
        "job_gpus": os.environ.get("SLURM_JOB_GPUS"),
    }
    summary = {
        "schema_version": 1,
        "allocation": allocation,
        **_resource_slice(rows),
        "stage_resource_usage": {},
    }
    for stage, (started, completed) in _stage_intervals(samples_path.parent / "stage_events.jsonl").items():
        stage_rows = [
            row
            for row in rows
            if (timestamp := _number(row.get("unix_timestamp", ""))) is not None
            and started <= timestamp <= completed
        ]
        summary["stage_resource_usage"][stage] = _resource_slice(stage_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="CSV sample output path.")
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--job-id", default=os.environ.get("SLURM_JOB_ID"))
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--summary-output", help="JSON summary destination.")
    args = parser.parse_args()
    output_path = Path(args.output)
    if args.summarize:
        if not args.summary_output:
            parser.error("--summary-output is required with --summarize")
        summarize(output_path, Path(args.summary_output))
        return
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    sample(output_path, args.interval_seconds, args.job_id)


if __name__ == "__main__":
    main()
