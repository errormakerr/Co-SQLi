# Experiment Protocol

## Data Contract

The external project `/hpc2hdd/home/hpan285/project/Co-SQLi-Benchmark` contains
`scripts/build_benchmarks.py`, which constructs all benchmark artifacts from
its versioned `data/source/` snapshot. The builder uses the canonical 48-cluster taxonomy and writes a
`build_manifest.json` containing source and artifact SHA-256 checksums. A run
accepts only an external benchmark that matches this manifest contract.
The benchmark project includes its own copy of the synthesis pipeline and
source-data snapshot, so benchmark construction does not import this runtime
repository.

Every benchmark contains two SFT renderings of each static SQL split:
`query_only` and `schema_aware`. Query-only user messages contain only the SQL
query, while schema-aware messages append DDL for the SQL record's database.
The raw SQL and labels are shared, and the selected `prompt_mode` applies to
both round-generated training data and static validation/test data.

| Dataset | Attack source | Attacks | Benign SQL |
| --- | --- | ---: | ---: |
| Static training corpus | train | 2,560 | 653 |
| Round training | train | generated each round | controlled by verifier |
| Validation | train | 1,920 | 40 |
| Test | test | 3,200 | 873 |

Validation drives the verifier. The test set is held out from policy updates
and is recorded for evaluation only.

The table describes the canonical schema-v2 benchmark build. A schema-v3
derived benchmark may reduce only the static training corpus while retaining
the same validation and test artifacts. Its manifest must record the parent
benchmark fingerprints, deterministic sampling rule and seed, selected-record
fingerprints, and checksums for every derived artifact. The runtime validates
this provenance before training; it does not accept an edited v2 benchmark.

The static training corpus is an external benchmark artifact for inspection and
optional baseline experiments. The current eight-round loop fine-tunes on the
generated `round_N/train_datas.jsonl` for each round; it does not automatically
append the static training corpus to that round's training input.

## Eight-Round Loop

The versioned experiment configuration defines eight rounds, 300 training
examples per round, an initial benign ratio of 0.25, and eight attack clusters
sampled without replacement per round. The default attacker strategy is
`by_probability`: it samples without replacement from the current distribution.
In the default `query_only` mode, benign training examples use the local train
corpus plus the configured external benign pools (`mix_benign_sources: true`).
When `prompt_mode` is `schema_aware`, the runtime resolves this setting to
`false` because those external rows do not carry database/schema metadata.
The implementation also supports the explicit `top_k` strategy for ablations.
Let `w_k` be the current weight of cluster `k`, `q=2`, `N=48`, and `gamma_t`
linearly decrease from 0.70 to 0.20.
The sampling probability is:

```text
p_t(k) = (1 - gamma_t) * w_k^q / sum_j(w_j^q) + gamma_t / N
```

The attacker draws eight distinct clusters using this distribution, synthesizes
attacks for those clusters, samples train-source benign SQL, and optionally
mutates payloads according to the configured round schedule.
Mutation weight scaling, mutation/type-inference LLM limits, prompt-routing
probability, expected-type inference, and mutation-memory few-shot count are
also explicit fields in the `payload_mutation` configuration section.
CEPP synthesis is configured separately in `synthesis.cepp`: the standard run
selects rational explanations with probability 0.20, caps their LLM response at
96 tokens, and disables SDK retries to avoid per-sample retry delays.

After fine-tuning, the verifier evaluates every validation cluster. For each
cluster, with `FN_k` false negatives and `n_k` validation examples, its smoothed
reward is:

```text
r_k = (FN_k + 1) / (n_k + 2)
```

With the round-wide mean reward `r_bar`, weights update as:

```text
w_k = w_k * exp(r_k - r_bar)
```

The benign share is updated from the smoothed validation false-positive rate.
For the current controller, the false-positive target is 0.05, the error EMA
decay is 0.70, the controller step size is 0.50, and the next-round ratio is
clipped to `[0.15, 0.35]`. The initial ratio is 0.25. These values are fields
in the `verifier` section of the YAML experiment configuration and are included
in the effective configuration recorded for each run.

## Qwen Input Contract

All SFT and inference examples use the tokenizer's native chat template. The
template is rendered to text first and that text is tokenized with
`add_special_tokens=False`. Training masks the rendered system and user prefix;
only assistant target tokens contribute to loss. The code records token-length
statistics and rejects a template that cannot produce the required chat format.

## Recorded Artifacts

Each run writes an external `run_manifest.json` containing the code revision,
resolved experiment configuration, source and resolved configuration checksums,
benchmark-manifest checksum, taxonomy, and scheduler identifier. Every round records sampling
probabilities, selected clusters, generated examples, verifier weights, reward
baseline, model metrics, stage timing, and resource telemetry.

`prompt_mode` is included in run and round metadata and is part of checkpoint
compatibility. Cross-mode resume is rejected.
