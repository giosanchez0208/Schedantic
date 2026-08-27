"""Score the rule baseline against annotated gold. This is the M5 measurement.

  uv run python scripts/eval_baseline.py            # dev
  uv run python scripts/eval_baseline.py --split test

Reports against the three product questions from TARGET.md, not as one blended
number: a strong SUMMARY F1 must not paper over a weak BYDAY recall.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.ir import L1, L2, Span, read_jsonl
from stlm.normalize import l1_to_l2, parse
from stlm.preannotate import with_summary
from stlm.score import l2_exact_match, rrule_equivalence, span_prf

REF = dt.datetime(2026, 8, 27, 9, 0, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    args = ap.parse_args()

    splits = json.loads((ROOT / "corpus" / "splits.json").read_text(encoding="utf-8"))
    want = (set(splits["dev_ids"]) if args.split == "dev"
            else set(splits["test_ids"]) if args.split == "test"
            else set(splits["dev_ids"]) | set(splits["test_ids"]))
    gold_rows = [r for r in read_jsonl(ROOT / "corpus" / "gold_l1.jsonl") if r["id"] in want]
    if not gold_rows:
        print(f"no annotated gold for split={args.split}")
        return

    gold_l1 = [L1.from_json(r) for r in gold_rows]
    pred_l1, gold_l2, pred_l2 = [], [], []
    for g in gold_l1:
        sp = with_summary(g.text)
        pred_l1.append(L1(
            id=g.id, text=g.text,
            spans=[Span(i=n, type=p.type, start=p.start, end=p.end, text=p.text)
                   for n, p in enumerate(sp)],
            event_groups=[[n for n, _ in enumerate(sp)]] if sp else [],
            status="ok" if sp else "no_temporal"))
        gold_l2.append(l1_to_l2(g)[0])
        pred_l2.append(parse(g.text, item_id=g.id)[0])

    print(f"=== M5 rule baseline vs gold  [split={args.split}, n={len(gold_l1)}] ===")

    # --- Q1: is it a schedule? ---------------------------------------------
    print("\nQ1  IS IT A SCHEDULE?")
    gold_sched = [g.status == "ok" for g in gold_l1]
    pred_sched = [bool(p.events) for p in pred_l2]
    correct = sum(a == b for a, b in zip(gold_sched, pred_sched))
    non = [i for i, s in enumerate(gold_sched) if not s]
    false_sched = sum(1 for i in non if pred_sched[i])
    status4 = sum(1 for g, p in zip(gold_l1, pred_l2) if g.status == p.status)
    print(f"  binary schedulable accuracy   {correct}/{len(gold_l1)} = {correct/len(gold_l1):.3f}")
    print(f"  4-way status accuracy         {status4}/{len(gold_l1)} = {status4/len(gold_l1):.3f}"
          f"   (target >= 0.90)")
    print(f"  FALSE-SCHEDULE rate           {false_sched}/{len(non)} = "
          f"{false_sched/max(1,len(non)):.3f}   (target <= 0.05)")

    # --- Q2: what goes on the calendar? ------------------------------------
    spans = span_prf(gold_l1, pred_l1)
    print("\nQ2  WHAT GOES ON THE CALENDAR?")
    smry = spans["per_type"].get("SUMMARY", {})
    print(f"  SUMMARY span F1               {smry.get('f1', 0):.3f}   (target >= 0.75)")

    # --- Q3: when? ----------------------------------------------------------
    ok_idx = [i for i, g in enumerate(gold_l1) if g.status == "ok"]
    gl2 = [gold_l2[i] for i in ok_idx]
    pl2 = [pred_l2[i] for i in ok_idx]
    m = l2_exact_match(gl2, pl2)
    r = rrule_equivalence(gl2, pl2, REF)
    print(f"\nQ3  WHEN?   [scored on the {len(ok_idx)} schedulable items]")
    print(f"  temporal exact match          {m['temporal_exact_match']:.3f}   (target >= 0.90)")
    print(f"  RRULE occurrence-set equal    {r['occurrence_set_exact']:.3f}   (target >= 0.90)")
    print(f"  mean occurrence Jaccard       {r['mean_jaccard']:.3f}")
    print(f"  whole-event exact match       {m['exact_match']:.3f}")

    print("\n--- span P/R/F1 by type ---")
    print(f"  {'type':<10}{'P':>7}{'R':>7}{'F1':>7}{'gold':>7}")
    for t, v in sorted(spans["per_type"].items(), key=lambda x: -x[1]["f1"]):
        print(f"  {t:<10}{v['p']:>7.2f}{v['r']:>7.2f}{v['f1']:>7.2f}{v['tp']+v['fn']:>7}")
    print(f"  {'MICRO':<10}{spans['micro']['p']:>7.2f}{spans['micro']['r']:>7.2f}"
          f"{spans['micro']['f1']:>7.2f}")
    print(f"  {'temporal':<10}{spans['temporal_only']['p']:>7.2f}"
          f"{spans['temporal_only']['r']:>7.2f}{spans['temporal_only']['f1']:>7.2f}")

    print("\n--- gold composition ---")
    print(f"  status  {dict(Counter(g.status for g in gold_l1))}")
    fl = Counter(f for g in gold_l1 for f in g.flags)
    print(f"  flags   {dict(fl.most_common(10))}")


if __name__ == "__main__":
    main()
