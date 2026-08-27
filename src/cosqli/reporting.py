"""Build durable per-round and per-run experiment reports."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cosqli.paths import require_external_path
from cosqli.telemetry import directory_size_bytes


ROUND_DIRECTORY_RE = re.compile(r"round_(\d+)$")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _round_directories(run_dir: Path) -> list[tuple[int, Path]]:
    rounds: list[tuple[int, Path]] = []
    for candidate in run_dir.iterdir():
        match = ROUND_DIRECTORY_RE.fullmatch(candidate.name)
        if candidate.is_dir() and match:
            rounds.append((int(match.group(1)), candidate))
    return sorted(rounds)


def _round_summary(round_index: int, round_dir: Path) -> dict[str, Any]:
    performance = _read_json(round_dir / "performance.json")
    training = _read_json(round_dir / "performance" / "training_metrics.json")
    validation = _read_json(round_dir / "evaluation" / "validation" / "metrics.json")
    test = _read_json(round_dir / "evaluation" / "test" / "metrics.json")
    return {
        "round": round_index,
        "round_duration_seconds": performance.get("round_duration_seconds"),
        "stages": performance.get("stages", {}),
        "training": training,
        "validation": validation,
        "test": test,
        "artifact_size_bytes": directory_size_bytes(round_dir),
    }


def _flatten_round(summary: dict[str, Any]) -> dict[str, Any]:
    training = summary.get("training", {})
    validation = summary.get("validation", {})
    test = summary.get("test", {})
    stages = summary.get("stages", {})
    return {
        "round": summary["round"],
        "round_duration_seconds": summary.get("round_duration_seconds"),
        "fine_tune_seconds": stages.get("fine_tune_seconds"),
        "merge_seconds": stages.get("merge_seconds"),
        "validation_seconds": stages.get("validation_evaluation_seconds"),
        "test_seconds": stages.get("test_evaluation_seconds"),
        "training_examples": training.get("training_examples"),
        "training_tokens": training.get("training_tokens"),
        "optimization_seconds": training.get("optimization_seconds"),
        "train_examples_per_second": training.get("train_examples_per_second"),
        "train_tokens_per_second": training.get("train_tokens_per_second"),
        "train_steps_per_second": training.get("train_steps_per_second"),
        "validation_accuracy": validation.get("accuracy"),
        "validation_f1": validation.get("f1"),
        "validation_fnr": validation.get("false_negative_rate"),
        "test_accuracy": test.get("accuracy"),
        "test_precision": test.get("precision"),
        "test_recall": test.get("recall"),
        "test_f1": test.get("f1"),
        "test_specificity": test.get("specificity"),
        "test_fpr": test.get("false_positive_rate"),
        "test_fnr": test.get("false_negative_rate"),
        "test_balanced_accuracy": test.get("balanced_accuracy"),
        "test_mcc": test.get("matthews_correlation"),
        "test_inference_seconds": test.get("timing", {}).get("inference_seconds"),
        "test_samples_per_second": test.get("timing", {}).get("samples_per_second"),
        "artifact_size_bytes": summary.get("artifact_size_bytes"),
    }


def _write_markdown(path: Path, summaries: list[dict[str, Any]], resource: dict[str, Any]) -> None:
    lines = ["# Co-SQLi Experiment Report", "", "## Round Metrics", ""]
    lines.extend(
        [
            "| Round | Test accuracy | Test F1 | Test recall | Test FNR | Train s | Test eval s |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for summary in summaries:
        row = _flatten_round(summary)
        def number(value: Any) -> str:
            return f"{value:.4f}" if isinstance(value, (float, int)) else "-"

        lines.append(
            "| {round} | {accuracy} | {f1} | {recall} | {fnr} | {train} | {test} |".format(
                round=row["round"],
                accuracy=number(row["test_accuracy"]),
                f1=number(row["test_f1"]),
                recall=number(row["test_recall"]),
                fnr=number(row["test_fnr"]),
                train=number(row["fine_tune_seconds"]),
                test=number(row["test_seconds"]),
            )
        )

    if resource:
        lines.extend(["", "## Resource Summary", ""])
        for key in ("gpu_utilization_percent", "gpu_memory_used_mib", "gpu_power_watts", "peak_rss_bytes"):
            value = resource.get(key)
            if value:
                lines.append(f"- {key}: {json.dumps(value, ensure_ascii=True)}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_experiment_reports(run_dir: Path | str) -> dict[str, Any]:
    """Write CSV, JSON, and Markdown summaries for all completed rounds."""
    resolved_run_dir = require_external_path(run_dir, purpose="report output")
    reports_dir = resolved_run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summaries = [_round_summary(index, directory) for index, directory in _round_directories(resolved_run_dir)]
    resource_summary = _read_json(resolved_run_dir / "telemetry" / "resource_summary.json")
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_directory": str(resolved_run_dir),
        "rounds": summaries,
        "final_test": summaries[-1].get("test", {}) if summaries else {},
        "resource_summary": resource_summary,
        "run_artifact_size_bytes": directory_size_bytes(resolved_run_dir),
    }
    (reports_dir / "experiment_summary.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    rows = [_flatten_round(summary) for summary in summaries]
    csv_path = reports_dir / "round_metrics.csv"
    fieldnames = list(rows[0]) if rows else ["round"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    _write_markdown(reports_dir / "experiment_report.md", summaries, resource_summary)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="External experiment directory.")
    args = parser.parse_args()
    write_experiment_reports(args.run_dir)


if __name__ == "__main__":
    main()
