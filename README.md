# Co-SQLi

Co-SQLi is a reproducible adversarial-training framework for SQL-injection
detection. It synthesizes taxonomy-controlled SQL data, fine-tunes a Qwen
detector, evaluates validation and held-out test sets, and adapts the next
round's attack-cluster sampling distribution from validation feedback.

## Current Experiment

The versioned configuration at `config/experiment_config.yaml` defines the
standard experiment:

- eight rounds with 400 generated training examples per round;
- 48 attack clusters defined by technique, reference scope, and comment state;
- eight clusters sampled without replacement each round from a squared-weight
  distribution mixed with an exploration schedule from 0.70 to 0.20;
- centered full-information exponential verifier updates with learning rate 1.0;
- a validation set built from train-source attacks (1,920) and benign SQL
  (40), plus a held-out test set built from test-source attacks (1,738) and
  benign SQL (875).

Training and inference use the tokenizer's native Qwen chat template. Rendered
chat text is then tokenized with `add_special_tokens=False`, so template control
tokens are encoded once. Training labels mask the system/user prompt and retain
only assistant response tokens.

## Repository Boundary

The repository contains source data, code, prompts, and non-secret examples.
Benchmarks, models, MySQL runtime files, credentials, logs, telemetry, and
experiment reports belong in external directories. Every benchmark and run
output path is rejected if it points inside the repository.

```text
data/source/                 Versioned SQL, payload, schema, and comment inputs
config/experiment_config.yaml  Versioned experiment definition
scripts/build_benchmarks.py  Deterministic external benchmark builder
src/cosqli/                  Training, inference, synthesis, and reporting code
tests/                       Regression suite
```

## Setup

Install the package in a Python environment with the training dependencies:

```bash
python -m pip install -e '.[training,dev]'
```

Set `COSQLI_CONFIG_DIR` to an external directory containing these runtime
configuration files:

- `runtime_config.yaml`, based on `config/runtime_config.yaml.example`, with
  `base_model_path_env` and `artifacts_root_env` keys;
- `database_connection.yaml`, based on `config/database_connection.yaml.example`;
- `gpt_config.yaml`, based on `config/gpt_config.yaml.example`.

The runtime configuration names environment variables; it does not store model
locations or secrets. Export the corresponding values before a run:

```bash
export COSQLI_CONFIG_DIR=/path/to/runtime-config
export COSQLI_BASE_MODEL_PATH=/path/to/qwen-model
export COSQLI_ARTIFACTS_ROOT=/path/to/experiment-results
export COSQLI_LLM_API_KEY=...
export COSQLI_MYSQL_PASSWORD=...
```

## Build A Benchmark

The benchmark builder writes to a new, empty external directory and records
SHA-256 checksums for every source input and generated artifact. It requires the
same MySQL-backed synthesis environment as a full run.

```bash
python scripts/build_benchmarks.py \
  --output-dir /path/to/benchmarks/current \
  --seed 20260827
```

For a Slurm job, set `COSQLI_MODE=build-benchmarks`,
`COSQLI_BENCHMARK_OUTPUT_DIR`, `COSQLI_PROJECT_ROOT`, `COSQLI_ENV_PREFIX`, and
`COSQLI_RUNTIME_ROOT`, then submit `scripts/co_sqli_slurm_job.sh` with the
resources appropriate for synthesis.

## Run An Experiment

`co-sqli-submit` creates an isolated run directory, writes scheduler logs below
it, and submits the job. The batch script starts a MySQL sidecar, executes the
run, stops the sidecar, and writes reports plus resource telemetry.

```bash
export COSQLI_ENV_PREFIX=/path/to/python-environment
export COSQLI_RUNTIME_ROOT=/path/to/mysql-runtime

co-sqli-submit \
  --run-id experiment-001 \
  --benchmark-dir /path/to/benchmarks/current \
  --partition <partition> \
  --gres gpu:1 \
  --cpus-per-task 8 \
  --mem 64G \
  --time 12:00:00
```

The default values come from `config/experiment_config.yaml`. The two execution
size overrides are available for short validation runs:

```bash
co-sqli --run-id smoke-001 --benchmark-dir /path/to/benchmarks/current \
  --num-rounds 1 --num-training-sqls 16
```

Each run records its resolved configuration, Git revision, benchmark-manifest
checksum, per-round sampling probabilities, selected clusters, weights,
evaluation metrics, stage timings, and resource measurements. See
[`docs/experiment-protocol.md`](docs/experiment-protocol.md) and
[`docs/reproducibility.md`](docs/reproducibility.md) for the full contract.

## Validate

```bash
python -m pytest -q
```

The suite verifies taxonomy stability, benchmark construction guards, current
configuration validation, Qwen chat rendering and tokenization, verifier
updates, checkpoint boundaries, reporting, telemetry, and scheduler log paths.
