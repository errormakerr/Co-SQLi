"""Aggregate expert annotations into D3 / D4(α̂) / D5 precision metrics.

Reads `expert_audit.db` and emits:
    reports/expert_audit_summary.json   -- top-level metrics
    reports/expert_audit_disagree.jsonl -- rows where experts disagree on Q1
    reports/expert_audit_per_dataset.json -- per-dataset breakdown

Concretely
----------
* D3  Label Correctness -- for samples with >=2 annotations, agreement
                           between experts' Q1 and the dataset's orig_label.
                           Reports per dataset: n, correct_rate, 95% CI.
* D4  α̂ ambiguity ratio -- fraction of samples the expert panel marks as
                           schema-dependent (Q1 in {mal,ben} AND Q2 == 'yes').
                           Per dataset: α̂ + 95% binomial CI; also
                           T1_accuracy_ceiling = 1 - α̂/2.
* D5  Attack-type precision -- for samples the *dataset* labelled malicious
                           AND experts agree are malicious, compare our D5
                           auto-classifier's primary class against Q3.
                           (Requires rerunning d5_attack_coverage.classify()
                           locally on the sample SQLs.)
* Cohen's κ between expert pairs on Q1 (mal vs ben collapsed from 4-way).

Majority rule
-------------
When >=2 experts annotate a sample, majority verdict = mode of Q1. Ties go
to "ambiguous" (documented and rare).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "expert_audit.db")

# re-use the D5 regex bank to assign auto attack-class
PARENT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PARENT, "quality_metrics"))
try:
    from d5_attack_coverage import classify as d5_classify, primary_label  # noqa
    _D5_OK = True
except Exception as e:
    print(f"[warn] could not import d5: {e}")
    _D5_OK = False

REPORTS_DIR = os.path.join(PARENT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# stats helpers

def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def cohens_kappa(a: List[str], b: List[str]) -> float:
    """Simple 2+-way unweighted Cohen's κ."""
    assert len(a) == len(b)
    if not a:
        return float("nan")
    cats = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    mat = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        mat[idx[x]][idx[y]] += 1
    total = sum(sum(r) for r in mat)
    if total == 0:
        return float("nan")
    obs = sum(mat[i][i] for i in range(k)) / total
    marg_a = [sum(mat[i]) / total for i in range(k)]
    marg_b = [sum(mat[j][i] for j in range(k)) / total for i in range(k)]
    exp = sum(marg_a[i] * marg_b[i] for i in range(k))
    if abs(1 - exp) < 1e-12:
        return 1.0
    return (obs - exp) / (1 - exp)


# ---------------------------------------------------------------------------

def load_annotations() -> Tuple[list, list]:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    samples = [dict(r) for r in c.execute(
        "SELECT * FROM samples").fetchall()]
    ann = [dict(r) for r in c.execute(
        """SELECT a.*, e.display_name AS expert_name
           FROM annotations a JOIN experts e USING(expert_id)""").fetchall()]
    c.close()
    return samples, ann


def majority(qs: List[str]) -> str:
    if not qs:
        return "none"
    cnt = Counter(qs)
    top, n = cnt.most_common(1)[0]
    # tie?
    same = [k for k, v in cnt.items() if v == n]
    if len(same) > 1:
        return "ambiguous"
    return top


