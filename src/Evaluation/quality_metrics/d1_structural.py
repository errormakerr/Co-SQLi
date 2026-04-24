"""D1: Structural Completeness.

For each sample we try to parse the SQL; if parsing fails (or the result
is not a top-level DML/DDL statement), we bucket the failure into one of
four categories:
  - fragment            (e.g., `id = 1 OR 1 = 1` -- no leading keyword)
  - truncated           (SELECT ... with no FROM, or statement ends mid-clause)
  - multi_unterminated  (multiple statements but last one unterminated)
  - unparseable         (everything else)

Injection samples are parsed in a double-state manner: if the original
query fails but a trivial "prefix-removed" variant succeeds, we count
it as structurally OK (this mirrors how WAFs see injected payloads).

Outputs: reports/e4_auto_D1.json
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Tuple

import sqlglot
import sqlparse

from common import DATASETS, Sample, ensure_reports_dir, load_all

TOP_LEVEL_KEYWORDS = {
    "select", "insert", "update", "delete", "with",
    "create", "alter", "drop", "truncate", "replace",
    "merge", "set", "use", "show", "describe", "desc", "explain",
}

LEADING_WORD = re.compile(r"^\s*([A-Za-z]+)")


def _leading(sql: str) -> str:
    m = LEADING_WORD.match(sql or "")
    return (m.group(1).lower() if m else "")


def _try_sqlglot(sql: str) -> bool:
    try:
        trees = sqlglot.parse(sql, read="mysql")
        return any(t is not None for t in trees)
    except Exception:
        return False


def _try_sqlparse(sql: str) -> bool:
    try:
        parsed = sqlparse.parse(sql)
        if not parsed:
            return False
        first = parsed[0]
        # demand a DDL/DML keyword at the top
        tokens = [t for t in first.flatten() if not t.is_whitespace]
        if not tokens:
            return False
        return (tokens[0].ttype is not None
                and str(tokens[0].value).lower() in TOP_LEVEL_KEYWORDS)
    except Exception:
        return False


def parse_ok(sql: str) -> bool:
    if not sql or not sql.strip():
        return False
    if _leading(sql) not in TOP_LEVEL_KEYWORDS:
        return False
    return _try_sqlglot(sql) or _try_sqlparse(sql)


def classify_failure(sql: str) -> str:
    """Return one of fragment / truncated / multi_unterm / unparseable."""
    if not sql or not sql.strip():
        return "fragment"
    lead = _leading(sql)
    if lead not in TOP_LEVEL_KEYWORDS:
        return "fragment"
    # multiple statements?
    parts = [p for p in sqlparse.split(sql) if p.strip()]
    if len(parts) > 1:
        # last part missing terminator or incomplete
        return "multi_unterm"
    # single statement with leading keyword but cannot parse ->
    #   likely truncated clause (missing FROM / WHERE value / etc.)
    # Distinguish truncated vs unparseable by looking for obvious truncation:
    if re.search(r"(select|from|where|order\s+by|group\s+by)\s*$",
                 sql, re.IGNORECASE):
        return "truncated"
    return "unparseable"


def audit_sample(s: Sample) -> Tuple[bool, str]:
    """Return (ok, reason). reason is '' on success."""
    if parse_ok(s.sql):
        return True, ""
    # double-state for injection samples: strip outer quotes / leading ',
    # re-parse to approximate "injected payload in context"
    if s.label == "mal":
        stripped = s.sql.strip().lstrip("'\"").rstrip(";'\"")
        if stripped != s.sql and parse_ok(stripped):
            return True, ""
    return False, classify_failure(s.sql)


def analyze_dataset(name: str, samples) -> dict:
    total = len(samples)
    ok_total = 0
    failures = Counter()
    by_label = {
        "mal": {"n": 0, "ok": 0, "fail": Counter()},
        "ben": {"n": 0, "ok": 0, "fail": Counter()},
        "other": {"n": 0, "ok": 0, "fail": Counter()},
    }
    for s in samples:
        ok, reason = audit_sample(s)
        by_label[s.label]["n"] += 1
        if ok:
            ok_total += 1
            by_label[s.label]["ok"] += 1
        else:
            failures[reason] += 1
            by_label[s.label]["fail"][reason] += 1
    return {
        "dataset": name,
        "n": total,
        "structural_rate": ok_total / total if total else 0.0,
        "ok_count": ok_total,
        "failure_breakdown": dict(failures),
        "by_label": {
            k: {
                "n": v["n"],
                "ok": v["ok"],
                "ok_rate": (v["ok"] / v["n"]) if v["n"] else 0.0,
                "fail": dict(v["fail"]),
            } for k, v in by_label.items()
        },
    }


def main():
    data = load_all()
    results = []
    for meta in DATASETS:
        if meta["name"] not in data:
            continue
        r = analyze_dataset(meta["name"], data[meta["name"]])
        results.append(r)
        print(f"[{r['dataset']:10s}] n={r['n']:4d}  "
              f"structural_rate={r['structural_rate']*100:5.2f}%  "
              f"failures={r['failure_breakdown']}")

    out = os.path.join(ensure_reports_dir(), "e4_auto_D1.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"dimension": "D1_Structural_Completeness",
                   "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n[D1] written {out}")


if __name__ == "__main__":
    main()
