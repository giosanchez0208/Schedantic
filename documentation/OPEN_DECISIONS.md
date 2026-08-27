# Open decisions

> **Round 1 resolved 2026-08-27.** A2, A7, B1, C4, OQ-2, OQ-6, OQ-10, OQ-11
> and OQ-13 are decided and implemented; struck through below with the
> outcome. Everything not struck through is still open.

Everything currently decided by default, guess, or my judgement rather than by
evidence or by you. Gathered from: 55 `note:` fields across 140 annotated dev
items, the `Policy` dataclass, and the IR spec's open questions.

Grouped by **what changing it costs**, because that is what should drive whether
it is worth your attention.

- **A. Policy defaults** — one-line change, no re-annotation. Cheap to revisit.
- **B. Annotation judgements** — changing these means re-annotating. Expensive.
- **C. Schema gaps** — currently produce `unrepresentable` / `unresolvable`.
- **D. Lexicon gaps** — surface forms the parser does not know.
- **E. Spec open questions** — need measurement, not a decision.

---

## A. Policy defaults

All in `convert.Policy` unless noted. Changing any is one line and touches no gold.

| # | Knob | Current | The arbitrary part |
|---|---|---|---|
| A1 | `this_weekday_includes_today` | `True` | "this Monday" said *on* a Monday means today. Could mean next week. |
| ~~A2~~ | `next_weekday_min_offset` | **`1`** -- see OQ-13 | **OQ-13.** "next Monday" said on a Wednesday → Sep 7 (Monday of next week), not Aug 31 (the coming Monday). Parsers genuinely disagree. Both readings are tested; neither is asserted correct. |
| A3 | `month_only_day` | `1` | "until December" → Dec **1**. Could as easily mean end of December. |
| A4 | `all_day_time` | `00:00` | An event with a date but no time lands at midnight. |
| A5 | `default_duration_minutes` | `60` | Start with no end runs one hour. |
| A6 | `tod_times` | dawn 06 · morning 08 · noon 12 · afternoon 14 · evening 18 · night 20 | Where each fuzzy word collapses. "Morning" is really a 06:00–11:00 window. |
| ~~A7~~ | AM/PM inference | 1–6 → PM, 7–12 as written, **but a time-of-day word overrides it**: `3 in the morning` = 03:00, `8 in the evening` = 20:00 | Mirrors chrono-node's refiner. **Affects ~26% of real strings** — the single highest-impact default in the project. |
| A8 | default-to-future | always | A past-sounding date resolves forward. Standard, but it is why `they got wed last week` books a future Wednesday. |

**A7 is the one worth your attention.** It is applied to more strings than any
other rule here, and it is currently justified by "chrono does it."

---

## B. Annotation judgements

These shape gold. Changing one means revisiting the annotated items.

| # | Case | Current call | Why it is contestable |
|---|---|---|---|
| ~~B1~~ | Bare single weekday | **`DATE` unless a repeat marker or a bound is present.** `CCC101 thurs` ≠ `CCC101 every thurs`. Parser now matches gold. | **Ratified 2026-08-27**, but genuinely ambiguous. `Wed stock, Sat sell` reads as a weekly rhythm; `THURS lunch` as one-off. Affects ~1 in 3 annotations. |
| B2 | `til 8` vs `til finals` | bare hour → `TEND`; anything else → `BOUND` | Same word, two span types, decided by what follows it. |
| ~~B3~~ | Prepositions in LOCATION | **Moot** — the LOCATION slot was removed 2026-08-27. |
| ~~B4~~ | Trailing qualifiers | **TAGGED as SUMMARY.** Reversed 2026-08-27 with OQ-14 — keeping the writer's own words is the point. |
| B5 | Redundant time-of-day | dropped when a clock time is present — `every tues night at 9PM` tags only `9PM` | Defensible, but it means `night` is a span in one string and not in another. |
| ~~B6~~ | PERSON | **Span kept, no ATTENDEE emitted.** Folding PERSON into SUMMARY as well was tested and was worse (0.689 → 0.643). |
| B7 | Bare `12` | noon, not midnight | `Lunch w Ate Bea at 12` — obviously right here, not obviously right always. |
| B8 | `f 15` | `15` read as 15:00 | Could be Friday **the 15th**. No way to tell from the string. |
| B9 | Multi-event splitting | only when weekday **and** time both differ | `then badminton after, til 9 pm` was kept as one event because it shares the time range. Judgement call. |

