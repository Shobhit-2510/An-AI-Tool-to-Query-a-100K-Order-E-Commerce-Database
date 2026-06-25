"""Execution-accuracy harness for the text-to-SQL assistant.

For each benchmark pair we run the GOLD SQL and the MODEL-generated SQL, then
compare the result sets order-insensitively. A match counts as correct. We sweep
{gemini, groq} x {self-correction on, off} and print accuracy overall and by
difficulty tier, plus the deltas.

    python eval/run_eval.py                 # all providers, both modes
    python eval/run_eval.py --provider gemini
    python eval/run_eval.py --limit 20      # first 20 pairs (quick smoke test)

Free-tier friendly: a small sleep + 429 retry keeps us under rate limits.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import get_connection
from execute import generate_and_run, run_query
from schema import get_schema_text

BENCHMARK = Path(__file__).resolve().parent / "benchmark.jsonl"
TIERS = ("easy", "medium", "hard")


def load_benchmark(limit=None):
    pairs = []
    with open(BENCHMARK, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))
    return pairs[:limit] if limit else pairs


def _normalize(df):
    """Canonical form for order-insensitive comparison: sort columns, stringify
    cells (so 1 == 1.0), then sort rows."""
    if df is None:
        return None
    d = df.copy()
    d.columns = [str(c) for c in d.columns]
    d = d[sorted(d.columns)]
    d = d.astype(str)
    d = d.sort_values(by=list(d.columns)).reset_index(drop=True)
    return d


def results_match(gold_df, gen_df):
    g, h = _normalize(gold_df), _normalize(gen_df)
    if g is None or h is None:
        return False
    if g.shape != h.shape:
        return False
    return g.equals(h)


def _gold_df(conn, sql):
    try:
        return run_query(conn, sql)
    except Exception as exc:
        print(f"    !! gold SQL failed: {exc}")
        return None


def evaluate(conn, schema_text, pairs, provider, self_correct, sleep=1.0):
    max_retries = 2 if self_correct else 0
    rows = []
    for p in pairs:
        gold_df = _gold_df(conn, p["gold_sql"])
        # Retry once on a rate-limit error to stay within free tiers.
        for attempt in range(2):
            try:
                res = generate_and_run(
                    conn, schema_text, p["question"], provider, max_retries=max_retries
                )
                break
            except Exception as exc:
                if "429" in str(exc) and attempt == 0:
                    print("    (rate limited; backing off 20s)")
                    time.sleep(20)
                    continue
                res = None
                break

        correct = bool(res and res.success and results_match(gold_df, res.dataframe))
        rows.append({"id": p["id"], "difficulty": p["difficulty"], "correct": correct,
                     "retries": res.retries if res else 0})
        mark = "OK " if correct else "XX "
        print(f"  {mark} #{p['id']:>3} [{p['difficulty']:<6}] {p['question'][:60]}")
        time.sleep(sleep)
    return pd.DataFrame(rows)


def summarize(df, label):
    print(f"\n=== {label} ===")
    overall = df["correct"].mean() * 100
    print(f"  overall: {overall:5.1f}%  ({df['correct'].sum()}/{len(df)})")
    by_tier = {}
    for tier in TIERS:
        sub = df[df["difficulty"] == tier]
        if len(sub):
            acc = sub["correct"].mean() * 100
            by_tier[tier] = acc
            print(f"    {tier:<6}: {acc:5.1f}%  ({sub['correct'].sum()}/{len(sub)})")
    return {"overall": overall, **by_tier}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "groq"], default=None,
                    help="default: run both")
    ap.add_argument("--no-correction-only", action="store_true",
                    help="skip the self-correction=ON pass")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    providers = [args.provider] if args.provider else ["gemini", "groq"]
    modes = [False] if args.no_correction_only else [True, False]

    pairs = load_benchmark(args.limit)
    conn = get_connection()
    schema_text = get_schema_text(conn)
    summary = {}
    try:
        for provider in providers:
            for self_correct in modes:
                label = f"{provider} | self-correction {'ON' if self_correct else 'OFF'}"
                print(f"\n>>> {label}  ({len(pairs)} pairs)")
                df = evaluate(conn, schema_text, pairs, provider, self_correct, args.sleep)
                summary[label] = summarize(df, label)
    finally:
        conn.close()

    print("\n\n========= SUMMARY (execution accuracy %) =========")
    header = ["overall", *TIERS]
    print(f"{'config':<32}" + "".join(f"{h:>9}" for h in header))
    for label, stats in summary.items():
        print(f"{label:<32}" + "".join(f"{stats.get(h, float('nan')):>9.1f}" for h in header))


if __name__ == "__main__":
    main()
