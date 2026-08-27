"""Tests for metrics, reports, and Slurm run-directory isolation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cosqli.evaluation import compute_classification_metrics
from cosqli.reporting import write_experiment_reports
from cosqli.submit import build_sbatch_command


class ExperimentReportingTests(unittest.TestCase):
    def test_metrics_include_security_rates_and_invalid_outputs(self) -> None:
        metrics = compute_classification_metrics(
            [
                {"ground_truth": "malicious", "predicted_answer": "malicious"},
                {"ground_truth": "malicious", "predicted_answer": "benign"},
                {"ground_truth": "benign", "predicted_answer": "malicious"},
                {"ground_truth": "benign", "predicted_answer": "benign"},
                {"ground_truth": "benign", "predicted_answer": "unknown"},
            ]
        )
        self.assertEqual(metrics["total"], 5)
        self.assertEqual(metrics["correct"], 2)
        self.assertEqual(metrics["invalid_prediction_count"], 1)
        self.assertEqual(metrics["confusion_matrix"], {
            "true_positive": 1,
            "true_negative": 1,
            "false_positive": 2,
            "false_negative": 1,
        })
        self.assertAlmostEqual(metrics["accuracy"], 0.4)
        self.assertAlmostEqual(metrics["precision"], 1 / 3)
        self.assertAlmostEqual(metrics["recall"], 0.5)
        self.assertAlmostEqual(metrics["false_negative_rate"], 0.5)

    def test_report_collects_round_metrics_and_final_test(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = Path(temporary_directory) / "experiment"
            round_dir = run_dir / "round_0"
            (round_dir / "performance").mkdir(parents=True)
            (round_dir / "evaluation" / "validation").mkdir(parents=True)
            (round_dir / "evaluation" / "test").mkdir(parents=True)
            (round_dir / "performance.json").write_text(
                json.dumps({"round_duration_seconds": 12.5, "stages": {"fine_tune_seconds": 5.0}}),
                encoding="utf-8",
            )
            (round_dir / "performance" / "training_metrics.json").write_text(
                json.dumps({"training_examples": 300, "train_examples_per_second": 12.0}),
                encoding="utf-8",
            )
            (round_dir / "evaluation" / "validation" / "metrics.json").write_text(
                json.dumps({"accuracy": 0.8, "f1": 0.75, "false_negative_rate": 0.2}),
                encoding="utf-8",
            )
            (round_dir / "evaluation" / "test" / "metrics.json").write_text(
                json.dumps({"accuracy": 0.9, "f1": 0.88, "recall": 0.86}),
                encoding="utf-8",
            )

            report = write_experiment_reports(run_dir)
            self.assertEqual(report["final_test"]["accuracy"], 0.9)
            self.assertTrue((run_dir / "reports" / "round_metrics.csv").is_file())
            self.assertTrue((run_dir / "reports" / "experiment_summary.json").is_file())
            self.assertTrue((run_dir / "reports" / "experiment_report.md").is_file())

    def test_sbatch_logs_are_nested_under_run_directory(self) -> None:
        run_dir = Path("/tmp/cosqli-experiment")
        command = build_sbatch_command(
            run_dir=run_dir,
            job_name="co-sqli",
            partition="gpu",
            gres="gpu:1",
            cpus_per_task=8,
            memory="64G",
            time_limit="01:00:00",
        )
        self.assertIn("--output=/tmp/cosqli-experiment/logs/slurm-%j.out", command)
        self.assertIn("--error=/tmp/cosqli-experiment/logs/slurm-%j.err", command)
        self.assertIn("--chdir=/tmp/cosqli-experiment", command)


if __name__ == "__main__":
    unittest.main()
