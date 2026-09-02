# Co-SQLi

Co-SQLi is a reproducible adversarial-training framework for SQL-injection
detection. It synthesizes taxonomy-controlled SQL data, fine-tunes a Qwen
detector, evaluates validation and held-out test sets, and adapts the next
round's attack-cluster sampling distribution from validation feedback.

## Current Experiment

The versioned configuration at `config/experiment_config.yaml` defines the
standard experiment:

- eight rounds with 300 generated training examples per round;
- 48 attack clusters defined by technique, reference scope, and comment state;
- eight clusters sampled without replacement each round from a squared-weight
  distribution mixed with an exploration schedule from 0.70 to 0.20;
- centered full-information exponential verifier updates with learning rate 1.0;
- a static training corpus built from 2,560 train-source attacks and all 653 train benign
  SQL, a validation set with 1,920 train-source attacks and 40 benign SQL, and
  a held-out test set with 3,200 test-source attacks and all 873 test benign SQL.

Training and inference use the tokenizer's native Qwen chat template. Rendered
chat text is then tokenized with `add_special_tokens=False`, so template control
tokens are encoded once. Training labels mask the system/user prompt and retain
only assistant response tokens.

## Prompt Modes

`prompt_mode` is a run-defining experiment setting. The default, `query_only`,
makes the model-visible user message exactly `SQL Query:` followed by the SQL
text; no database name, DDL, or schema placeholder is included. `schema_aware`
additionally supplies the database DDL.

The benchmark builder writes both mode-specific SFT artifacts from the same raw
SQL splits, so mode comparisons retain identical SQL, labels, ordering, and
seed. Select a mode in an experiment YAML or override it for a run:

```bash
co-sqli --run-id query-only-001 --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
  --prompt-mode query_only

co-sqli-submit --run-id schema-aware-001 --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
  --prompt-mode schema_aware --partition <partition> --gres gpu:1
```

Prompt mode is recorded in benchmark, run, round, and submission metadata. A
checkpoint can be resumed only with the same mode. Rebuild benchmarks after this
format change; previous benchmark manifests are intentionally rejected.

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

For an external legacy configuration that contains a secret value, set
`COSQLI_ALLOW_INLINE_SECRETS=1` explicitly. Repository configuration templates
never contain secret values.

## Build A Benchmark

The benchmark builder writes to a new, empty external directory and records
SHA-256 checksums for every source input and generated artifact. It requires the
same MySQL-backed synthesis environment as a full run.

The standard benchmark artifact for this deployment is
`/hpc2hdd/home/hpan285/data/co-sqli/benchmarks/v2-prompt-modes-seed-20260827`. Build a fresh
staging directory and validate its manifest before deliberately refreshing this
canonical artifact.

```bash
export COSQLI_BENCHMARK_DIR=/hpc2hdd/home/hpan285/data/co-sqli/benchmarks/v2-prompt-modes-seed-20260827

python scripts/build_benchmarks.py \
  --output-dir "$COSQLI_BENCHMARK_DIR" \
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
  --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
  --partition <partition> \
  --gres gpu:1 \
  --cpus-per-task 8 \
  --mem 64G \
  --time 12:00:00
```

The default values come from `config/experiment_config.yaml`. The two execution
size overrides are available for short validation runs:

```bash
co-sqli --run-id smoke-001 --benchmark-dir "$COSQLI_BENCHMARK_DIR" \
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
