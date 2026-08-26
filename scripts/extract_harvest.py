"""Extract harvested schedule strings from the workflow journal into
corpus/harvested.jsonl.

These strings are HUMAN-AUTHORED and pulled from public parser test suites and
corpora. They are NOT gold for this project -- they carry no L1/L2 labels and
their register is not the target register. They exist to answer one question:
what does real schedule text actually look like, versus what the generator
assumes it looks like.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.ir import write_jsonl

JOURNAL = sys.argv[1] if len(sys.argv) > 1 else None
if not JOURNAL:
    print("usage: extract_harvest.py <journal.jsonl>")
    sys.exit(1)

results = []
for line in pathlib.Path(JOURNAL).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "result":
        continue
    payload = d.get("result", d.get("value"))
    if isinstance(payload, dict):
        results.append(payload)

rows: list[dict] = []
seen: set[str] = set()
src_counts: dict[str, int] = {}

for res in results:
    cls = res.get("source_class", "unknown")
    for s in res.get("strings", []) or []:
        text = (s.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        row = {
            "text": text,
            "source": "harvested",
            "source_class": cls,
            "source_url": s.get("source_url", ""),
            "register": s.get("register", "unknown"),
            "verbatim": bool(s.get("verbatim", False)),
            "encodes_events": s.get("encodes_events"),
            "notes": s.get("notes", ""),
        }
        rows.append(row)
        key = s.get("source_url", "").rsplit("/", 1)[-1] or cls
        src_counts[key] = src_counts.get(key, 0) + 1

n = write_jsonl(ROOT / "corpus" / "harvested.jsonl", rows)
print(f"wrote corpus/harvested.jsonl: {n} unique strings")
print(f"  verbatim-flagged: {sum(1 for r in rows if r['verbatim'])}")
print("\nby source file:")
for k, v in sorted(src_counts.items(), key=lambda x: -x[1]):
    print(f"  {v:>5}  {k}")
print("\nby register:")
reg: dict[str, int] = {}
for r in rows:
    reg[r["register"]] = reg.get(r["register"], 0) + 1
for k, v in sorted(reg.items(), key=lambda x: -x[1]):
    print(f"  {v:>5}  {k}")
print("\nsample:")
for r in rows[:20]:
    print(f"  {r['text']!r}")
