"""Audit the hand-written corpus before committing to annotation.

Annotating 200 strings is expensive. This checks first whether they are worth
annotating: distinct enough, representable in the IR, and not secretly 40 copies
of the same sentence.
"""

from __future__ import annotations

import difflib
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.analyze import CONSTRUCTIONS
from stlm.ir import read_jsonl

rows = read_jsonl(ROOT / "corpus" / "human_raw.jsonl")
texts = [r["text"] for r in rows]
N = len(rows)
print(f"corpus: {N} strings from {len(set(r['author'] for r in rows))} authors\n")


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


# --- 1. near-duplicate clustering -------------------------------------------
print("=" * 70)
print("1. NEAR-DUPLICATES  (are 207 strings really 207 distinct things?)")
clusters: list[list[int]] = []
assigned = {}
for i in range(N):
    if i in assigned:
        continue
    grp = [i]
    assigned[i] = len(clusters)
    for j in range(i + 1, N):
        if j in assigned:
            continue
        if difflib.SequenceMatcher(None, norm(texts[i]), norm(texts[j])).ratio() > 0.80:
            grp.append(j)
            assigned[j] = len(clusters)
    clusters.append(grp)
multi = [g for g in clusters if len(g) > 1]
dup_strings = sum(len(g) - 1 for g in multi)
print(f"  {len(clusters)} distinct clusters at 0.80 similarity")
print(f"  {dup_strings} strings are near-copies of another ({100*dup_strings/N:.1f}%)")
print(f"  effective distinct corpus size: ~{len(clusters)}")
for g in sorted(multi, key=lambda g: -len(g))[:6]:
    print(f"    cluster of {len(g)}:")
    for k in g[:4]:
        print(f"       [{rows[k]['author']:<6}] {texts[k]!r}")

# --- 2. degenerate strings ---------------------------------------------------
print("\n" + "=" * 70)
print("2. DEGENERATE  (too short / no temporal content at all)")
HAS_TIME = re.compile(r"\d")
degen = [r for r in rows if len(r["text"]) < 8 or not HAS_TIME.search(r["text"])]
print(f"  {len(degen)} suspicious ({100*len(degen)/N:.1f}%)")
for r in degen[:10]:
    print(f"    [{r['author']:<6}] {r['text']!r}")

# --- 3. lexical diversity ----------------------------------------------------
print("\n" + "=" * 70)
print("3. LEXICAL DIVERSITY")
toks = [t for s in texts for t in re.findall(r"[a-z]+", s.lower())]
print(f"  {len(toks)} word tokens, {len(set(toks))} types  (TTR {len(set(toks))/len(toks):.3f})")
content = [t for t in toks if t not in {
    "at", "on", "in", "the", "for", "with", "w", "and", "to", "a", "of", "every", "my"}]
print("  most common content words:")
for wd, c in Counter(content).most_common(12):
    print(f"    {c:>4}  {wd}")

# --- 4. do strings match the cell they were written for? --------------------
print("\n" + "=" * 70)
print("4. CELL-CLAIM MISMATCH  (string written under a cell it doesn't satisfy)")
probe_by_label = {lbl: rx for _cid, lbl, rx, _w, _wh, _sh in CONSTRUCTIONS}
mismatch = []
for r in rows:
    lbl = r.get("cell_label")
    if not lbl:
        continue
    rx = probe_by_label.get(lbl)
    if rx and not rx.search(r["text"]):
        mismatch.append(r)
labelled = [r for r in rows if r.get("cell_label")]
print(f"  {len(mismatch)}/{len(labelled)} labelled strings fail their own cell probe "
      f"({100*len(mismatch)/max(1,len(labelled)):.1f}%)")
print("  (some of this is probe imprecision, not contributor error)")
for r in mismatch[:8]:
    print(f"    [{r['author']:<6}] {r['text']!r}")
    print(f"             cell was: {r['cell_label']}")

# --- 5. constructions the IR may not represent -------------------------------
print("\n" + "=" * 70)
print("5. REPRESENTABILITY RISKS  (things IR_SPEC_v0 has no slot for)")
RISKS = {
    "two time ranges on one day": re.compile(r"\d\s*[-–]\s*\d.*?[,;].*?\d\s*[-–]\s*\d"),
    "date RANGE (Oct 21-23)": re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{1,2}\s*[-–]\s*\d{1,2}", re.I),
    "'same as <day>' backreference": re.compile(r"\bsame as\b", re.I),
    "vague/hedged time": re.compile(r"\b(morning|afternoon|evening|night|noonish|ish|sometime|around|maybe|before|after)\b", re.I),
    "open-ended 'onwards/starting'": re.compile(r"\b(onwards?|starting|from now|indefinitely)\b", re.I),
    "negation needing EXDATE": re.compile(r"\bexcept\b.*\b(holiday|break|exam|sem|when|if)", re.I),
    "conditional / non-committal": re.compile(r"\b(if|unless|when i|whenever|might|probably)\b", re.I),
    "no-event statement": re.compile(r"\bno class\b|\bcancelled\b|\bfree\b", re.I),
    "duration w/o start": re.compile(r"^\s*(for|about)\s+\d+\s*(hr|hour|min)", re.I),
    "count + until together": re.compile(r"(for \d+ weeks?|x\d+).*(until|till|thru)|((until|till|thru).*(for \d+ weeks?|x\d+))", re.I),
}
total_risky = set()
for name, rx in RISKS.items():
    hits = [r for r in rows if rx.search(r["text"])]
    if not hits:
        continue
    total_risky.update(id(h) for h in hits)
    print(f"\n  {name}: {len(hits)} ({100*len(hits)/N:.1f}%)")
    for h in hits[:4]:
        print(f"      [{h['author']:<6}] {h['text']!r}")
print(f"\n  strings touching >=1 representability risk: {len(total_risky)} "
      f"({100*len(total_risky)/N:.1f}%)")

# --- 6. per-author profile ---------------------------------------------------
print("\n" + "=" * 70)
print("6. PER-AUTHOR PROFILE")
print(f"  {'author':<8} {'n':>4} {'distinct':>9} {'anchored':>9} {'p50 bytes':>10}")
for a in sorted(set(r["author"] for r in rows)):
    ar = [r for r in rows if r["author"] == a]
    ac = {assigned[i] for i, r in enumerate(rows) if r["author"] == a}
    anc = sum(1 for r in ar if r.get("prompt_anchored"))
    b = sorted(len(r["text"].encode()) for r in ar)
    print(f"  {a:<8} {len(ar):>4} {len(ac):>9} {anc:>8}  {b[len(b)//2]:>9}")
