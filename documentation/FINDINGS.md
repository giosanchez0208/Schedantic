# Findings — first data pass

**Date:** 2026-08-26
**Inputs:** 610 harvested real strings (305 target-like) · 20,000 balanced synthetic · 10,000 realistic synthetic
**Regenerate:** `scripts/build_corpus.py` then `scripts/gap_report.py`

---

## What was actually built

| Milestone | State | Where |
|---|---|---|
| M0 fixtures — 7 example strings, hand-mapped to L2 | done, passing | `tests/test_core.py` |
| M1 IR schema — L1/L2 dataclasses + validation | done | `src/stlm/ir.py` |
| M2 converter — symbolic resolution, L2→jCal | done, passing | `src/stlm/convert.py` |
| M3 scorer — span F1, L2 exact match, RRULE equivalence | done, passing | `src/stlm/score.py` |
| M7 generator — meaning-first, two sampling profiles | done | `src/stlm/generate.py` |
| Analysis + gap engine | done | `src/stlm/analyze.py` |
| M4a human gold corpus | **not started — yours to write** | — |

All 44 tests pass, including the RRULE-equivalence pairs that must *not* be fooled by
string differences (`BYDAY=MO,WE` vs `BYDAY=WE,MO`; `COUNT=4` vs the matching `UNTIL`).

---

## Provenance and how much to trust this

The harvest came from public parser test suites and one public student forum:
ctparse's production corpus of real customer messages, Duckling's Time corpus,
chrono's test fixtures, kvh/recurrent, Sherlock, natty, rrule.js,
Microsoft Recognizers-Text, and an AnandTech thread where students typed their
own class schedules.

**Verification status: partial.** The workflow's two adversarial verification
agents died on a session limit, so I spot-checked by hand instead:

- ctparse corpus — **confirmed**, `"Nov 12 (Sun"` present verbatim.
- AnandTech thread — **confirmed**, `"8am-11am MWF"`, `"7:45am-1:15 TTh"`,
  `"9-12, 1-3 Mondays"`, `"W F - 9-12"` all present verbatim.
- Two typo strings the agent *described* in its notes (`"thursady"`,
  `"next Thrusday"`) were **not** found in the file. The agent embellished its
  commentary; the harvested strings themselves checked out.

Treat the corpus as substantially authentic and the agent commentary as unreliable.

**The harvest is biased, in two known directions:**

1. Parser test suites over-represent absolute dates and month names, because
   that is precisely what they are built to test.
2. Forum posts and parser tests essentially never name an attendee or a room —
   nobody writes "with Sir Jefferson" in a bug report.

So a low harvest rate means *either* "genuinely rare" *or* "invisible to this
register," and the data cannot tell those apart. Every number below is
directional. **Your 500 replace all of it.**

---

## Open questions — answers

### Answered with evidence

**OQ-5 — AM/PM ambiguity rate. 25.9% target-like, 36.7% of the informal subset.**
The biggest surprise in the pass. A bare hour with no meridiem is not an edge
case, it is roughly a third of real terse schedule text. This promotes AM/PM
disambiguation from "a refiner" to a first-class component with its own metric.
Prior raised 12% → 25%. The resolution policy now lives in `convert.Policy` and
is documented: hours 7–12 stay as written, 1–6 resolve to PM.
*Action: score AM/PM resolution separately from extraction. It will dominate your error budget.*

**OQ-12 — byte-length distribution.** Harvested target-like, UTF-8 bytes:
p50 **22**, p90 **40**, p99 **54**, max **82**. Synthetic runs longer
(p50 30, max 92). Non-ASCII appears in **0.66%** of harvested strings and 0.41%
of synthetic — en-dash `U+2013` is the only recurring offender, at 3 bytes.
*Action: `max_len = 128` bytes covers everything observed with headroom. Byte/char inflation is ~1.0002, so characters and bytes are interchangeable here in practice — but size the positional table in bytes anyway.*

**OQ-4 — UNTIL / COUNT base rate.** UNTIL **2.6%**. COUNT **0.0%** in the
target-like subset, 0.5% across the whole harvest.
*Action: COUNT will never be learned from natural sampling. It must be deliberately oversampled in the balanced pool (it is, at 1.5% realistic / 12.5% balanced) and deliberately hand-written. It is P0 on the worksheet.*

**OQ-8 — DURATION vs TEND. 0.98%.**
*Action: **drop `DURATION` as a span type.** Handle "for 2 hrs" as a normalization rule that computes TEND from TSTART. One fewer slot, one fewer thing for the tagger to get wrong. Revisit only if your 500 disagree.*

**OQ-9 — negation / exception. 0.33%.**
*Action: keep representable negation ("every day except Friday" → `BYDAY=MO,TU,WE,TH`), which the generator already emits. **Defer EXDATE entirely** — "except holidays" stays `unrepresentable` in v0. The rate does not justify the machinery.*

