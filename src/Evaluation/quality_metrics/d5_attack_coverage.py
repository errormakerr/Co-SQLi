"""D5: Attack Type Coverage.

Coarse taxonomy (8 canonical SQLi classes, OWASP+sqlmap aligned):

  tautology         e.g. OR 1=1, 'a'='a'
  boolean_inference AND/OR with blind-boolean paired checks, IF(...)
  union_based       UNION SELECT ...
  error_based       extractvalue / updatexml / cast(... as ...)
  time_based        SLEEP / WAITFOR DELAY / BENCHMARK / pg_sleep
  piggybacked       stacked statements via ;
  stacked_queries   (alias for piggybacked)  -- collapsed below
  inline_injection  single statement with comment/quote escape (--, /*, #)

Note on collapse: piggybacked and stacked_queries overlap; we keep one
label "stacked" and report 7 coarse classes.  Readers preferring 8 can
split stacked into "piggy-after-DML" vs "standalone exec" in the human
calibration step.

Only samples labeled *malicious* contribute to the per-type distribution
(benign samples trivially have no attack type).

Outputs: reports/e4_auto_D5.json
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from typing import Dict, List, Tuple

from common import DATASETS, Sample, ensure_reports_dir, load_all

# --- regex bank (intentionally conservative; human calibration follows) ----

P = {
    "tautology":     re.compile(
        r"""\b(?P<tn>\d+)\s*=\s*(?P=tn)\b"""
        r"""|(?P<q>['"])\s*(?P<s>\w+)\s*(?P=q)\s*=\s*(?P=q)\s*(?P=s)\s*(?P=q)""",
        re.IGNORECASE),
    "union_based":   re.compile(r"\bunion\s+(?:all\s+)?select\b", re.IGNORECASE),
    "error_based":   re.compile(
        r"\b(extractvalue|updatexml|utl_inaddr\.get_host_address|"
        r"ctxsys\.drithsx\.sn|dbms_utility\.sqlid_to_sqlhash)\s*\(",
        re.IGNORECASE),
    "time_based":    re.compile(
        r"\b(sleep|waitfor\s+delay|benchmark|pg_sleep|"
        r"dbms_pipe\.receive_message|dbms_lock\.sleep)\b", re.IGNORECASE),
    "stacked":       re.compile(
        r";\s*(select|insert|update|delete|drop|alter|create|exec(?:ute)?"
        r"|shutdown|truncate|declare|begin|if|xp_|sp_)", re.IGNORECASE),
    "boolean_inference": re.compile(
        r"\b(and|or)\b[^\n;]{0,80}(=|<|>|like|in\s*\(|is\s+null)",
        re.IGNORECASE),
    "inline_injection":  re.compile(
        r"""(--|/\*|\*/|\#)|(['"]\s*(or|and)\s+)""", re.IGNORECASE),
}

# order matters: more specific first
ORDER = [
    "union_based", "error_based", "time_based", "stacked",
    "tautology", "inline_injection", "boolean_inference",
]


def classify(sql: str) -> List[str]:
    if not sql:
        return []
    hits = [name for name in ORDER if P[name].search(sql)]
    return hits


def primary_label(hits: List[str]) -> str:
    return hits[0] if hits else "none"


def _shannon(counts: Dict[str, int]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    H = 0.0
    for c in counts.values():
        if c == 0:
            continue
        p = c / total
        H -= p * math.log2(p)
    return H


def _gini(counts: List[int]) -> float:
    if not counts or sum(counts) == 0:
        return 0.0
    xs = sorted(counts)
    n = len(xs)
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * sum(xs)) - (n + 1) / n


def analyze_dataset(name: str, samples: List[Sample]) -> dict:
    mal = [s for s in samples if s.label == "mal"]
    mal_n = len(mal)

    prim_counts: Counter = Counter()
    multi_counts: Counter = Counter()
    for s in mal:
        hits = classify(s.sql)
        prim_counts[primary_label(hits)] += 1
        for h in hits:
            multi_counts[h] += 1
        if not hits:
            multi_counts["none"] += 1

    covered_types = sum(1 for k in ORDER if prim_counts.get(k, 0) > 0)
    type_coverage_rate = covered_types / len(ORDER)
    per_type_min_count = min(prim_counts.get(k, 0) for k in ORDER)
    H = _shannon({k: prim_counts.get(k, 0) for k in ORDER})
    H_norm = H / math.log2(len(ORDER)) if len(ORDER) > 1 else 0.0
    gini = _gini([prim_counts.get(k, 0) for k in ORDER])

    return {
        "dataset": name,
        "malicious_n": mal_n,
        "taxonomy": ORDER,
        "primary_counts": {k: prim_counts.get(k, 0) for k in ORDER + ["none"]},
        "multi_label_counts": dict(multi_counts),
        "type_coverage_rate": type_coverage_rate,
        "per_type_min_count": per_type_min_count,
        "shannon_entropy_bits": H,
        "shannon_entropy_normalized": H_norm,
        "gini_coefficient": gini,
    }


def main():
    data = load_all()
    out_results = []
    for meta in DATASETS:
        if meta["name"] not in data:
            continue
        r = analyze_dataset(meta["name"], data[meta["name"]])
        out_results.append(r)
        print(f"[{r['dataset']:10s}] mal_n={r['malicious_n']:4d}  "
              f"coverage={r['type_coverage_rate']*100:5.1f}%  "
              f"min_per_type={r['per_type_min_count']:3d}  "
              f"H_norm={r['shannon_entropy_normalized']:.3f}  "
              f"gini={r['gini_coefficient']:.3f}")
        print(f"    primary_counts: {r['primary_counts']}")

    out = os.path.join(ensure_reports_dir(), "e4_auto_D5.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"dimension": "D5_Attack_Type_Coverage",
                   "results": out_results}, f, ensure_ascii=False, indent=2)
    print(f"\n[D5] written {out}")


if __name__ == "__main__":
    main()
