"""Submit a Co-SQLi Slurm experiment with a self-contained run directory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cosqli.experiment_config import (
    DEFAULT_EXPERIMENT_CONFIG_PATH,
    experiment_config_sha256,
    load_experiment_config,
)
from cosqli.paths import (
    PROJECT_ROOT,
    get_config_path,
    require_external_path,
    resolve_runtime_artifacts_root,
    validate_run_id,
)
from cosqli.utils.yaml_operation import load_yaml_to_dict


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _artifacts_root() -> Path:
    runtime_config = load_yaml_to_dict(str(get_config_path("runtime_config.yaml")))
    if not isinstance(runtime_config, dict):
        raise ValueError("runtime_config.yaml must be a mapping")
    return resolve_runtime_artifacts_root(runtime_config)


def build_sbatch_command(
    *,
    run_dir: Path,
    job_name: str,
    partition: str | None,
    gres: str | None,
    cpus_per_task: int | None,
    memory: str | None,
    time_limit: str | None,
) -> list[str]:
    """Build the sbatch command that keeps scheduler logs within *run_dir*."""
    command = [
        "sbatch",
        "--parsable",
        f"--job-name={job_name}",
        f"--chdir={run_dir}",
        f"--output={run_dir / 'logs' / 'slurm-%j.out'}",
        f"--error={run_dir / 'logs' / 'slurm-%j.err'}",
    ]
    if partition:
        command.append(f"--partition={partition}")
    if gres:
        command.append(f"--gres={gres}")
    if cpus_per_task:
        command.append(f"--cpus-per-task={cpus_per_task}")
    if memory:
        command.append(f"--mem={memory}")
    if time_limit:
        command.append(f"--time={time_limit}")
    command.append(str(PROJECT_ROOT / "scripts" / "co_sqli_slurm_job.sh"))
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=_default_run_id())
    parser.add_argument("--experiment-config", default=str(DEFAULT_EXPERIMENT_CONFIG_PATH))
    parser.add_argument("--num-rounds", type=int)
    parser.add_argument("--num-training-sqls", type=int)
    parser.add_argument(
        "--benchmark-dir",
        required=True,
        help="External benchmark directory built by scripts/build_benchmarks.py.",
    )
    parser.add_argument("--breakpoint-round", type=int, default=-1)
    parser.add_argument("--job-name", default="co-sqli")
    parser.add_argument("--partition")
    parser.add_argument("--gres")
    parser.add_argument("--cpus-per-task", type=int)
    parser.add_argument("--mem")
    parser.add_argument("--time")
    args = parser.parse_args()
    experiment_config_path = Path(args.experiment_config).expanduser().resolve()
    experiment_config = load_experiment_config(experiment_config_path).with_cli_overrides(
        num_rounds=args.num_rounds,
        num_training_sqls=args.num_training_sqls,
    )

    if experiment_config.num_rounds <= 0 or experiment_config.num_training_sqls <= 0:
        parser.error("--num-rounds and --num-training-sqls must be positive")
    if (
        args.breakpoint_round >= experiment_config.num_rounds
        or args.breakpoint_round < -1
    ):
        parser.error("--breakpoint-round must be in [-1, num-rounds)")

    run_id = validate_run_id(args.run_id)
    run_dir = _artifacts_root() / run_id
    benchmark_dir = require_external_path(
        args.benchmark_dir,
        purpose="benchmark directory",
    )
    if not benchmark_dir.is_dir():
        parser.error(f"--benchmark-dir does not exist: {benchmark_dir}")
    if run_dir.exists():
        parser.error(f"run directory already exists: {run_dir}")
    (run_dir / "logs").mkdir(parents=True)

    environment = os.environ.copy()
    environment.update(
        {
            "COSQLI_PROJECT_ROOT": str(PROJECT_ROOT),
            "COSQLI_RUN_ID": run_id,
            "COSQLI_RUN_DIR": str(run_dir),
            "COSQLI_MODE": "full",
            "COSQLI_EXPERIMENT_CONFIG": str(experiment_config_path),
            "COSQLI_NUM_ROUNDS": str(experiment_config.num_rounds),
            "COSQLI_NUM_TRAINING_SQLS": str(experiment_config.num_training_sqls),
            "COSQLI_BREAKPOINT_ROUND": str(args.breakpoint_round),
            "COSQLI_BENCHMARK_DIR": str(benchmark_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    command = build_sbatch_command(
        run_dir=run_dir,
        job_name=args.job_name,
        partition=args.partition,
        gres=args.gres,
        cpus_per_task=args.cpus_per_task,
        memory=args.mem,
        time_limit=args.time,
    )
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True, env=environment)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "no scheduler output").strip()
        raise RuntimeError(f"sbatch submission failed: {detail}") from error
    job_id = result.stdout.strip().split(";", maxsplit=1)[0]
    (run_dir / "submission.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "job_id": job_id,
                "command": command,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "benchmark_dir": str(benchmark_dir),
                "experiment_config_sha256": experiment_config_sha256(
                    experiment_config_path
                ),
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(job_id)


if __name__ == "__main__":
    main()
