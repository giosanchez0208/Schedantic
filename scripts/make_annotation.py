"""Emit editable L1 annotation files.

  uv run python scripts/make_annotation.py dev   --n 40
  uv run python scripts/make_annotation.py test  --n 48

DEV is pre-annotated by the rule proposer so you correct rather than type.
TEST is emitted BLANK on purpose: pre-annotating the frozen set with the same
rules that become the M5 baseline would make the baseline grade its own homework.

You never type character offsets. Write the span VALUE; ingest locates it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.ir import FLAGS, SPAN_TYPES, read_jsonl
from stlm.preannotate import with_summary

ANN_DIR = ROOT / "corpus" / "annotate"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["dev", "test"])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    splits = json.loads((ROOT / "corpus" / "splits.json").read_text(encoding="utf-8"))
    ids = set(splits[f"{args.split}_ids"])
    rows = [r for r in read_jsonl(ROOT / "corpus" / "human_raw.jsonl") if r["id"] in ids]
    rows.sort(key=lambda r: r["id"])
    chunk = rows[args.start : args.start + args.n]
    if not chunk:
        print("nothing to emit for that range")
        return

    ANN_DIR.mkdir(parents=True, exist_ok=True)
    path = ANN_DIR / f"{args.split}_{args.start:04d}_{args.start + len(chunk):04d}.txt"

    L: list[str] = []
    w = L.append
    w(f"# L1 ANNOTATION -- split={args.split}  items={len(chunk)}")
    w("#")
    w("# For each item, list its spans as:   TYPE | exact text from the line")
    w("# Delete a line to remove that span. Add a line to add one. Edit the text")
    w("# to fix a boundary. Copy the value EXACTLY as it appears, including case.")
    w("#")
    w(f"# TYPES: {' '.join(SPAN_TYPES)}")
    w("# SUMMARY is the residual -- whatever is not temporal. Spans must NOT overlap.")
    w("#")
    w("# If the same text appears twice in the line, disambiguate with an")
    w("# occurrence number:   TSTART | 8 #2      (the second '8')")
    w("#")
    w("# events: which spans belong to which event. Default is all-in-one.")
    w("#   Two events -> list the span types per event, separated by ' ; '")
    w("#   e.g.  events: RECUR#1 TSTART#1 SUMMARY ; RECUR#2 TSTART#2 SUMMARY")
    w("#")
    w("# status: ok | no_temporal | unresolvable | unrepresentable")
    w("# UNREPRESENTABLE is the important one -- use it when the schema genuinely")
    w("# cannot express the line, and say why in note:. Those drive IR v1.")
    w(f"# flags: {' '.join(FLAGS)}")
    if args.split == "test":
        w("#")
        w("# !! TEST SPLIT: intentionally NOT pre-annotated. Annotate from scratch.")
    w("")

    for r in chunk:
        w(f"=== {r['id']} [{r['author']}] ===")
        w(f"> {r['text']}")
        if args.split == "dev":
            for p in with_summary(r["text"]):
                w(f"{p.type:<9}| {p.text}")
        else:
            w("SUMMARY  | ")
        w("events: all")
        w("status: ok")
        w("flags:")
        w("note:")
        w("")

    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    pre = "pre-annotated" if args.split == "dev" else "BLANK (annotate from scratch)"
    print(f"wrote {path.relative_to(ROOT)}  ({len(chunk)} items, {pre})")
    print(f"remaining in {args.split}: {len(rows) - args.start - len(chunk)}")
    print("\nwhen done:  uv run python scripts/ingest_annotation.py")


if __name__ == "__main__":
    main()
