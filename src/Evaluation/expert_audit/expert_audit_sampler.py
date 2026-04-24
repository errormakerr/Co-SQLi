"""Stratified sampler for the expert audit web app.

Draws 250 samples per dataset (stratified by original label) from the four
benchmark-quality CSVs, plus 20 calibration samples, and writes them into a
SQLite database that the FastAPI app reads.

Seeding is deterministic (seed=42) so every run produces the same sample
set and the same `assigned_order` (identical quiz order for every expert).

Database layout (three tables)
------------------------------
samples(sample_id PK, dataset, row_idx, sql, orig_label, is_calibration,
        assigned_order)
experts(expert_id PK, display_name, token UNIQUE, started_at, last_seen)
annotations(annotation_id PK, sample_id FK, expert_id FK,
            q1_verdict, q2_flipping, q3_attacks, notes,
            submitted_at, time_spent_ms,
            UNIQUE(sample_id, expert_id))

Usage
-----
    python expert_audit_sampler.py          # creates expert_audit.db
    python expert_audit_sampler.py --force  # wipes + regenerates
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)  # src/Evaluation
sys.path.insert(0, os.path.join(PARENT, "quality_metrics"))

from common import DATASETS, load_dataset  # noqa: E402

SEED = 42
PER_DATASET = 250
CALIBRATION_PER_DATASET = 5
DB_PATH = os.path.join(HERE, "expert_audit.db")


# ---------------------------------------------------------------------------
# schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    sample_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset         TEXT NOT NULL,
    row_idx         INTEGER NOT NULL,
    sql             TEXT NOT NULL,
    orig_label      TEXT NOT NULL,
    is_calibration  INTEGER NOT NULL DEFAULT 0,
    assigned_order  INTEGER NOT NULL,
    UNIQUE (dataset, row_idx)
);

CREATE INDEX IF NOT EXISTS idx_samples_order ON samples(assigned_order);

CREATE TABLE IF NOT EXISTS experts (
    expert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name    TEXT NOT NULL,
    token           TEXT NOT NULL UNIQUE,
    started_at      TEXT NOT NULL,
    last_seen       TEXT
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id       INTEGER NOT NULL REFERENCES samples(sample_id),
    expert_id       INTEGER NOT NULL REFERENCES experts(expert_id),
    q1_verdict      TEXT NOT NULL,           -- 'mal' | 'ben' | 'ambiguous' | 'invalid'
    q2_flipping     TEXT,                    -- 'yes' | 'no' | NULL (only for mal+ben)
    q3_attacks      TEXT,                    -- JSON list of classes, NULL for non-mal
    notes           TEXT,
    submitted_at    TEXT NOT NULL,
    time_spent_ms   INTEGER,
    UNIQUE (sample_id, expert_id)
);

CREATE INDEX IF NOT EXISTS idx_ann_sample ON annotations(sample_id);
CREATE INDEX IF NOT EXISTS idx_ann_expert ON annotations(expert_id);
"""


# ---------------------------------------------------------------------------
# sampling

def stratified_sample(samples, n: int, rng: random.Random):
    """Label-stratified sample.

    Split by normalized label (mal / ben / other) and allocate proportionally
    so the overall mal/ben ratio is preserved.  If a class is under-populated
    we fall back to pure random.
    """
    buckets = {"mal": [], "ben": [], "other": []}
    for s in samples:
        buckets[s.label].append(s)
    total = sum(len(v) for v in buckets.values())
    if total == 0:
        return []
    alloc = {k: max(0, round(n * len(v) / total)) for k, v in buckets.items()}
    # rounding drift fix
    while sum(alloc.values()) < n:
        # give extra slots to the largest bucket
        k = max(alloc, key=lambda k: len(buckets[k]) - alloc[k])
        alloc[k] += 1
    while sum(alloc.values()) > n:
        k = max(alloc, key=lambda k: alloc[k])
        alloc[k] -= 1

    picked = []
    for k, v in buckets.items():
        take = min(alloc[k], len(v))
        picked.extend(rng.sample(v, take))
    # top-up if a bucket was too small
    short = n - len(picked)
    if short > 0:
        pool = [s for s in samples if s not in picked]
        picked.extend(rng.sample(pool, min(short, len(pool))))
    return picked


