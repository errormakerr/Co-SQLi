"""D2: Duplication Rate.

Exact-dup:  SHA-256 of a normalized SQL string (lowercase, whitespace
            collapsed, string literals and numerics parameterized).
Near-dup:   AST subtree Merkle hashing + Jaccard >= 0.9 over the set of
            subtree hashes, then connected-components over pairs.

For samples where sqlglot fails to produce an AST we fall back to a
token-shingle representation (3-grams over the normalized tokens) so
they can still participate in near-dup detection.

Outputs: reports/e4_auto_D2.json
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Set, Tuple

import sqlglot

from common import DATASETS, Sample, ensure_reports_dir, load_all, normalize_sql

NEAR_DUP_JACCARD = 0.9


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def exact_key(sql: str) -> str:
    return sha(normalize_sql(sql))


# ---------- AST Merkle subtree hashing -------------------------------------

def _merkle(node) -> str:
    """Hash sqlglot expression into a Merkle subtree hash."""
    t = type(node).__name__
    children = []
    # use .args so we get consistent ordering
    for key, val in node.args.items():
        if isinstance(val, list):
            for v in val:
                if hasattr(v, "args"):
                    children.append(_merkle(v))
                else:
                    children.append(f"<{key}:{v!r}>")
        elif hasattr(val, "args"):
            children.append(_merkle(val))
        else:
            children.append(f"<{key}:{val!r}>")
    return sha(t + "|" + "|".join(children))


def subtree_hashes(node) -> Set[str]:
    """Collect Merkle hashes of every subtree (bag of shapes)."""
    out = set()

    def walk(n):
        if not hasattr(n, "args"):
            return
        out.add(_merkle(n))
        for key, val in n.args.items():
            if isinstance(val, list):
                for v in val:
                    walk(v)
            else:
                walk(val)

    walk(node)
    return out


def token_shingles(sql: str, k: int = 3) -> Set[str]:
    toks = normalize_sql(sql).split()
    if len(toks) < k:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def sample_signature(sql: str) -> Set[str]:
    try:
        trees = sqlglot.parse(sql, read="mysql")
        sig: Set[str] = set()
        for t in trees:
            if t is not None:
                sig.update(subtree_hashes(t))
        if sig:
            return sig
    except Exception:
        pass
    return token_shingles(sql)


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------- Union-Find for connected components ----------------------------

class UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _to_hex(h: str) -> str:
    """Ensure a signature element is a hex digest (token shingles are not)."""
    if len(h) >= 16 and all(c in "0123456789abcdef" for c in h[:16]):
        return h
    return sha(h)


def _blocking_key(sig: Set[str], num_bands: int = 8) -> List[int]:
    """LSH-style blocking: hash each subtree-hash into a band bucket so
    we only compare signatures that share at least one band."""
    if not sig:
        return [0]
    buckets = set()
    for h in sig:
        v = int(_to_hex(h)[:16], 16)
        for b in range(num_bands):
            buckets.add((b, v % (2 ** 20 + b)))
    return list(buckets)


def analyze_dataset(name: str, samples: List[Sample]) -> dict:
    n = len(samples)
    sqls = [s.sql for s in samples]

    # --- exact duplicates ---------------------------------------------------
    exact_keys = [exact_key(s) for s in sqls]
    from collections import Counter
    ec = Counter(exact_keys)
    exact_dup_cnt = sum(c for c in ec.values() if c > 1) - len(
        [c for c in ec.values() if c > 1]
    )
    # above = total rows in dup groups minus one "canonical" per group
    exact_unique = len(ec)

    # --- near duplicates ----------------------------------------------------
    sigs = [sample_signature(s) for s in sqls]

    # LSH-style blocking
    buckets: Dict[tuple, List[int]] = {}
    for i, sig in enumerate(sigs):
        for key in _blocking_key(sig):
            buckets.setdefault(key, []).append(i)

    uf = UF(n)
    # pre-union exact-duplicates: near-dup is a superset of exact-dup
    exact_groups: Dict[str, int] = {}
    for i, k in enumerate(exact_keys):
        if k in exact_groups:
            uf.union(exact_groups[k], i)
        else:
            exact_groups[k] = i
    checked = 0
    for ids in buckets.values():
        if len(ids) < 2:
            continue
        for a_idx in range(len(ids)):
            for b_idx in range(a_idx + 1, len(ids)):
                i, j = ids[a_idx], ids[b_idx]
                if uf.find(i) == uf.find(j):
                    continue
                if jaccard(sigs[i], sigs[j]) >= NEAR_DUP_JACCARD:
                    uf.union(i, j)
                checked += 1
                if checked > 5_000_000:
                    break
            if checked > 5_000_000:
                break
        if checked > 5_000_000:
            break

    roots = {uf.find(i) for i in range(n)}
    near_unique = len(roots)
    near_dup_rate = 1 - (near_unique / n) if n else 0.0
    exact_dup_rate = 1 - (exact_unique / n) if n else 0.0

    return {
        "dataset": name,
        "n": n,
        "exact_unique": exact_unique,
        "exact_dup_rate": exact_dup_rate,
        "near_unique": near_unique,
        "near_dup_rate": near_dup_rate,
        "pairs_checked": checked,
    }


def main():
    data = load_all()
    out_results = []
    for meta in DATASETS:
        if meta["name"] not in data:
            continue
        print(f"[D2] processing {meta['name']} ...")
        r = analyze_dataset(meta["name"], data[meta["name"]])
        out_results.append(r)
        print(f"  n={r['n']}  exact_unique={r['exact_unique']}  "
              f"exact_dup_rate={r['exact_dup_rate']*100:.2f}%  "
              f"near_unique={r['near_unique']}  "
              f"near_dup_rate={r['near_dup_rate']*100:.2f}%")

    out = os.path.join(ensure_reports_dir(), "e4_auto_D2.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"dimension": "D2_Duplication_Rate",
                   "near_dup_jaccard_threshold": NEAR_DUP_JACCARD,
                   "results": out_results}, f, ensure_ascii=False, indent=2)
    print(f"\n[D2] written {out}")


if __name__ == "__main__":
    main()
