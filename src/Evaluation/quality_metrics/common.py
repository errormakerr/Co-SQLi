"""Shared helpers for the benchmark quality-evaluation pipeline.

Defensive research only: this module loads SQL samples from the four
already-sampled CSV files (produced by sample_cleaned_datasets.py) and
provides a uniform record shape for downstream D1--D5 metrics.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from typing import Iterable, List

csv.field_size_limit(10 * 1024 * 1024)

BASE_DATA = r"D:\project\server\other_dataset\sqli_dataset"

DATASETS = [
    {
        "name": "SQLiV3",
        # RAW (uncleaned) random sample, n=10,000, seed=42
        "path": os.path.join(
            BASE_DATA, "sqli dataset_1", "data",
            "SQLiV3_raw_sampled_10000.csv"),
        "sql_col": "Sentence",
        "label_col": "Label",
        "malicious_values": {"1"},
        "benign_values": {"0"},
    },
    {
        "name": "rbsqli",
        # RAW (uncleaned) random sample, n=10,000, seed=42
        "path": os.path.join(
            BASE_DATA, "sqli dataset_2", "data",
            "rbsqli_dataset_raw_sampled_10000.csv"),
        "sql_col": "sql_query",
        "label_col": "vulnerability_status",
        "malicious_values": {"Yes"},
        "benign_values": {"No"},
    },
    {
        "name": "Superviz25",
        # RAW (uncleaned) random sample, n=10,000, seed=42
        "path": os.path.join(
            BASE_DATA, "sqli_dataset_3", "data",
            "Superviz25_raw_sampled_10000.csv"),
        "sql_col": "full_query",
        "label_col": "label",
        "malicious_values": {"1"},
        "benign_values": {"0"},
    },
    {
        "name": "Ours",
        # Ours benchmark is already our held-out corpus; use full rows.
        "path": os.path.join(
            BASE_DATA, "sqli_dataset_4", "data",
            "benchmark_context_free.csv"),
        "sql_col": "Sentence",
        "label_col": "Label",
        "malicious_values": {"1"},
        "benign_values": {"0"},
    },
]

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reports",
)


@dataclass
class Sample:
    dataset: str
    row_idx: int
    sql: str
    label: str          # normalized: "mal" / "ben" / "other"
    raw_label: str


def _norm_label(raw: str, mal: set, ben: set) -> str:
    s = (raw or "").strip()
    if s in mal:
        return "mal"
    if s in ben:
        return "ben"
    return "other"


def load_dataset(meta: dict) -> List[Sample]:
    with open(meta["path"], "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out: List[Sample] = []
    for i, r in enumerate(rows):
        sql = (r.get(meta["sql_col"]) or "")
        raw = (r.get(meta["label_col"]) or "")
        out.append(Sample(
            dataset=meta["name"],
            row_idx=i,
            sql=sql,
            label=_norm_label(raw, meta["malicious_values"], meta["benign_values"]),
            raw_label=raw.strip(),
        ))
    return out


def load_all() -> dict:
    """Return {dataset_name: [Sample,...]} for all four datasets."""
    result = {}
    for meta in DATASETS:
        if not os.path.exists(meta["path"]):
            print(f"[WARN] missing: {meta['path']}")
            continue
        result[meta["name"]] = load_dataset(meta)
    return result


# --- normalization used by D2 exact-dup hashing -----------------------------

_WS_RE = re.compile(r"\s+")
_STR_LIT_RE = re.compile(r"'([^']|'')*'")
_DSTR_LIT_RE = re.compile(r'"([^"]|"")*"')
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def normalize_sql(sql: str) -> str:
    s = (sql or "").strip().lower()
    s = _STR_LIT_RE.sub("'?'", s)
    s = _DSTR_LIT_RE.sub('"?"', s)
    s = _NUM_RE.sub("?", s)
    s = _WS_RE.sub(" ", s)
    return s


def ensure_reports_dir() -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    return REPORTS_DIR