**OQ-1 — multi-event rate. 17.7%** of target-like strings contain a multi-event
separator. That is a floor, not a ceiling — the probe is a regex for `,;/` and
"and", which over-triggers on some strings and misses others.
*Action: not negligible, so `events` stays a list and `event_groups` stays in L1. But how the **model** emits grouping is still unsolved and is now the single largest architectural risk. Do not defer this to M8 without a plan.*

### Answered, but the evidence is weak

**OQ-3 — LOCATION base rate. 3.6%**, above the 2% delete-the-slot threshold, but
the harvest register under-counts rooms.
*Action: **keep the slot**, flag for re-decision after the 500.*

**OQ-7 — month-only and date-of-month. 28.5% month name, 24.6% month+day** —
but this is the most test-suite-biased number in the report and the true rate is
certainly lower.
*Action: implemented regardless, because the design question was answerable on its own merits. `until December` is now `REL:MONTH_12` — symbolic, meaning "the next December," not a fixed year. That is what stops gold from expiring, and it fixed 7 unresolvable rows.*

### Not answered

**OQ-2 — is PERSON its own slot?** Harvest says 0.33%. **Ignore that number.**
All six of your own examples carry an attendee; parser test suites and forum
posts structurally cannot. This is the clearest case where the harvest's register
mismatch makes it useless. Slot kept, prior deliberately *not* recalibrated down.
*Decide from your 500.*

**OQ-6 — relative anchor + recurrence.** No clean probe. Found indirectly: the
generator produced "every MWF starting next week" at ~20% until I gated it, which
is obviously wrong but I have no measurement to set the real rate. Currently 4%,
a guess.

**OQ-10 — all-day event rate.** Not probed. Needs labels the harvest lacks.

**OQ-11 — span nesting pressure.** The evidence agent died. Weak positive
only: 20,000 generated examples produced **zero** overlap violations under the
non-overlapping/residual-SUMMARY rule, so the rule is at least self-consistent.
That says nothing about whether real text wants nesting. Still open.

### New question found during the work

**OQ-13 — "next Monday" is genuinely ambiguous.** Issued on a Wednesday, does it
mean the coming Monday (+5) or the Monday of next week (+12)? Parsers disagree,
and my own test initially asserted the wrong one. This is now a policy knob
(`Policy.next_weekday_min_offset`) with both readings tested, and it is
deliberately *not* resolved. Add strings to the 500 that pin down which you mean.

---

## Two design decisions forced by the data

**1. Coverage sampling and realism sampling are different jobs.** Uniform axis
sampling gives complete cell coverage (0 empty cells across all marginals and key
pairs) but a wildly unrealistic corpus — 46% multi-event, 46% location, 11%
bounded recurrence. There are now two pools:

| | `synthetic_balanced.jsonl` | `synthetic_realistic.jsonl` |
|---|---|---|
| Sampling | uniform over axes | `AXIS_PRIOR`, partly harvest-calibrated |
| multi-event | 45.5% | 11.4% |
| bounded_count | 11.1% | 1.5% |
| Purpose | class coverage, so rare forms are learnable | distribution calibration |

Train on balanced, calibrate and evaluate against realistic, and report both.

**2. `AXIS_PRIOR` is a guess with a paper trail.** Entries anchored to a measured
harvest rate are tagged `[H]` in the source; the rest are labelled as priors. Two
were deliberately left *uncalibrated* (`has_person`, `has_location`) because the
harvest cannot see them. This is the biggest single source of unearned confidence
in the project, and it is marked as such at the point of use.

---

## Bugs the validator caught

Worth recording, because they are the class of error that would otherwise reach
the model as silent label noise:

- A typo turned `"Lab 3"` into `"lab "`, and the final `strip()` desynced that
  span from the text. Labelled chunks now carry no edge whitespace.
- Multi-event splitting kept `interval=2` in L2 while the surface only said
  `"fri"` — the label asserted something the text never stated, making the
  example unlearnable. Split events now force `interval=1`.
- `REL:NEXT_OCCURRENCE` compared occurrences against the reference *datetime*
  rather than its *date*, silently skipping today whenever the reference time was
  past midnight.
- Space-collapse noise was merging words (`"at the cafelater today"`). Collapse
  is now allowed only across a letter/digit boundary, which is what real
  shorthand actually does (`mwf8-12nn`).

---

## What to do next

1. **Write the 500.** `documentation/COVERAGE_GAPS.md` is the worksheet — it
   ranks constructions P0–P3 by how absent they are from real data. P0 is
   COUNT bounds, negation, attendees, and durations.
2. **Set the accuracy target before M5 produces a number**, per the earlier
   discussion. It is still unwritten.
3. **Decide the segmentation mechanism** (OQ-1). It is the largest open
   architectural risk and 17.7% is too high to defer.
4. Re-run `gap_report.py` after each batch of 50 to watch the P0 rows fill.
