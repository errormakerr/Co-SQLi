"""Random sampling from the *raw* (uncleaned) public-dataset CSVs.

The project's original sample_cleaned_datasets.py sampled from
`*_cleaned.csv` -- files that had INSERT/UPDATE/DELETE/... non-SELECT
statements filtered out (see filter_select_and_payload.py).  That
preprocessing is *our* pipeline step, not part of the public datasets.
A quality audit of the public datasets must therefore sample from the
raw CSVs; otherwise D1/D2/D5 numbers underestimate the true data issues.

Reservoir sampling handles the 10M-row rbsqli case without loading the
whole file into memory.

Outputs (seed=42, n=10,000 per public dataset):
  sqli dataset_1/data/SQLiV3_raw_sampled_10000.csv
  sqli dataset_2/data/rbsqli_dataset_raw_sampled_10000.csv
  sqli_dataset_3/data/Superviz25_raw_sampled_10000.csv
"""
from __future__ import annotations

import csv
import os
import random
import sys
import time

csv.field_size_limit(10 * 1024 * 1024)

SEED = 42
N_SAMPLES = 10_000

BASE = r"D:\project\server\other_dataset\sqli_dataset"

JOBS = [
    {
        "name": "SQLiV3",
        "in_path":  os.path.join(BASE, "sqli dataset_1", "data", "SQLiV3.csv"),
        "out_path": os.path.join(BASE, "sqli dataset_1", "data",
                                 f"SQLiV3_raw_sampled_{N_SAMPLES}.csv"),
        "sql_col": "Sentence",
        "label_col": "Label",
        "valid_labels": {"0", "1"},
    },
    {
        "name": "rbsqli",
        "in_path":  os.path.join(BASE, "sqli dataset_2", "data",
                                 "rbsqli_dataset.csv"),
        "out_path": os.path.join(BASE, "sqli dataset_2", "data",
                                 f"rbsqli_dataset_raw_sampled_{N_SAMPLES}.csv"),
        "sql_col": "sql_query",
        "label_col": "vulnerability_status",
        "valid_labels": {"Yes", "No"},
    },
    {
        "name": "Superviz25",
        "in_path":  os.path.join(BASE, "sqli_dataset_3", "data",
                                 "Superviz25.csv"),
        "out_path": os.path.join(BASE, "sqli_dataset_3", "data",
                                 f"Superviz25_raw_sampled_{N_SAMPLES}.csv"),
        "sql_col": "full_query",
        "label_col": "label",
        "valid_labels": {"0", "1"},
    },
]


def reservoir_sample(in_path: str, n: int, rng: random.Random,
                     sql_col: str, label_col: str, valid_labels: set):
    """Reservoir-sample `n` rows from `in_path`.

    Rows with an invalid label or empty SQL are skipped (same behaviour
    as the project's existing cleaned sampler: we only want labeled SQL).

    Returns (header, sample_rows, kept, total).
    """
    with open(in_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        sql_idx = header.index(sql_col)
        lab_idx = header.index(label_col)

        reservoir = []
        kept = 0
        total = 0
        t0 = time.time()
        for row in reader:
            total += 1
            if sql_idx >= len(row) or lab_idx >= len(row):
                continue
            sql = row[sql_idx]
            lab = (row[lab_idx] or "").strip()
            if not sql or lab not in valid_labels:
                continue
            kept += 1
            if len(reservoir) < n:
                reservoir.append(row)
            else:
                j = rng.randint(0, kept - 1)
                if j < n:
                    reservoir[j] = row
            if total % 500_000 == 0:
                rate = total / max(1.0, time.time() - t0)
                print(f"    scanned={total:>11,}  eligible_kept={kept:>11,}  "
                      f"({rate:,.0f} rows/s)", flush=True)

    return header, reservoir, kept, total


def main():
    rng = random.Random(SEED)
    for job in JOBS:
        if not os.path.exists(job["in_path"]):
            print(f"[SKIP] missing: {job['in_path']}")
            continue
        print(f"\n[{job['name']}] source: {job['in_path']}")
        # use a per-job rng seeded deterministically
        job_rng = random.Random(SEED + hash(job["name"]) % 10_000)
        header, rows, kept, total = reservoir_sample(
            job["in_path"], N_SAMPLES, job_rng,
            job["sql_col"], job["label_col"], job["valid_labels"],
        )
        # deterministic ordering of the reservoir for reproducibility
        rows.sort(key=lambda r: (r[header.index(job["sql_col"])],
                                 r[header.index(job["label_col"])]))
        os.makedirs(os.path.dirname(job["out_path"]), exist_ok=True)
        with open(job["out_path"], "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        pct = (len(rows) / kept * 100) if kept else 0.0
        print(f"[{job['name']}] total={total:,}  eligible={kept:,}  "
              f"sampled={len(rows):,} ({pct:.2f}% of eligible)")
        print(f"           -> {job['out_path']}")


if __name__ == "__main__":
    main()
