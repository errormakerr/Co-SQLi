"""Tests for dependency-free Slurm resource telemetry aggregation."""

from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosqli.paths import PROJECT_ROOT


def _resource_monitor_module():
    script = PROJECT_ROOT / "scripts" / "resource_monitor.py"
    spec = importlib.util.spec_from_file_location("cosqli_resource_monitor", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load resource monitor script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResourceMonitorTests(unittest.TestCase):
    def test_unavailable_gpu_command_returns_no_samples(self) -> None:
        monitor = _resource_monitor_module()
        with patch.object(monitor.subprocess, "run", side_effect=PermissionError):
            self.assertEqual(monitor._run_command(["nvidia-smi"]), "")

    def test_summary_reports_gpu_and_memory_peaks(self) -> None:
        monitor = _resource_monitor_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            samples = directory / "resource_samples.csv"
            with samples.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=monitor.FIELDS)
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "unix_timestamp": "100.0",
                            "gpu_index": "0",
                            "gpu_utilization_percent": "20",
                            "gpu_memory_used_mib": "1000",
                            "gpu_temperature_celsius": "40",
                            "gpu_power_watts": "50",
                            "slurm_average_rss_bytes": "1024",
                            "slurm_max_rss_bytes": "2048",
                        },
                        {
                            "unix_timestamp": "105.0",
                            "gpu_index": "0",
                            "gpu_utilization_percent": "60",
                            "gpu_memory_used_mib": "2000",
                            "gpu_temperature_celsius": "50",
                            "gpu_power_watts": "70",
                            "slurm_average_rss_bytes": "2048",
                            "slurm_max_rss_bytes": "4096",
                        },
                    ]
                )
            summary_path = directory / "resource_summary.json"
            monitor.summarize(samples, summary_path)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["sample_count"], 2)
            self.assertEqual(summary["gpu_utilization_percent"]["max"], 60.0)
            self.assertEqual(summary["gpu_memory_used_mib"]["max"], 2000.0)
            self.assertEqual(summary["peak_rss_bytes"], 4096.0)
            self.assertAlmostEqual(summary["estimated_gpu_energy_wh"], 60 * 5 / 3600)


if __name__ == "__main__":
    unittest.main()
