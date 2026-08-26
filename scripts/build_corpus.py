"""Build the synthetic corpus and run the full analysis.

Usage: uv run --with python-dateutil --with icalendar python scripts/build_corpus.py [N]
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.analyze import analyze_labelled, analyze_raw, coverage, gap_vs_reality
from stlm.generate import generate
from stlm.ir import read_jsonl, write_jsonl

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
SEED = 1337

print(f"generating {N} balanced + {N // 2} realistic examples (seed={SEED}) ...")
rows = generate(N, seed=SEED, profile="balanced")
real_rows = generate(N // 2, seed=SEED + 1, profile="realistic")
n = write_jsonl(ROOT / "corpus" / "synthetic_balanced.jsonl", rows)
m = write_jsonl(ROOT / "corpus" / "synthetic_realistic.jsonl", real_rows)
print(f"  wrote corpus/synthetic_balanced.jsonl ({n} rows)")
print(f"  wrote corpus/synthetic_realistic.jsonl ({m} rows)")

syn = analyze_labelled(rows, "synthetic_balanced")
syn_real = analyze_labelled(real_rows, "synthetic_realistic")
cov = coverage(rows)
cov_real = coverage(real_rows)
out = {"synthetic_balanced": syn, "synthetic_realistic": syn_real,
       "coverage_balanced": cov, "coverage_realistic": cov_real}

# The harvest is heterogeneous. rrule.js's "Every week on Sunday at 10, 12 and 17"
# is human-authored but machine-register; a student forum's "M: 11:45-5" is the
# actual target. Pooling them would average away the only signal that matters, so
# analyse the target-like subset separately and treat IT as the reality anchor.
TARGET_LIKE = {
    "informal", "real-user-terse", "institutional", "event-title+datetime",
    "terse-time-range", "terse-date-dialect", "terse-time", "terse-datetime",
}

harvested = read_jsonl(ROOT / "corpus" / "harvested.jsonl")
if harvested:
    texts = [h["text"] for h in harvested if h.get("text")]
    tgt = [h["text"] for h in harvested
           if h.get("text") and h.get("register") in TARGET_LIKE]
    raw_all = analyze_raw(texts, "harvested_all")
    raw_tgt = analyze_raw(tgt, "harvested_target_like")
    out["harvested_all"] = raw_all
    out["harvested_target_like"] = raw_tgt
    out["gap_vs_reality"] = gap_vs_reality(syn_real, raw_tgt)
    out["gap_vs_reality_allharvest"] = gap_vs_reality(syn_real, raw_all)
    print(f"  analysed {len(texts)} harvested strings ({len(tgt)} target-like)")
else:
    print("  no corpus/harvested.jsonl yet -- skipping reality comparison")

# Self-comparison: run the same regex probes over the synthetic text so the
# probe-vs-gold delta tells us how much to trust the probes on unlabelled text.
syn_texts = [r["l1"]["text"] for r in rows]
out["synthetic_via_same_probes"] = analyze_raw(syn_texts, "synthetic (regex probes)")

path = ROOT / "corpus" / "analysis.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"  wrote corpus/analysis.json")

print("\n=== length (synthetic) ===")
print(json.dumps(syn["length"]["bytes"], indent=2))
print(f"byte/char inflation: {syn['length']['byte_char_inflation']}")
print(f"strings with non-ASCII: {syn['length']['pct_strings_with_nonascii']}%")

print("\n=== flags: balanced vs realistic (% of strings) ===")
keys = sorted(set(syn["flag_pct"]) | set(syn_real["flag_pct"]),
              key=lambda k: -syn_real["flag_pct"].get(k, 0))
print(f"  {'flag':<22} {'balanced':>10} {'realistic':>10}")
for k in keys:
    print(f"  {k:<22} {syn['flag_pct'].get(k, 0):>9}% {syn_real['flag_pct'].get(k, 0):>9}%")

print("\n=== span types (% of strings containing at least one) ===")
print(f"  {'span':<12} {'balanced':>10} {'realistic':>10}")
for k in sorted(set(syn["span_type_pct_of_strings"]) | set(syn_real["span_type_pct_of_strings"]),
                key=lambda k: -syn_real["span_type_pct_of_strings"].get(k, 0)):
    print(f"  {k:<12} {syn['span_type_pct_of_strings'].get(k, 0):>9}% "
          f"{syn_real['span_type_pct_of_strings'].get(k, 0):>9}%")

print(f"\n=== multi-event: balanced {syn['multi_event_pct']}% | "
      f"realistic {syn_real['multi_event_pct']}% ===")

print(f"\n=== coverage: {cov['n_empty']} EMPTY cells, {len(cov['gaps'])} thin-or-empty ===")
for g in cov["gaps"][:25]:
    print(f"  {g['count']:>5}  {g['pct']:>6}%  [{g['kind']}] {g['axis']}: {g['cell']}")

if "gap_vs_reality" in out:
    print("\n=== length: synthetic vs harvested(target-like) ===")
    print(f"  synthetic  bytes p50={syn_real['length']['bytes']['p50']} "
          f"p90={syn_real['length']['bytes']['p90']} p99={syn_real['length']['bytes']['p99']} "
          f"max={syn_real['length']['bytes']['max']}")
    hb = out["harvested_target_like"]["length"]["bytes"]
    print(f"  harvested  bytes p50={hb['p50']} p90={hb['p90']} p99={hb['p99']} max={hb['max']}")
    print(f"  harvested non-ASCII strings: "
          f"{out['harvested_target_like']['length']['pct_strings_with_nonascii']}%")

    print("\n=== casing: synthetic vs harvested(target-like) ===")
    print(f"  synthetic: {syn_real['casing_pct']}")
    print(f"  harvested: {out['harvested_target_like']['casing_pct']}")

    print("\n=== probe rates: harvested(target-like) vs harvested(all) ===")
    a = out["harvested_target_like"]["probe_rates_pct"]
    b = out["harvested_all"]["probe_rates_pct"]
    print(f"  {'probe':<32} {'target-like':>12} {'all':>8}")
    for k in a:
        print(f"  {k:<32} {a[k]:>11}% {b[k]:>7}%")

    print("\n=== GAP: synthetic(realistic) vs harvested(target-like) ===")
    for g in out["gap_vs_reality"]:
        print(f"  {g['feature']:<22} harvested={g['harvested_pct']:>6}%  "
              f"synthetic={g['synthetic_pct']:>6}%  delta={g['delta_pp']:>+7}pp  {g['verdict']}")