def pick_calibration(by_dataset, rng: random.Random):
    """CALIBRATION_PER_DATASET samples per dataset, balanced across labels
    where possible. Separate from the main 250 pool."""
    out = []
    for name, samples in by_dataset.items():
        mal = [s for s in samples if s.label == "mal"]
        ben = [s for s in samples if s.label == "ben"]
        n_each = CALIBRATION_PER_DATASET // 2
        extra = CALIBRATION_PER_DATASET - 2 * n_each
        take = []
        if mal:
            take.extend(rng.sample(mal, min(n_each + extra, len(mal))))
        if ben:
            take.extend(rng.sample(ben, min(n_each, len(ben))))
        # pad if short
        if len(take) < CALIBRATION_PER_DATASET:
            pool = [s for s in samples if s not in take]
            take.extend(rng.sample(pool, min(CALIBRATION_PER_DATASET - len(take),
                                             len(pool))))
        out.extend(take)
    return out


# ---------------------------------------------------------------------------
# db build

def build_db(force: bool = False):
    if os.path.exists(DB_PATH):
        if not force:
            print(f"[abort] {DB_PATH} already exists. pass --force to rebuild.")
            return
        os.remove(DB_PATH)
        print(f"[clean] removed existing {DB_PATH}")

    rng = random.Random(SEED)
    by_dataset = {}
    for meta in DATASETS:
        if not os.path.exists(meta["path"]):
            print(f"[WARN] missing: {meta['path']}  (skipped)")
            continue
        rows = load_dataset(meta)
        by_dataset[meta["name"]] = rows
        print(f"[load] {meta['name']:12s} n={len(rows):>6d}  "
              f"(mal={sum(1 for s in rows if s.label=='mal')}, "
              f"ben={sum(1 for s in rows if s.label=='ben')})")

    # main pool: stratified 250 per dataset
    main_pool = []
    for name, samples in by_dataset.items():
        # deterministic per-dataset rng so datasets can be added/removed
        # without disturbing the others
        drng = random.Random(SEED + (hash(name) % 10_000))
        picks = stratified_sample(samples, PER_DATASET, drng)
        main_pool.extend([(p, False) for p in picks])
        print(f"[main] {name:12s} picked={len(picks)}")

    # calibration pool: separate rng so calibration picks are stable
    crng = random.Random(SEED + 7777)
    calib = pick_calibration(by_dataset, crng)
    # remove any overlap with main_pool (very unlikely but guard anyway)
    main_set = {(s.dataset, s.row_idx) for s, _ in main_pool}
    calib = [c for c in calib if (c.dataset, c.row_idx) not in main_set]
    calib_pool = [(c, True) for c in calib]
    print(f"[calib] picked={len(calib_pool)}")

    full = main_pool + calib_pool

    # deterministic quiz order
    order_rng = random.Random(SEED + 12345)
    order = list(range(len(full)))
    order_rng.shuffle(order)
    assigned_order = {i: pos for pos, i in enumerate(order)}

    # write
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    cur = conn.cursor()
    for i, (s, is_calib) in enumerate(full):
        cur.execute(
            "INSERT INTO samples(dataset,row_idx,sql,orig_label,"
            "is_calibration,assigned_order) VALUES (?,?,?,?,?,?)",
            (s.dataset, s.row_idx, s.sql, s.label,
             1 if is_calib else 0, assigned_order[i]),
        )
    conn.commit()
    n_main = sum(1 for _, c in full if not c)
    n_calib = sum(1 for _, c in full if c)
    print(f"[db] wrote {DB_PATH}  main={n_main}  calibration={n_calib}  "
          f"total={len(full)}")

    # summary by dataset
    cur.execute("""SELECT dataset, orig_label, COUNT(*),
                          SUM(is_calibration)
                   FROM samples GROUP BY dataset, orig_label
                   ORDER BY dataset, orig_label""")
    print("\n[summary]  dataset          label     count   calib")
    for row in cur.fetchall():
        print(f"           {row[0]:14s}  {row[1]:8s}  {row[2]:5d}  {row[3]:5d}")
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="wipe existing db and regenerate")
    args = ap.parse_args()
    build_db(force=args.force)


if __name__ == "__main__":
    main()
