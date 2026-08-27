# Experiment Protocol

## Data Contract

`scripts/build_benchmarks.py` constructs all benchmark artifacts from
`data/source/`. The builder uses the canonical 48-cluster taxonomy and writes a
`build_manifest.json` containing source and artifact SHA-256 checksums. A run
accepts only an external benchmark that matches this manifest contract.

| Dataset | Attack source | Attacks | Benign SQL |
| --- | --- | ---: | ---: |
| Training | train | generated each round | controlled by verifier |
| Validation | train | 1,920 | 40 |
| Test | test | 1,738 | 875 |

Validation drives the verifier. The test set is held out from policy updates
and is recorded for evaluation only.

## Eight-Round Loop

The versioned experiment configuration defines eight rounds, 400 training
examples per round, an initial benign ratio of 0.25, and eight attack clusters
sampled without replacement per round. Let `w_k` be the current weight of
cluster `k`, `q=2`, `N=48`, and `gamma_t` linearly decrease from 0.70 to 0.20.
The sampling probability is:

```text
p_t(k) = (1 - gamma_t) * w_k^q / sum_j(w_j^q) + gamma_t / N
```

The attacker draws eight distinct clusters using this distribution, synthesizes
attacks for those clusters, samples train-source benign SQL, and optionally
mutates payloads according to the configured round schedule.

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

The benign share is updated from the smoothed validation false-positive rate and
is constrained to the configured controller range.

## Qwen Input Contract

All SFT and inference examples use the tokenizer's native chat template. The
template is rendered to text first and that text is tokenized with
`add_special_tokens=False`. Training masks the rendered system and user prefix;
only assistant target tokens contribute to loss. The code records token-length
statistics and rejects a template that cannot produce the required chat format.

## Recorded Artifacts

Each run writes an external `run_manifest.json` containing the code revision,
resolved experiment configuration, configuration checksum, benchmark-manifest
checksum, taxonomy, and scheduler identifier. Every round records sampling
probabilities, selected clusters, generated examples, verifier weights, reward
baseline, model metrics, stage timing, and resource telemetry.
