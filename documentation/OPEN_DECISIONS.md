# Open decisions

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
| A2 | `next_weekday_min_offset` | `7` | **OQ-13.** "next Monday" said on a Wednesday → Sep 7 (Monday of next week), not Aug 31 (the coming Monday). Parsers genuinely disagree. Both readings are tested; neither is asserted correct. |
| A3 | `month_only_day` | `1` | "until December" → Dec **1**. Could as easily mean end of December. |
| A4 | `all_day_time` | `00:00` | An event with a date but no time lands at midnight. |
| A5 | `default_duration_minutes` | `60` | Start with no end runs one hour. |
| A6 | `tod_times` | dawn 06 · morning 08 · noon 12 · afternoon 14 · evening 18 · night 20 | Where each fuzzy word collapses. "Morning" is really a 06:00–11:00 window. |
| A7 | AM/PM inference *(in `normalize.py`, not `Policy`)* | hours 1–6 → PM, 7–12 as written | Mirrors chrono-node's refiner. **Affects ~26% of real strings** — the single highest-impact default in the project. |
| A8 | default-to-future | always | A past-sounding date resolves forward. Standard, but it is why `they got wed last week` books a future Wednesday. |

**A7 is the one worth your attention.** It is applied to more strings than any
other rule here, and it is currently justified by "chrono does it."

---

## B. Annotation judgements

These shape gold. Changing one means revisiting the annotated items.

| # | Case | Current call | Why it is contestable |
|---|---|---|---|
| B1 | Bare single weekday — `THURS lunch` | `DATE` + `recurrence_ambiguous` | **Ratified 2026-08-27**, but genuinely ambiguous. `Wed stock, Sat sell` reads as a weekly rhythm; `THURS lunch` as one-off. Affects ~1 in 3 annotations. |
| B2 | `til 8` vs `til finals` | bare hour → `TEND`; anything else → `BOUND` | Same word, two span types, decided by what follows it. |
| B3 | Prepositions in LOCATION | included — `at the chapel`, not `the chapel` | Arbitrary but must be consistent. Same question never arose for PERSON. |
| B4 | Trailing qualifiers | untagged — `before class`, `by eod`, `sharp`, `dont forget` | `by eod` is arguably a real deadline. `sharp` is arguably a precision marker. Both dropped. |
| B5 | Redundant time-of-day | dropped when a clock time is present — `every tues night at 9PM` tags only `9PM` | Defensible, but it means `night` is a span in one string and not in another. |
| B6 | PERSON | both folded into the summary string *and* emitted as `attendees` | Duplication on purpose. May be wrong for either consumer. |
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
| C4 | Monthly ordinal weekday | `every 2nd sun` = 2nd Sunday of the month | **RFC 5545 supports this** (`BYDAY=2SU`); our `RRule` validator rejects anything but bare weekday codes. Real gap, cheap fix. |
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
| OQ-2 | Is `PERSON` its own slot, or part of SUMMARY? | Gold rate. Harvest said 0.33% but its register cannot see attendees. |
| OQ-6 | Do relative anchors co-occur with recurrence? (`every MWF starting next week`) | Gold rate. Currently a 4% guess. |
| OQ-10 | All-day event rate | Gold rate. |
| OQ-11 | Span nesting pressure — does real text want overlapping spans? | 20k synthetic examples produced zero overlaps, but that only proves the generator is self-consistent. |
| OQ-13 | `next Monday` semantics | Same as A2. Needs strings that disambiguate it. |

---

## What I would put in front of you first

1. **A7 — AM/PM inference.** Highest blast radius of anything here (~26% of strings) and currently justified only by precedent.
2. **B1 — bare weekday.** Largest systematic effect on gold, ~1 in 3 items, and I decided it.
3. **C4 — monthly ordinal weekday.** The one schema gap that is a real RFC feature and cheap to add.

Everything else is either genuinely low-impact, already scoped out, or waiting
on measurement rather than on a judgement.
