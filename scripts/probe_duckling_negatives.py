"""Duckling's negativeCorpus, run against both of our Q1 answers.

Source: facebook/duckling, Duckling/Time/EN/Corpus.hs, BSD-3. These are strings
a production temporal parser is asserted NOT to parse as a time -- curated by
people who shipped one and watched it misfire. Every class in it is a class we
score 0.00-0.40 on.

Used as EVALUATION only. If these go into the generator they stop being a
measurement, same rule as the 56 human negatives and the 28 human refusals.
"""
import datetime as dt
import sys
import warnings

warnings.filterwarnings("ignore")
R = r"C:\Repositories\Schedule-Tiny-Language-Model"
sys.path.insert(0, R + r"\src")

from stlm.infer import load, run                      # noqa: E402
from stlm.normalize import parse                      # noqa: E402

REF = dt.datetime(2026, 8, 27, 9, 0)

DUCKLING_NEGATIVE = [
    "laughing out loud", "1 adult", "we are separated", "25",
    "this is the one", "this one", "this past one", "at single",
    "at a couple of", "at pairs", "at a few", "at dozens",
    "single o'clock", "dozens o'clock", "Rat 6", "rat 6",
    "3 30", "three twenty", "at 650.650.6500", "at 650-650-6500",
    "two sixty a m", "Pay ABC 2000", "4a", "4a.", "A4 A5", "palm",
    "Martin Luther King' day", "two three",
]

model, meta = load(R + r"\checkpoints\tagger.pt")

rows = []
for t in DUCKLING_NEGATIVE:
    m = run(model, t, ref=REF)
    rl2, _ = parse(t)
    rows.append((t, m.status, m.status_probs["ok"], bool(rl2.events)))

mw = sum(1 for _, s, _, _ in rows if s == "ok")
rw = sum(1 for _, _, _, r in rows if r)
print(f"Duckling negative corpus, n={len(rows)}")
print(f"  model schedules : {mw}/{len(rows)} = {mw/len(rows):.2f}   (should be 0)")
print(f"  rules schedule  : {rw}/{len(rows)} = {rw/len(rows):.2f}   (should be 0)")
print()
print(f"  {'string':<28}{'model':<17}{'p(ok)':>7}   rules")
for t, s, p, r in rows:
    flag = "XX" if s == "ok" else "  "
    print(f"{flag} {t:<28}{s:<17}{p:>6.2f}   {'SCHEDULES' if r else 'refuses'}")
