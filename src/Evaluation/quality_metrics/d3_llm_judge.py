"""D3: Label Correctness via LLM-as-judge (full-sample).

Run two independent judges on every sample's *context-free* SQL and compare
with the dataset's original label. A sample is "agreed-correct" if the
judge's verdict matches the original label. A sample is "consensus-correct"
if both judges agree AND the consensus matches the original label.

Dataset-level metric:
  correctness_rate = # agreed-correct / n
  llm_disagreement_rate = # judges-disagree / n  (escalate to human in D3-L2)

Outputs (resumable):
  reports/d3/<judge>/<dataset>.jsonl   -- one row per verdict
  reports/e4_auto_D3.json              -- aggregated rates

USAGE
-----
    python d3_llm_judge.py --judge A        # run judge A (gpt-5.1)
    python d3_llm_judge.py --judge B        # run judge B (different model)
    python d3_llm_judge.py --aggregate      # compute rates after both runs

The script NEVER echoes the API key and reads the model + endpoint from
the project's existing config/gpt_config.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

# reach the project root so we can import src.utils.LLM
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, PROJ_ROOT)

from src.utils.LLM import LLM  # noqa: E402
from src.utils.yaml_operation import load_yaml_to_dict  # noqa: E402

from common import DATASETS, ensure_reports_dir, load_all  # noqa: E402

# ---------------------------------------------------------------------------

JUDGE_PROMPT = """You are a security expert labelling SQL statements for a
SQL-injection (SQLi) benchmark.  Judge the given SQL in a **context-free**
setting (no schema information is available).

Rules
-----
1. If the SQL contains unambiguous SQLi markers (obvious tautology like
   "OR 1=1", UNION-based exfiltration, time-based sleep, stacked DROP/INSERT,
   error-based extractvalue/updatexml, SQL comment bypass "--" / "#"
   inside an ongoing clause, etc.), label "malicious".
2. If the SQL is a plain CRUD / analytic query whose intent is clearly
   legitimate application behaviour (SELECT with normal WHERE / JOIN,
   INSERT/UPDATE with literal values, no comments bypass), label "benign".
3. If the SQL is ambiguous (no strong signal either way; benign-looking
   SQL that *could* be SQLi under the right schema), label "ambiguous".

Output strictly this JSON (no other text):
{"label": "malicious" | "benign" | "ambiguous", "reason": "<<30 words"}

