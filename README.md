# Co-SQLi

Co-SQLi is an adversarial training framework for SQL-injection detection. It
generates taxonomy-controlled training data, fine-tunes a detector, evaluates
the result, and uses feedback to select the next attack clusters.

## Repository Layout

```text
Co-SQLi/
├── config/                 # Versioned, non-secret defaults and examples
├── data/
│   ├── source/             # Versioned source SQL, schemas, and payload templates
│   └── benchmark/          # Versioned reviewed benchmark snapshots
├── prompts/                # Jinja2 templates for comment and mutation prompts
├── resources/ddl/          # MySQL reference schemas
├── scripts/                # Batch entry points and validation tools
├── src/cosqli/
│   ├── attacker/           # Cluster sampling and payload mutation
│   ├── defender/           # Fine-tuning, merging, and evaluation orchestration
│   ├── modeling/           # Standalone model-operation programs
│   ├── synthesis/          # SQL and SFT data generation
│   ├── verifier/           # Feedback and EXP3 weight updates
│   └── paths.py            # Configuration and external-artifact boundary
└── tests/
```

All generated data, checkpoints, models, logs, and Slurm output live outside
the repository. The runtime MySQL installation is separate from experiment
artifacts:

```text
/hpc2hdd/home/hpan285/co-sqli-runtime/
├── mysql/
└── config/

/hpc2hdd/home/hpan285/experiment_results/
└── <run-id>/
```

## Setup

Install the package in an existing Python environment:

```bash
python -m pip install -e '.[training,dev]'
```

Create external runtime configuration from the examples in `config/`, then
export the configuration and secret locations:

```bash
export COSQLI_CONFIG_DIR=/hpc2hdd/home/hpan285/co-sqli-runtime/config
export COSQLI_BASE_MODEL_PATH=/path/to/base-model
export COSQLI_LLM_API_KEY=...
export COSQLI_MYSQL_PASSWORD=...
```

`runtime_config.yaml` contains only `base_model_path_env` and the approved
artifact root. Model locations and credentials are environment variables, not
YAML values.

## Run

Run a named experiment. Its files are created only below the external artifact
root:

```bash
co-sqli --run-id experiment-001 --num-rounds 8 --num-training-sqls 300
```

Resume is allowed only for a checkpoint whose persisted taxonomy version and
cluster list match the current v3 schema:

```bash
co-sqli --run-id experiment-001 --breakpoint-round 3
```

For Slurm, provide the environment and external runtime root before submission:

```bash
export COSQLI_ENV_PREFIX=/path/to/python-environment
export COSQLI_RUNTIME_ROOT=/hpc2hdd/home/hpan285/co-sqli-runtime
export COSQLI_CONFIG_DIR=/hpc2hdd/home/hpan285/co-sqli-runtime/config
COSQLI_MODE=full sbatch scripts/co_sqli_slurm_job.sh
```

Available batch modes are `db-check`, `generate-smoke`, `mutation-smoke`,
`synthesis-smoke`, `build-benchmarks`, and `full`. `build-benchmarks` requires
`COSQLI_BENCHMARK_OUTPUT_DIR` and never overwrites the versioned benchmark
snapshot in this repository.

## Taxonomy And Prompts

The stable taxonomy uses `technique`, `reference_scope`, and `comment_state`.
Checkpoint and mutation-memory metadata retain the v3 schema identifier, so a
checkpoint with another taxonomy contract is rejected rather than migrated.

All prompt bodies are Jinja2 files under `prompts/`. Mutation rendering code
selects a template and supplies technical guidance; it does not contain a
second prompt-template implementation. The mutation prompts define the
`lor`, `tsr`, and `scr` reference scopes and identify memory examples as
negative few-shot context.

## Validation

Run the focused regression suite:

```bash
python -m pytest -q
```

The test suite verifies taxonomy arm stability, v3 checkpoint rejection and
restoration, mutation memory behavior, prompt rendering, CEPP few-shots, and
the external-artifact guard.
