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
import re
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


def _canon_cell(x):
    """Normalize one value so 1 == 1.0 and rounding noise (gold ROUND vs model
    full precision) doesn't cause spurious mismatches."""
    if x is None:
        return "None"
    try:
        return f"{round(float(x), 2):.2f}"   # numbers: compare to 2 decimals
    except (TypeError, ValueError):
        return str(x).strip()


def _canon(df):
    """Canonical form for execution-accuracy comparison: a sorted list of rows,
    ignoring column NAMES and column ORDER (a correct answer shouldn't fail just
    because the model aliased a column or ordered columns differently)."""
    if df is None:
        return None
    rows = []
    for row in df.itertuples(index=False, name=None):
        rows.append(tuple(sorted(_canon_cell(v) for v in row)))
    return sorted(rows)


def results_match(gold_df, gen_df):
    g, h = _canon(gold_df), _canon(gen_df)
    if g is None or h is None:
        return False
    return g == h


def _gold_df(conn, sql):
    try:
        return run_query(conn, sql)
    except Exception as exc:
        print(f"    !! gold SQL failed: {exc}")
        return None


class QuotaExhausted(Exception):
    """Raised to abort when many consecutive questions get no answer (quota wall)."""


def _is_rate_limit(exc):
    """True for any 429 / rate-limit / quota error."""
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "resource_exhausted" in msg


def _retry_after(exc, default=20, floor=15, cap=70):
    """Seconds to wait before retrying, from the provider's hint (clamped). The
    floor keeps very short hints (e.g. 1.5s) from busy-looping inside a 1-min
    window that hasn't actually cleared yet."""
    m = re.search(r"retry in ([0-9.]+)s", str(exc).lower()) \
        or re.search(r"try again in ([0-9.]+)", str(exc).lower())
    if m:
        return min(cap, max(floor, int(float(m.group(1))) + 2))
    return default


def evaluate(conn, schema_text, pairs, provider, self_correct, sleep=1.0):
    """Score the model over `pairs`. Questions that never get an answer (the API
    stays rate-limited after several backoffs) are SKIPPED, not marked wrong, so
    accuracy is measured only over questions the model actually answered."""
    max_retries = 2 if self_correct else 0
    rows = []
    skipped = 0
    consec_skips = 0
    for p in pairs:
        gold_df = _gold_df(conn, p["gold_sql"])
        res = None
        for attempt in range(6):
            try:
                res = generate_and_run(
                    conn, schema_text, p["question"], provider, max_retries=max_retries
                )
                break
            except Exception as exc:
                if _is_rate_limit(exc) and attempt < 5:
                    wait = _retry_after(exc)
                    print(f"    (rate-limited at #{p['id']}; backing off {wait}s)")
                    time.sleep(wait)
                    continue
                break  # give up on this question (no answer)

        if res is None:
            skipped += 1
            consec_skips += 1
            print(f"  -- #{p['id']:>3} [{p['difficulty']:<6}] skipped (no answer / rate-limited)")
            if consec_skips >= 6:
                print(f"\n!! {provider}: 6 questions in a row got no answer — quota wall. "
                      f"Aborting; reporting accuracy over the {len(rows)} answered so far.")
                raise QuotaExhausted()
            time.sleep(sleep)
            continue

        consec_skips = 0
        correct = bool(res.success and results_match(gold_df, res.dataframe))
        rows.append({"id": p["id"], "difficulty": p["difficulty"], "correct": correct,
                     "retries": res.retries})
        mark = "OK " if correct else "XX "
        print(f"  {mark} #{p['id']:>3} [{p['difficulty']:<6}] {p['question'][:60]}")
        time.sleep(sleep)
    if skipped:
        print(f"  ({skipped} question(s) skipped for no answer — excluded from accuracy)")
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
                    help="run only the self-correction=OFF pass")
    ap.add_argument("--self-correct-only", action="store_true",
                    help="run only the self-correction=ON pass (cheapest single config)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    providers = [args.provider] if args.provider else ["gemini", "groq"]
    if args.self_correct_only:
        modes = [True]
    elif args.no_correction_only:
        modes = [False]
    else:
        modes = [True, False]

    pairs = load_benchmark(args.limit)
    conn = get_connection()
    schema_text = get_schema_text(conn)
    summary = {}
    try:
        for provider in providers:
            for self_correct in modes:
                label = f"{provider} | self-correction {'ON' if self_correct else 'OFF'}"
                print(f"\n>>> {label}  ({len(pairs)} pairs)")
                try:
                    df = evaluate(conn, schema_text, pairs, provider, self_correct, args.sleep)
                    summary[label] = summarize(df, label)
                except QuotaExhausted:
                    # Skip this provider's remaining passes; its quota is gone today.
                    print(f"   (skipping remaining {provider} passes — quota exhausted)")
                    break
    finally:
        conn.close()

    print("\n\n========= SUMMARY (execution accuracy %) =========")
    header = ["overall", *TIERS]
    print(f"{'config':<32}" + "".join(f"{h:>9}" for h in header))
    for label, stats in summary.items():
        print(f"{label:<32}" + "".join(f"{stats.get(h, float('nan')):>9.1f}" for h in header))


if __name__ == "__main__":
    main()
