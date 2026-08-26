# Accuracy target — M1.5

**Declared 2026-08-26, before any baseline number existed.** That is the point of
this file: if the target is written after M5 produces a number, it gets
reverse-engineered from whatever the baseline happened to score, and the M6 gate
stops gating anything.

---

## The gate

At **M6**, the rule baseline is measured on the **Tier A frozen test set**. If it
clears every threshold below, the correct engineering call is **ship rules, do
not build the model**.

| Metric | Threshold | Measured by |
|---|---|---|
| Temporal slots exact-match | **≥ 0.90** | `score.l2_exact_match(...)["temporal_exact_match"]` |
| SUMMARY span F1 | **≥ 0.75** | `score.span_prf(...)["per_type"]["SUMMARY"]["f1"]` |
| Silent catastrophic rate | **≤ 2%** | `score.silent_catastrophic_rate(...)` |
| RRULE occurrence-set equivalence | **≥ 0.90** | `score.rrule_equivalence(...)["occurrence_set_exact"]` |

"Temporal slots" means DTSTART date+time, DTEND, FREQ, BYDAY, INTERVAL, and the
UNTIL/COUNT bound. Not SUMMARY, not attendees, not location.

## Why these numbers

**The thresholds are asymmetric on purpose.** A wrong SUMMARY is cosmetic — the
user sees a slightly odd calendar title. A wrong DTSTART or a dropped BYDAY is a
missed class. So temporal precision is held at 0.90 while SUMMARY is allowed to
sit at 0.75.

**Silent catastrophic rate is the one that actually matters to a user.** It counts
cases where a temporal slot is wrong *and* no ambiguity flag was raised — the
parser was confidently wrong and the user was never warned. 2% is roughly "one
bad event per 50," which a confirmation step catches.

**These assume a confirmation step in the UI.** The user sees the parsed event
before it is saved. If that assumption ever changes — if events are written to
the calendar silently — every threshold here must be revised upward, because the
user has no chance to catch anything.

**They are set to be clearable.** A target the rules can never hit would make M6
always answer "build the model," which defeats the branch. 0.90 temporal on terse
real input is demanding but not absurd for a well-tuned rule pipeline.

## What is deliberately not in here

- **No aggregate score.** A single blended number would let a strong SUMMARY F1
  paper over a weak BYDAY recall. Every threshold must be cleared independently.
- **No latency or size target yet.** Those belong to M10 and only exist on the
  neural branch.
- **No target for the synthetic pools.** Synthetic accuracy is not evidence; the
  only number that gates anything is the one measured on Tier A.

## Revision rules

This file may be revised **before** M5 runs, for any reason. After M5 has
produced a number it may be revised only with the reason recorded here, and the
pre-revision number kept alongside — otherwise the gate is being moved to fit the
result.

| Date | Change | Reason |
|---|---|---|
| 2026-08-26 | Initial declaration | Set before any baseline existed |
