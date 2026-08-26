"""Generate a fill-in-the-blanks batch file for hand-writing corpus strings.

  uv run python scripts/make_batch.py               # next batch, 50 cells
  uv run python scripts/make_batch.py --n 25
  uv run python scripts/make_batch.py --author kylar --device phone

Batch composition follows the three product questions, not just the construction
inventory:

  Q1 "is it a schedule?"  -> NEGATIVE cells. Strings that must NOT produce an
                             event. Batch 01 had zero of these, so question 1 has
                             a threshold in TARGET.md and no human data to measure
                             it against. Highest-priority gap in the corpus.
  Q2 "what goes on it?"   -> DOMAIN assignment. Batch 01 was 22% about the gym;
                             a domain per cell forces event variety.
  Q3 "when?"              -> the construction inventory, weighted toward whatever
                             COVERAGE_GAPS.md says is thin.

Cells describe the SHAPE of what to write, never a copyable example string --
batch 01 came back 26.6% prompt-anchored because the prompts contained literal
strings people copied.
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

# Vocabulary diversity. Batch 01 defaulted hard to the gym; naming a domain per
# cell is what stops the SUMMARY vocabulary collapsing to five words.
DOMAINS = [
    "school / classes", "work / meetings", "health / appointments",
    "family / home", "church / faith", "sports / fitness",
    "errands / chores", "friends / social", "hobby / lessons",
    "travel / commute", "money / admin", "food / cooking",
    "pets", "volunteering", "side hustle",
]

# Q1 negative cells. These are what the corpus has none of.
NEGATIVE_KINDS = [
    ("lookalike-weekday",
     "A normal message that happens to contain a weekday word used NON-temporally. "
     "Think of days that are also names, verbs, or parts of other words.",
     "Must NOT be schedulable."),
    ("lookalike-month",
     "A normal message containing a month name used NON-temporally -- as a person's "
     "name, a verb, or an ordinary noun.",
     "Must NOT be schedulable."),
    ("lookalike-number",
     "A message with numbers in it that are NOT times -- prices, counts, room "
     "numbers on their own, scores, ages.",
     "Must NOT be schedulable."),
    ("chat-filler",
     "Something you'd actually send in a group chat that carries no scheduling "
     "information whatsoever. Replies, acknowledgements, reactions.",
     "Must NOT be schedulable."),
    ("cancellation",
     "A message about a schedule that CANCELS or negates rather than creating one.",
     "Must NOT create an event."),
    ("question-about-time",
     "A question about when something is, rather than a statement scheduling it.",
     "Must NOT create an event."),
]

# Q1 middle band: real events that cannot be pinned down.
UNDERSPECIFIED_KINDS = [
    ("vague-when",
     "A real event with a time reference so vague no specific slot could be chosen.",
     "Should be flagged unresolvable, not guessed."),
    ("conditional",
     "A recurring event with a condition attached that a calendar cannot express.",
     "Should be flagged unrepresentable."),
]

BAND_MIX = {"P0": 0.40, "P1": 0.24, "P2": 0.12, "P3": 0.24}

# Of every 50 cells: 14 negatives, 4 underspecified, 32 positive schedules.
N_NEGATIVE, N_UNDERSPEC = 14, 4


def current_rates() -> dict[str, float]:
    pool: list[str] = []
    for name in ("harvested.jsonl", "human_raw.jsonl"):
        for r in read_jsonl(ROOT / "corpus" / name):
            if name == "harvested.jsonl" and r.get("register") not in TARGET_LIKE_REGISTERS:
                continue
            if r.get("text"):
                pool.append(r["text"])
    n = len(pool) or 1
    return {cid: 100 * sum(1 for t in pool if rx.search(t)) / n
            for cid, _l, rx, _w, _wh, _sh in CONSTRUCTIONS}


def band(rate: float) -> str:
    return "P0" if rate < 1.0 else "P1" if rate < 5.0 else "P2" if rate < 15.0 else "P3"


def next_batch_number() -> int:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    return len(sorted(BATCH_DIR.glob("batch_*.txt"))) + 1


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

    scale = args.n / 50
    n_neg = max(1, round(N_NEGATIVE * scale))
    n_und = max(1, round(N_UNDERSPEC * scale))
    n_pos = max(1, args.n - n_neg - n_und)

    # Cap any single construction. Without this, a band containing exactly one
    # construction absorbs that band's whole allocation -- 13 holiday cells out
    # of 32, which trades one coverage hole for another.
    cap = max(2, round(n_pos * 0.12))
    used: dict[str, int] = {}
    slots: list[tuple] = []

    def take(pool, budget):
        i = 0
        added = 0
        while added < budget and pool:
            cid, lbl, shape, rate = pool[i % len(pool)]
            i += 1
            if used.get(cid, 0) >= cap:
                if all(used.get(c[0], 0) >= cap for c in pool):
                    return added
                continue
            used[cid] = used.get(cid, 0) + 1
            slots.append(("schedule", lbl, shape, band(rate), rate))
            added += 1
        return added

    for b, frac in BAND_MIX.items():
        take(by_band[b], max(1, round(n_pos * frac)))
    # Whatever the caps left over goes to the thinnest constructions still open.
    leftovers = sorted((c for bs in by_band.values() for c in bs), key=lambda c: c[3])
    take(leftovers, n_pos - len(slots))
    slots = slots[:n_pos]

    for i in range(n_neg):
        _k, shape, note = NEGATIVE_KINDS[i % len(NEGATIVE_KINDS)]
        slots.append(("negative", "NOT a schedule", shape, "Q1", note))
    for i in range(n_und):
        _k, shape, note = UNDERSPECIFIED_KINDS[i % len(UNDERSPECIFIED_KINDS)]
        slots.append(("underspecified", "Cannot be pinned down", shape, "Q1", note))

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
    w("# THREE KINDS OF CELL IN THIS BATCH:")
    w("#   [SCHEDULE]  a normal schedule string")
    w("#   [NOT-A-SCHEDULE]  a message that must NOT become a calendar event.")
    w("#       These are the most valuable cells here. The corpus has ZERO of them")
    w("#       so far, and 'is it a schedule?' is now a scored question.")
    w("#       Write real messages, not gibberish -- the point is that they LOOK")
    w("#       schedulable to a dumb parser and are not.")
    w("#   [CANNOT-PIN-DOWN]  a real event that no calendar slot could capture.")
    w("#")
    w("# IF SOMEONE ELSE TYPES SOME: add a line like")
    w("#   author: p1")
    w("#   device: phone")
    w("# and everything after it is credited to them. One line, do not skip it.")
    w("#")
    w("# DO NOT read documentation/IR_SPEC_v0.md before writing.")
    w("")

    for i, (kind, lbl, shape, tag, extra) in enumerate(slots, start=1):
        if kind == "schedule":
            w(f"## [{i:03d}] {lbl}   <{tag}, currently {extra:.1f}%>")
            w(f"#     style:  {rng.choice(REGISTERS)} | {rng.choice(CASINGS)} | "
              f"{rng.choice(ORDERS)} | {rng.choice(LENGTHS)}")
            w(f"#     domain: {rng.choice(DOMAINS)}   <- vary the SUBJECT, not just the format")
            w(f"#     shape:  {shape}")
        elif kind == "negative":
            w(f"## [{i:03d}] NOT-A-SCHEDULE   <Q1>")
            w(f"#     style:  {rng.choice(REGISTERS)} | {rng.choice(CASINGS)}")
            w(f"#     shape:  {shape}")
            w(f"#     !!      {extra}")
        else:
            w(f"## [{i:03d}] CANNOT-PIN-DOWN   <Q1>")
            w(f"#     style:  {rng.choice(REGISTERS)} | {rng.choice(CASINGS)}")
            w(f"#     shape:  {shape}")
            w(f"#     !!      {extra}")
        w("")
        w("")

    w("# end of batch")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"wrote {path.relative_to(ROOT)}  ({args.n} cells, author={args.author})")
    print(f"  {n_pos:>3}  schedule cells (domain-assigned for vocabulary spread)")
    print(f"  {n_neg:>3}  NOT-A-SCHEDULE cells   <- corpus currently has 0")
    print(f"  {n_und:>3}  CANNOT-PIN-DOWN cells")
    counts: dict[str, int] = {}
    for kind, lbl, _s, tag, _e in slots:
        if kind == "schedule":
            counts[f"{tag} {lbl}"] = counts.get(f"{tag} {lbl}", 0) + 1
    print()
    for k, v in sorted(counts.items()):
        print(f"  {v:>3}  {k}")
    print("\nFill it in, then:  uv run python scripts/ingest_batch.py")


if __name__ == "__main__":
    main()