def aggregate():
    samples, ann = load_annotations()
    print(f"[load] samples={len(samples)}  annotations={len(ann)}  "
          f"experts={len({a['expert_id'] for a in ann})}")

    by_sample: Dict[int, list] = defaultdict(list)
    for a in ann:
        by_sample[a["sample_id"]].append(a)

    per_dataset = defaultdict(lambda: {
        "n_samples": 0,
        "n_annotated": 0,
        "n_majority_mal": 0,
        "n_majority_ben": 0,
        "n_majority_ambig": 0,
        "n_majority_invalid": 0,
        "n_schema_dep": 0,        # Q1 in {mal,ben} AND Q2 == 'yes'
        "n_correct_vs_orig": 0,   # majority Q1 matches orig_label
        "n_correct_denom": 0,     # samples where orig is mal/ben and majority is mal/ben
        "n_d5_tp": 0,
        "n_d5_fp": 0,
    })

    disagree_rows = []

    for s in samples:
        d = per_dataset[s["dataset"]]
        d["n_samples"] += 1
        rs = by_sample.get(s["sample_id"], [])
        if not rs:
            continue
        d["n_annotated"] += 1

        qs = [r["q1_verdict"] for r in rs]
        mj = majority(qs)
        if mj == "mal":      d["n_majority_mal"] += 1
        elif mj == "ben":    d["n_majority_ben"] += 1
        elif mj == "ambiguous": d["n_majority_ambig"] += 1
        elif mj == "invalid":   d["n_majority_invalid"] += 1

        # track disagreement
        if len(set(qs)) > 1 and len(rs) >= 2:
            disagree_rows.append({
                "sample_id": s["sample_id"],
                "dataset": s["dataset"],
                "row_idx": s["row_idx"],
                "sql": s["sql"],
                "orig_label": s["orig_label"],
                "verdicts": [{"expert": r["expert_name"],
                              "q1": r["q1_verdict"],
                              "q2": r["q2_flipping"],
                              "q3": r["q3_attacks"],
                              "notes": r["notes"]} for r in rs],
            })

        # D4 α̂: majority "mal" or "ben" AND any expert says Q2=yes counts
        # (conservative: require majority Q2=yes when >=2 annotators)
        q2s = [r["q2_flipping"] for r in rs if r["q2_flipping"]]
        if mj in {"mal", "ben"} and q2s:
            yes = sum(1 for q in q2s if q == "yes")
            if yes > len(q2s) / 2:
                d["n_schema_dep"] += 1

        # D3 correctness: orig_label vs majority verdict
        orig = s["orig_label"]  # 'mal' / 'ben' / 'other'
        if orig in {"mal", "ben"} and mj in {"mal", "ben"}:
            d["n_correct_denom"] += 1
            if mj == orig:
                d["n_correct_vs_orig"] += 1

        # D5 precision: sample originally malicious, majority confirms mal,
        # and we can recover the auto primary class vs Q3 multi-hot
        if _D5_OK and orig == "mal" and mj == "mal":
            auto_primary = primary_label(d5_classify(s["sql"]))
            # union of expert Q3 picks (any of them counts as "expert-claimed")
            expert_classes = set()
            for r in rs:
                if r["q3_attacks"]:
                    try:
                        expert_classes.update(json.loads(r["q3_attacks"]))
                    except Exception:
                        pass
            if auto_primary != "none" and auto_primary in expert_classes:
                d["n_d5_tp"] += 1
            else:
                d["n_d5_fp"] += 1

    # compute κ between each pair of experts on samples both annotated
    all_experts = sorted({a["expert_id"] for a in ann})
    kappa_pairs = {}
    for i, e1 in enumerate(all_experts):
        for e2 in all_experts[i + 1:]:
            pair_a, pair_b = [], []
            for rs in by_sample.values():
                m1 = next((r for r in rs if r["expert_id"] == e1), None)
                m2 = next((r for r in rs if r["expert_id"] == e2), None)
                if m1 and m2:
                    pair_a.append(m1["q1_verdict"])
                    pair_b.append(m2["q1_verdict"])
            if pair_a:
                kappa_pairs[f"{e1}-{e2}"] = {
                    "n": len(pair_a),
                    "kappa": cohens_kappa(pair_a, pair_b),
                }

    # final per-dataset summary
    out = {"per_dataset": []}
    for name, d in per_dataset.items():
        n = d["n_annotated"]
        k_mal_ben = d["n_majority_mal"] + d["n_majority_ben"]
        alpha_hat = (d["n_schema_dep"] / k_mal_ben) if k_mal_ben else 0.0
        a_lo, a_hi = wilson_ci(d["n_schema_dep"], k_mal_ben)
        correct_rate = (d["n_correct_vs_orig"] / d["n_correct_denom"]
                        if d["n_correct_denom"] else 0.0)
        c_lo, c_hi = wilson_ci(d["n_correct_vs_orig"], d["n_correct_denom"])
        d5_total = d["n_d5_tp"] + d["n_d5_fp"]
        d5_prec = (d["n_d5_tp"] / d5_total) if d5_total else None
        out["per_dataset"].append({
            "dataset": name,
            "n_samples": d["n_samples"],
            "n_annotated": n,
            "majority_counts": {
                "mal": d["n_majority_mal"],
                "ben": d["n_majority_ben"],
                "ambiguous": d["n_majority_ambig"],
                "invalid": d["n_majority_invalid"],
            },
            "alpha_hat": alpha_hat,
            "alpha_hat_ci95": [a_lo, a_hi],
            "T1_accuracy_ceiling": 1 - alpha_hat / 2,
            "label_correctness_rate": correct_rate,
            "label_correctness_ci95": [c_lo, c_hi],
            "d5_auto_precision": d5_prec,
            "d5_auto_tp": d["n_d5_tp"],
            "d5_auto_fp": d["n_d5_fp"],
        })

    out["kappa_pairwise_q1"] = kappa_pairs
    out["n_disagreement_samples"] = len(disagree_rows)

    with open(os.path.join(REPORTS_DIR, "expert_audit_summary.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPORTS_DIR, "expert_audit_disagree.jsonl"),
              "w", encoding="utf-8") as f:
        for row in disagree_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n[write] reports/expert_audit_summary.json "
          f"+ expert_audit_disagree.jsonl ({len(disagree_rows)} rows)")


if __name__ == "__main__":
    aggregate()