SQL:
<<<
{sql}
>>>
"""


def _load_cfg() -> dict:
    cfg_path = os.path.join(PROJ_ROOT, "config", "gpt_config.yaml")
    return load_yaml_to_dict(cfg_path)


def _judge_config(judge: str) -> dict:
    """Return {model, base_url, api_key} for a judge ID.

    Judge A: whatever is in gpt_config.yaml (defaults to gpt-5.1).
    Judge B: same endpoint but user-selectable second model --
            e.g. gpt-4o-2024-11-20 or claude-3-5-sonnet via a proxy.
    """
    cfg = _load_cfg()
    if judge == "A":
        return {
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "api_key": cfg["api_key"],
        }
    # Judge B: fall back to env-var override if user wants a different endpoint
    return {
        "model": os.environ.get("D3_JUDGE_B_MODEL", "gpt-4o-2024-11-20"),
        "base_url": os.environ.get("D3_JUDGE_B_BASE_URL", cfg["base_url"]),
        "api_key": os.environ.get("D3_JUDGE_B_API_KEY", cfg["api_key"]),
    }


def _out_path(judge: str, dataset: str) -> str:
    d = os.path.join(ensure_reports_dir(), "d3", f"judge_{judge}")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{dataset}.jsonl")


def _already_done(path: str) -> set:
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.add(int(json.loads(line).get("row_idx", -1)))
            except Exception:
                continue
    out.discard(-1)
    return out


def _parse_verdict(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    # tolerate markdown code fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json\n"):
            text = text[5:]
    # find first { ... }
    l = text.find("{")
    r = text.rfind("}")
    if l < 0 or r <= l:
        return None
    try:
        obj = json.loads(text[l:r + 1])
        lab = str(obj.get("label", "")).strip().lower()
        if lab in {"malicious", "benign", "ambiguous"}:
            return lab
    except Exception:
        return None
    return None


def run_judge(judge: str, dataset_name: Optional[str] = None,
              max_per_dataset: Optional[int] = None,
              workers: int = 8):
    cfg = _judge_config(judge)
    llm = LLM(api_key=cfg["api_key"], base_url=cfg["base_url"])
    model = cfg["model"]
    print(f"[judge={judge}] model={model}  (key/endpoint loaded from config)")

    data = load_all()
    for meta in DATASETS:
        if dataset_name and meta["name"] != dataset_name:
            continue
        samples = data.get(meta["name"], [])
        if max_per_dataset:
            samples = samples[:max_per_dataset]
        out = _out_path(judge, meta["name"])
        done = _already_done(out)
        todo = [s for s in samples if s.row_idx not in done]
        print(f"[{meta['name']}] samples={len(samples)}  "
              f"done={len(done)}  todo={len(todo)}  -> {out}")
        if not todo:
            continue

        prompts = [JUDGE_PROMPT.replace("{sql}", s.sql) for s in todo]
        # batch_generate already handles retries + thread pool
        results = llm.batch_generate(
            prompts=prompts,
            model=model,
            temperature=0.0,
            max_tokens=200,
            max_workers=workers,
        )

        with open(out, "a", encoding="utf-8") as f:
            for s, res in zip(todo, results):
                text = res.get("response") if isinstance(res, dict) else res
                verdict = _parse_verdict(text)
                rec = {
                    "dataset": meta["name"],
                    "row_idx": s.row_idx,
                    "orig_label": s.label,
                    "verdict": verdict,
                    "raw": (text or "")[:500],
                    "judge": judge,
                    "model": model,
                    "ts": int(time.time()),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  [{meta['name']}] wrote {len(todo)} verdicts")


def aggregate():
    """Compute per-dataset correctness_rate and llm-llm agreement."""
    out = {"dimension": "D3_Label_Correctness",
           "per_dataset": []}
    for meta in DATASETS:
        name = meta["name"]
        vA = _load_verdicts(_out_path("A", name))
        vB = _load_verdicts(_out_path("B", name))
        common = set(vA) & set(vB)
        n = len(common)
        agreed_correct = 0
        both_agree = 0
        consensus_correct = 0
        for k in common:
            orig = vA[k]["orig_label"]
            # map to the judge vocabulary
            expected = {"mal": "malicious", "ben": "benign"}.get(orig)
            a_lab = vA[k]["verdict"]
            b_lab = vB[k]["verdict"]
            if a_lab == b_lab and a_lab is not None:
                both_agree += 1
                if expected is not None and a_lab == expected:
                    consensus_correct += 1
            if expected is not None and a_lab == expected:
                agreed_correct += 1
        out["per_dataset"].append({
            "dataset": name,
            "n_common": n,
            "judge_agree_rate": both_agree / n if n else 0.0,
            "consensus_correct_rate": consensus_correct / n if n else 0.0,
            "judgeA_correct_rate": agreed_correct / n if n else 0.0,
            "n_judgeA_only": len(set(vA) - set(vB)),
            "n_judgeB_only": len(set(vB) - set(vA)),
        })
        print(f"[{name}] n_common={n}  "
              f"judgeA_correct={agreed_correct/n*100:.2f}%  "
              f"judges_agree={both_agree/n*100:.2f}%  "
              f"consensus_correct={consensus_correct/n*100:.2f}%"
              if n else f"[{name}] n_common=0")

    path = os.path.join(ensure_reports_dir(), "e4_auto_D3.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[D3] written {path}")


def _load_verdicts(path: str) -> Dict[int, dict]:
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if "row_idx" in r:
                    out[int(r["row_idx"])] = r
            except Exception:
                continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", choices=["A", "B"], default=None)
    ap.add_argument("--dataset", default=None,
                    help="only run one dataset (e.g. SQLiV3)")
    ap.add_argument("--max-per-dataset", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--aggregate", action="store_true")
    args = ap.parse_args()

    if args.aggregate:
        aggregate()
        return
    if args.judge is None:
        ap.error("--judge A|B required unless --aggregate is passed")
    run_judge(args.judge, args.dataset, args.max_per_dataset, args.workers)


if __name__ == "__main__":
    main()