**B1 is the big one** — it is the largest systematic disagreement between my
annotation and the parser (DATE recall 0.38), and it touches roughly a third of
the corpus.

---

## C. Schema gaps

Produce `unrepresentable` or `unresolvable` today. 13 of 140 annotated items.

| # | Gap | Examples seen | Status |
|---|---|---|---|
| C1 | Conditional recurrence | `every day that it doesnt rain`, `when im not on duty`, `when the pager goes` | **Out of scope by your call.** 4 cases. |
| C2 | Institution-specific periods | `Homecoming week`, `the week before Spring Break`, `till finals` | No anchor exists. Offset machinery now works *if* the anchor were known. |
| C3 | Bound that is an event, not a date | `til the exhibit closes in april` | Currently tagged BOUND but unresolvable. |
| ~~C4~~ | Monthly ordinal weekday | **Order matters.** `every 2nd sun` = every OTHER Sunday (INTERVAL=2). `second sun of the month` = MONTHLY BYDAY=2SU. Both implemented. | **RFC 5545 supports this** (`BYDAY=2SU`); our `RRule` validator rejects anything but bare weekday codes. Real gap, cheap fix. |
| C5 | Count with no frequency | `Yoga 6 sessions` | A COUNT with no BYDAY/FREQ cannot build an RRULE. |
| C6 | Event with neither time nor date | `Lab @ CS Bldg` | Title and place only. Currently `unresolvable`. |
| C7 | Astronomical / tidal recurrence | `every spring low tide, shifts ~50 min a day` | Not a calendar rule at all. |

**C4 is the only cheap one** and it is a genuine RFC feature we are refusing.

---

## D. Lexicon gaps

Surface forms real contributors wrote that the parser does not know.

| # | Form | Meaning | Seen |
|---|---|---|---|
| D1 | `q2 wks` | every 2 weeks | 2× |
| D2 | `7ish`, `abt 11:15` | approximate time | 2× |
| D3 | `friendsgiving` | informal named occasion, no fixed date | 1× |
| D4 | `x6 wks`, `6 of them` | count bound variants | 2× |

Cheap to add, no design question. Listed so they are not lost.

---

## E. Spec open questions

Need measurement, not a decision. Answering them is what the gold corpus is for.

| # | Question | Blocked on |
|---|---|---|
| ~~OQ-2~~ | PERSON slot | **Part of SUMMARY.** Span kept for boundary detection; no ATTENDEE property emitted. |
| ~~OQ-6~~ | Relative anchor + recurrence | **Yes**, handled by the composed-symbol resolver. |
| ~~OQ-10~~ | All-day events | **All-day iff no time is specified.** Emits the DATE value type, not DATE-TIME. |
| ~~OQ-11~~ | Span nesting | **Not an issue** — each line is independent. Flat BIO stands. |
| ~~OQ-13~~ | `next Monday` | **The next instance of Monday.** A schedule is written before the day it names. |

---

## Still open after round 1

- **A1, A3, A4, A5, A6, A8** — low-impact policy defaults, one line each.
- **B2–B9** — annotation judgements. B4 (`by eod`, `sharp`) and B8 (`f 15` as a
  time vs the 15th) have real content; the rest are consistency choices where any
  answer works so long as it is applied uniformly.
- **C1** — conditional recurrence. Out of scope by decision, not oversight.
- **C2, C3, C5, C6, C7** — degenerate or unanchorable cases.
- **D1–D4** — lexicon gaps, trivial to add.
