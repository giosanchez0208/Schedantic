"""Generate a fill-in-the-blanks batch file for hand-writing corpus strings.

  uv run python scripts/make_batch.py            # next batch, 50 cells
  uv run python scripts/make_batch.py --n 25     # shorter batch
  uv run python scripts/make_batch.py --author p1

Cell assignments are weighted toward whatever COVERAGE_GAPS.md says is missing,
so filling the file is what closes the P0 rows. Write one string per line under
each heading; blank lines and # lines are ignored.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.analyze import CONSTRUCTIONS, TARGET_LIKE_REGISTERS
from stlm.ir import read_jsonl

BATCH_DIR = ROOT / "corpus" / "batches"

REGISTERS = ["informal", "phone shorthand", "institutional"]
CASINGS = ["all lowercase", "Normal Caps", "MIXED cAsInG", "ALL CAPS"]
ORDERS = ["time/day FIRST, title after", "title FIRST, time/day after",
          "time split around the title"]
LENGTHS = ["very short (under 20 chars)", "medium", "long (50+ chars)"]

# How many cells of each priority band to allocate, per 50.
BAND_MIX = {"P0": 0.40, "P1": 0.24, "P2": 0.12, "P3": 0.24}


def current_rates() -> dict[str, float]:
    """Rate of each construction across everything collected so far."""
    pool: list[str] = []
    for name in ("harvested.jsonl", "human_raw.jsonl"):
        for r in read_jsonl(ROOT / "corpus" / name):
            if name == "harvested.jsonl" and r.get("register") not in TARGET_LIKE_REGISTERS:
                continue
            if r.get("text"):
                pool.append(r["text"])
    n = len(pool) or 1
    return {cid: 100 * sum(1 for t in pool if rx.search(t)) / n
            for cid, _lbl, rx, _why, _what, _shape in CONSTRUCTIONS}


def band(rate: float) -> str:
    return "P0" if rate < 1.0 else "P1" if rate < 5.0 else "P2" if rate < 15.0 else "P3"


def next_batch_number() -> int:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(BATCH_DIR.glob("batch_*.txt"))
    return len(existing) + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--author", default="me")
    ap.add_argument("--device", default="keyboard")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    rates = current_rates()
    by_band: dict[str, list] = {"P0": [], "P1": [], "P2": [], "P3": []}
    for cid, lbl, _rx, _why, _what, shape in CONSTRUCTIONS:
        by_band[band(rates[cid])].append((cid, lbl, shape, rates[cid]))

    # Allocate slots by band, then fill from that band's constructions.
    slots: list[tuple] = []
    for b, frac in BAND_MIX.items():
        pool = by_band[b]
        if not pool:
            continue
        k = max(1, round(args.n * frac))
        for i in range(k):
            slots.append(pool[i % len(pool)])
    while len(slots) < args.n:
        pool = by_band["P3"] or by_band["P2"] or by_band["P1"] or by_band["P0"]
        slots.append(pool[len(slots) % len(pool)])
    slots = slots[: args.n]
    # Interleave so you are not writing ten COUNT strings in a row -- that is
    # how anchoring produces ten variants of the same sentence.
    rng.shuffle(slots)

    num = next_batch_number()
    path = BATCH_DIR / f"batch_{num:02d}.txt"

    L: list[str] = []
    w = L.append
    w(f"# STLM corpus batch {num:02d}")
    w(f"# author: {args.author}")
    w(f"# device: {args.device}")
    w("#")
    w("# HOW TO USE")
    w("#   Write one string per line under each '##' heading.")
    w("#   Blank lines are ignored. Lines starting with # are ignored.")
    w("#   Write what you would ACTUALLY type. Typos stay. Don't clean it up.")
    w("#   Can't think of one? Leave it blank and move on. Blank is fine.")
    w("#   Weird/unsure? Write it anyway and put ?? at the end of the line.")
    w("#")
    w("# IF SOMEONE ELSE TYPES SOME: add a line like")
    w("#   # author: p1")
    w("#   # device: phone")
    w("# and everything after it is credited to them. This is what lets us keep")
    w("# a test set written by someone other than you. One line, do not skip it.")
    w("#")
    w("# DO NOT read documentation/IR_SPEC_v0.md before writing. Knowing what the")
    w("# schema supports changes what you write, and then the corpus stops being")
    w("# evidence.")
    w("")

    for i, (cid, lbl, shape, rate) in enumerate(slots, start=1):
        reg = rng.choice(REGISTERS)
        cas = rng.choice(CASINGS)
        order = rng.choice(ORDERS)
        ln = rng.choice(LENGTHS)
        b = band(rate)
        w(f"## [{i:03d}] {lbl}   <{b}, currently {rate:.1f}%>")
        w(f"#     style: {reg} | {cas} | {order} | {ln}")
        w(f"#     shape: {shape}")
        w("")
        w("")

    w("# end of batch")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"wrote {path.relative_to(ROOT)}  ({args.n} cells, author={args.author})")
    counts: dict[str, int] = {}
    for _cid, lbl, _shape, rate in slots:
        counts[f"{band(rate)} {lbl}"] = counts.get(f"{band(rate)} {lbl}", 0) + 1
    for k, v in sorted(counts.items()):
        print(f"  {v:>3}  {k}")
    print("\nFill it in, then:  uv run python scripts/ingest_batch.py")


if __name__ == "__main__":
    main()
