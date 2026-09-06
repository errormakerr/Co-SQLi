# Reproducibility

## Inputs

Use a clean external benchmark directory created by
`/hpc2hdd/home/hpan285/project/Co-SQLi-Benchmark/scripts/build_benchmarks.py`
with the required seed. Its `build_manifest.json`
binds the benchmark to exact versioned source inputs and generated files through
SHA-256 checksums. Co-SQLi validates those checksums before a training run.
The benchmark project carries its own synthesis code and source-data snapshot;
the runtime repository does not need to be on the builder's `PYTHONPATH`.

Each run records the complete effective experiment configuration together with separate
SHA-256 fingerprints for the source YAML and the resolved configuration after
any command-line overrides. The repository default experiment seed is `42`.
Use `--seed N` with either `co-sqli` or `co-sqli-submit` for a multi-seed
replicate; the override is applied to attacker sampling, payload generation,
fine-tuning, and inference. The resolved
`prompt_mode` is also stored in the run manifest; do not compare or resume runs
across `query_only` and `schema_aware` modes.

The seed does not by itself guarantee bit-for-bit identical results. GPU
operations can be nondeterministic, and results can change with the CUDA,
PyTorch, Transformers, or other dependency versions. When enabled, benchmark
comment generation and payload mutation also depend on external LLM responses.
For comparable runs, keep the hardware, software environment, model files,
source data, and external LLM configuration fixed, and retain the recorded
checksums and run metadata.

## Runtime

The default runtime configuration is kept in the repository under
`config/runtime_config.yaml`, `config/database_connection.yaml`, and
`config/gpt_config.yaml`; no external configuration directory is required.
The MySQL password and LLM API key are intentionally supplied through their
configured environment variables rather than stored in YAML.

Use one immutable base model directory and one writable external artifacts
directory. The batch script requires an external MySQL runtime and starts it on
a node-local Unix socket. It stores its process identifier and error log under
the run's `logs/` directory, then stops the service during cleanup.

## Outputs

```text
<artifacts-root>/<run-id>/
  run_manifest.json
  logs/
  telemetry/
  reports/
  round_0/
    generation_stats.json
    cluster_weights.jsonl
    verifier_state.json
    evaluation/
    performance.json
  ...
```

`generation_stats.json` contains the sampling distribution and selected
clusters. `cluster_weights.jsonl` contains the post-update verifier weights.
`reports/` consolidates round metrics, final held-out test metrics, artifact
sizes, and resource summaries.

## Resume

Resume only an existing run with its matching taxonomy and checkpoint metadata.
The run restores the selected round's weights, benign-ratio controller state,
and payload-mutation memory before continuing with the next round.
