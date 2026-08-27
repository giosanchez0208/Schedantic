# Intermediate Representation — Spec v0

**Status:** provisional. Written *before* corpus collection, deliberately.
**Purpose:** not to freeze a schema, but to surface the questions the corpus has to answer. Every guess in here is logged in [Open Questions](#open-questions).

**Do not read this while writing corpus strings.** Knowing what the schema supports biases what you write, and the corpus is supposed to be evidence about the world, not about the schema. Write first, then come back.

---

## 1. Why the IR is three layers, not one

The original plan was NL → jCal. It has to become NL → IR → jCal, and the IR itself splits into three:

| Layer | Holds | Produced by | Question it answers |
|---|---|---|---|
| **L1 Extraction** | Typed character spans over the raw text | The tagger; hand-annotated for gold | "Where are the spans and what type is each?" |
| **L2 Resolution** | Normalized, symbolic event list | Deterministic code from L1 | "What are the event semantics?" |
| **L3 Instantiation** | jCal with absolute datetimes | Code, from L2 + reference time + tz | "What goes on the calendar?" |

### Rationale

**Annotation becomes reliable.** Labeling L1 is "highlight spans, type them" — no judgment calls. A merged IR would require the annotator to decide, by hand, 500 times, whether bare `8` means 08:00 or 20:00, and to apply that consistently. They won't. The gold would be internally inconsistent in ways nobody could detect.

**Defaulting policy changes without re-annotation.** The AM/PM heuristic will change repeatedly. If defaults are baked into gold, each change is a 500-example re-annotation pass. In L1→L2 code, it's a config edit.

**Errors localize.** Slot-F1 at L1 measures extraction. Exact-match at L2 measures normalization and defaults. L1 = 0.94 with L2 = 0.71 means the tagger is fine and the defaulting rules are wrong — a diagnosis that is impossible from a single merged number.

**Gold does not expire.** L2 stores *symbolic* dates (`REL:TOMORROW`), never resolved ones. Gold containing `2026-08-27` would be welded to the day it was written, and the test set would rot. Symbolic gold is timeless; L3 takes reference time as an explicit parameter, the way Duckling's `reftime` and ML Kit's `setReferenceTime` do.

---

## 2. L1 — Extraction

```json
{
  "id": "c0042",
  "text": "MWF 8-12NN CCC100 with Sir Jefferson",
  "spans": [
    {"i": 0, "type": "RECUR",   "start": 0,  "end": 3,  "text": "MWF"},
    {"i": 1, "type": "TSTART",  "start": 4,  "end": 5,  "text": "8"},
    {"i": 2, "type": "TEND",    "start": 6,  "end": 10, "text": "12NN"},
    {"i": 3, "type": "SUMMARY", "start": 11, "end": 17, "text": "CCC100"},
    {"i": 4, "type": "PERSON",  "start": 23, "end": 36, "text": "Sir Jefferson"}
  ],
  "event_groups": [[0, 1, 2, 3, 4]],
  "status": "ok",
  "notes": null
}
```

Offsets are character indices, half-open `[start, end)`. The `text` field duplicates `text[start:end]` — redundant, but it makes annotations readable and diffable, and it catches offset bugs immediately.

### Span inventory (v0)

`SUMMARY` · `RECUR` · `TSTART` · `TEND` · `DATE` · `UNTIL` · `PERSON` · `LOCATION`

Deliberately small. Every slot costs annotation effort and tagger capacity, so a slot has to earn its place with a real base rate in the corpus.

- **`SUMMARY`** — event title. The *residual*: whatever is not otherwise typed.
- **`RECUR`** — recurrence expression: `MWF`, `every other Tuesday`, `weekly`.
- **`TSTART`** / **`TEND`** — clock times.
- **`DATE`** — absolute or relative date expression: `this Monday`, `tmrw`, `Sept 3`.
- **`UNTIL`** — recurrence end bound: `until December`, `till finals`.
- **`PERSON`** — attendee.
- **`LOCATION`** — place.

### Design rule 1 — spans are non-overlapping; SUMMARY is the residual

If `SUMMARY` were `"CCC100 with Sir Jefferson"` and `PERSON` were `"Sir Jefferson"` nested inside it, a flat BIO tagger could not emit both — one token cannot carry two labels. So `SUMMARY` is `"CCC100"`, `PERSON` is separate, and the display summary is *composed* back together at L2→L3.

This also matches the correct generalization to teach the tagger: **SUMMARY = anything not temporal**, which is broader and more robust than SUMMARY = plausible event noun phrase.

### Design rule 2 — `event_groups` carries segmentation

RFC 5545 cannot bind different times to different weekdays in one RRULE (see §5), so one input string can legitimately produce several events. `event_groups` is a list of lists of span indices; a span index may appear in more than one group when it is shared.

```json
"text": "Monday 12pm, Wednesday 5pm Laboratory with Sir Jeff",
"event_groups": [[0, 1, 4, 5], [2, 3, 4, 5]]
```

Spans 4 and 5 (SUMMARY, PERSON) belong to both events.

> **Unresolved:** annotating grouping is trivial for a human, but **how the model produces it is an open architectural problem.** Flat BIO has no native notion of "which event does this span belong to." Candidate approaches: encode an event index in the tag set (`B-SUMMARY-1`), add a separate grouping head, or segment-then-tag. Deferred to M8. The corpus decides how much this matters — see [OQ-1](#oq-1--multi-event-rate).

---

## 3. L2 — Resolution

```json
{
  "events": [
    {
      "summary": "CCC100 with Sir Jefferson",
      "dtstart": {"date": "REL:NEXT_OCCURRENCE", "time": "08:00"},
      "dtend":   {"time": "12:00"},
      "rrule":   {"freq": "WEEKLY", "byday": ["MO", "WE", "FR"]},
      "attendees": ["Sir Jefferson"],
      "location": null
    }
  ],
  "status": "ok",
  "flags": ["ampm_inferred"],
  "provenance": {
    "events[0].dtstart.time": {"span": 1, "rule": "AMPM_DEFAULT_MORNING"}
  }
}
```

### Symbolic dates

`date` is never a resolved datetime. Closed set, extended as the corpus demands:

```
REL:TODAY
REL:TOMORROW
REL:DAY_AFTER_TOMORROW
REL:THIS_<WEEKDAY>
REL:NEXT_<WEEKDAY>
REL:NEXT_OCCURRENCE      # first date matching the RRULE at or after reftime
ABS:YYYY-MM-DD
```

The model never does date arithmetic. It classifies into this set; L3 resolves against reference time. Default-to-future, matching Duckling and ctparse.

### `provenance`

Optional, cheap, and it pays for itself in error analysis: it records *which rule* produced each derived value, so a wrong output points at the rule that produced it rather than requiring a re-derivation by hand.

---

## 4. L3 — Instantiation

`L3 = f(L2, reference_datetime, timezone) → jCal`

Nothing here is a design decision worth debating; it is the deterministic assembly described in RESEARCH.md §B, built on `dateutil.rrule` and `icalendar`. Two rules carried over:

- DTSTART/DTEND stored as local time with TZID, or floating for pure academic schedules.
- `UNTIL` in UTC when DTSTART is tz-aware (RFC 5545); expansion performed in the DTSTART timezone so an "every Monday 08:00" series stays at 08:00 local across a DST boundary.

**jCal is an output format, not an annotation format.** Gold is never written as jCal:

- Two semantically identical events serialize differently — property order, parameter presence, case of `freq` values. String equality is a broken metric.
- Slot-level F1 is not computable from a jCal string without parsing it back into slots, which requires the IR anyway.
- The tagger emits BIO tags, not jCal. Gold must live at the level being scored.
- RFC 5545 requires `UID` and `DTSTAMP`; every gold annotation would carry an arbitrary UID and a timestamp to be excluded from every comparison.

---

## 5. Known RFC 5545 constraint: no per-weekday times

`FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=12,17` does **not** mean "Monday at 12, Wednesday at 17." For `FREQ=WEEKLY`, both `BYDAY` and `BYHOUR` are *expand* rule parts, so they produce the cross product:

```
MO 12:00, MO 17:00, WE 12:00, WE 17:00     <- four occurrences, not two
```

There is no pairing operator in RFC 5545. `"Monday 12pm, Wednesday 5pm Laboratory"` therefore requires **two VEVENTs** sharing a SUMMARY:

```
VEVENT 1: DTSTART Mon 12:00, RRULE FREQ=WEEKLY;BYDAY=MO
VEVENT 2: DTSTART Wed 17:00, RRULE FREQ=WEEKLY;BYDAY=WE
```

(A single VEVENT with `RDATE` enumerating every Wednesday is technically valid but requires ~16 explicit dates for a semester and does not compress. Not used.)

**Consequence for scope:** v1 may be scoped to one input *string*, but it cannot be scoped to one output *event*. `events` is a list from the start.

---

## 6. Status and flags

```
status: "ok" | "no_temporal" | "unresolvable" | "unrepresentable"
```

| Status | Meaning | `events` | Example |
|---|---|---|---|
| `ok` | Valid event(s), even if underspecified | ≥1 | `MW 8am` |
| `no_temporal` | No scheduling information present | `[]` | `I have to go` |
| `unresolvable` | Real event, but no reasonable default exists | `[]` | `lunch sometime next week` |
| `unrepresentable` | The schema cannot express it — **schema bug** | `[]` | `every day except holidays` |

Underspecification does **not** demote `status` from `ok`. Nearly every real string is underspecified in some way and defaults handle it; the specifics live in `flags`.

`unresolvable` marks the line between *underspecified and defaultable* (`MW 8` → default to 08:00) and *underspecified and not* (`sometime next week` → no defensible time exists).

`unrepresentable` is the bucket that drives IR evolution. It is the reason a binary valid/None annotation was rejected: `None` conflated *"correctly produces zero events"* with *"my schema is wrong,"* and the second kind would never have been found.

### Flags (open vocabulary; freeze after corpus analysis)

```
ampm_ambiguous       ampm_inferred        missing_end_time
missing_date         missing_summary      temporal_lookalike
multi_event          relative_date        negated_recurrence
bounded_until        bounded_count        all_day
```

`temporal_lookalike` is worth calling out: `"My friends are to be wed"` has the same `events: []` as `"I have to go"`, but it is a hard negative and among the most valuable training data in the corpus. The flag preserves that distinction.

---

## 7. Worked examples

### 7.1 `MWF 8-12NN CCC100 with Sir Jefferson`

**L1**

```json
{
  "text": "MWF 8-12NN CCC100 with Sir Jefferson",
  "spans": [
    {"i": 0, "type": "RECUR",  "start": 0,  "end": 3,  "text": "MWF"},
    {"i": 1, "type": "TSTART", "start": 4,  "end": 5,  "text": "8"},
    {"i": 2, "type": "TEND",   "start": 6,  "end": 10, "text": "12NN"},
    {"i": 3, "type": "SUMMARY","start": 11, "end": 17, "text": "CCC100"},
    {"i": 4, "type": "PERSON", "start": 23, "end": 36, "text": "Sir Jefferson"}
  ],
  "event_groups": [[0, 1, 2, 3, 4]],
  "status": "ok"
}
```

**L2**

```json
{
  "events": [{
    "summary": "CCC100 with Sir Jefferson",
    "dtstart": {"date": "REL:NEXT_OCCURRENCE", "time": "08:00"},
    "dtend":   {"time": "12:00"},
    "rrule":   {"freq": "WEEKLY", "byday": ["MO", "WE", "FR"]},
    "attendees": ["Sir Jefferson"]
  }],
  "status": "ok",
  "flags": ["ampm_inferred"]
}
```

### 7.2 `TTh 5pm Meeting with Boss`

**L1** — `TTh` [0,3) RECUR · `5pm` [4,7) TSTART · `Meeting` [8,15) SUMMARY · `Boss` [21,25) PERSON. One group.

**L2** — `rrule: {freq: WEEKLY, byday: [TU, TH]}`, `dtstart.time: "17:00"`, `dtend: null`.
`flags: ["missing_end_time"]`

### 7.3 `MW 8am`

**L1** — `MW` [0,2) RECUR · `8am` [3,6) TSTART. No SUMMARY span.

**L2** — `summary: null`, `rrule: {freq: WEEKLY, byday: [MO, WE]}`, `dtstart.time: "08:00"`.
`flags: ["missing_end_time", "missing_summary"]`

> AM/PM is explicit here, so no `ampm_inferred`. Compare with a bare `MW 8`, which is the deliberately-generated ambiguous variant and carries `ampm_ambiguous` + `ampm_inferred`.

### 7.4 `every other Tuesday until December`

**L1** — `every other Tuesday` [0,19) RECUR · `until December` [20,34) UNTIL.

**L2**

```json
{
  "events": [{
    "summary": null,
    "dtstart": {"date": "REL:NEXT_OCCURRENCE", "time": null},
    "rrule": {"freq": "WEEKLY", "interval": 2, "byday": ["TU"],
              "until": "ABS:2026-12-01"}
  }],
  "status": "ok",
  "flags": ["bounded_until", "missing_date", "missing_summary", "all_day"]
}
```

> `until December` resolving to Dec 1 of the *next* December relative to reftime is a defaulting decision, not a fact. It belongs in L1→L2 policy and is listed in [OQ-7](#oq-7--month-only-and-date-of-month-expressions).

### 7.5 `Tomorrow go swimming with kyle`

**L1** — `Tomorrow` [0,8) DATE · `go swimming` [9,20) SUMMARY · `kyle` [26,30) PERSON.

**L2** — `dtstart: {date: "REL:TOMORROW", time: null}`, `rrule: null`, `attendees: ["kyle"]`.
`flags: ["relative_date", "all_day"]`

### 7.6 `Day after Tmrw skating`

**L1** — `Day after Tmrw` [0,14) DATE · `skating` [15,22) SUMMARY.

**L2** — `dtstart: {date: "REL:DAY_AFTER_TOMORROW", time: null}`.
`flags: ["relative_date", "all_day"]`

### 7.7 `Ballet Class This Monday`

**L1** — `Ballet Class` [0,12) SUMMARY · `This Monday` [13,24) DATE.

**L2** — `dtstart: {date: "REL:THIS_MONDAY", time: null}`, `rrule: null`.

> Trailing-temporal ordering. Contrast 7.5, which is leading-temporal. Template diversity across this axis is a corpus requirement, not a nice-to-have.

### 7.8 `Monday 12pm, Wednesday 5pm Laboratory with Sir Jeff` — multi-event

**L1**

```json
{
  "text": "Monday 12pm, Wednesday 5pm Laboratory with Sir Jeff",
  "spans": [
    {"i": 0, "type": "RECUR",  "start": 0,  "end": 6,  "text": "Monday"},
    {"i": 1, "type": "TSTART", "start": 7,  "end": 11, "text": "12pm"},
    {"i": 2, "type": "RECUR",  "start": 13, "end": 22, "text": "Wednesday"},
    {"i": 3, "type": "TSTART", "start": 23, "end": 26, "text": "5pm"},
    {"i": 4, "type": "SUMMARY","start": 27, "end": 37, "text": "Laboratory"},
    {"i": 5, "type": "PERSON", "start": 43, "end": 51, "text": "Sir Jeff"}
  ],
  "event_groups": [[0, 1, 4, 5], [2, 3, 4, 5]],
  "status": "ok",
  "notes": "spans 4,5 shared across both events"
}
```

**L2** — two events, both `summary: "Laboratory with Sir Jeff"`, `attendees: ["Sir Jeff"]`:

- `dtstart.time: "12:00"`, `rrule: {freq: WEEKLY, byday: [MO]}`
- `dtstart.time: "17:00"`, `rrule: {freq: WEEKLY, byday: [WE]}`

`flags: ["multi_event", "missing_end_time"]`

### 7.9 Negative and edge cases

| Input | `status` | `flags` | Note |
|---|---|---|---|
| `I have to go` | `no_temporal` | — | No spans. |
| `My friends are to be wed` | `no_temporal` | `temporal_lookalike` | `wed` is not a weekday here. High-value hard negative. |
| `March was fun` | `no_temporal` | `temporal_lookalike` | Month name, non-temporal use. |
| `Sat down for coffee` | `no_temporal` | `temporal_lookalike` | `Sat` is a verb here. |
| `lunch sometime next week` | `unresolvable` | `relative_date` | Real event; no defensible time or date. |
| `every day except Friday` | `ok` | `negated_recurrence` | Representable: `BYDAY=MO,TU,WE,TH,SA,SU`. |
| `MWF 8-12 except holidays` | `unrepresentable` | `negated_recurrence` | Needs EXDATE against an external calendar. Out of scope for v0. |

---

## Open Questions

These are the guesses embedded above. Each becomes an explicit count in the corpus analysis script. **Nothing in this spec is promoted from v0 to v1 until these are answered with real numbers.**

### OQ-1 — multi-event rate

What fraction of strings encode more than one event? Drives how much architecture segmentation deserves at M8, and whether `event_groups` needs a model-side mechanism at all.

### OQ-2 — is `PERSON` its own slot?

Depends on base rate, and on whether it is ever *not* adjacent to the summary. If it is always trailing and always adjacent, folding it into SUMMARY removes a slot for free.

### OQ-3 — `LOCATION` base rate

Below roughly 2%, delete the slot.

### OQ-4 — `UNTIL` / `COUNT` base rate

Needed to know how hard to oversample these synthetically. RESEARCH.md warns they are rare in natural distributions and will be underfit otherwise.

### OQ-5 — AM/PM ambiguity rate

Sets how much the defaulting policy matters, and how much of the accuracy budget it can consume.

### OQ-6 — relative anchor + recurrence co-occurrence

Does `every Monday starting next week` actually appear? If so, `dtstart.date: REL:NEXT_MONDAY` alongside an RRULE must be supported and tested.

### OQ-7 — month-only and date-of-month expressions

`Sept 3`, `the 15th`, `until December`. Needs `ABS:` handling, possibly `FREQ=MONTHLY;BYMONTHDAY`, and a documented policy for resolving bare month names.

### OQ-8 — `DURATION` instead of `TEND`

`2 hours from 8`, `8am for 90 mins`. If present, either a `DURATION` span type or a normalization rule that converts to TEND.

### OQ-9 — negation and exception frequency

`every day except Friday` (representable) vs `MWF except holidays` (not). The ratio decides whether EXDATE support is v1 scope or deferred.

### OQ-10 — all-day event rate

How often is there a date but no time at all?

### OQ-11 — span nesting pressure

How often does the natural reading want overlapping spans? If frequent, Design rule 1 is under strain and flat BIO needs revisiting.

### OQ-12 — byte-length distribution

p50 / p90 / p99 / max in **UTF-8 bytes**, not characters. Sets `max_len` and sizes the positional embedding table. Also: how much non-ASCII is present, since one visual character can be 2–4 bytes.

### OQ-13 — "next Monday" semantics  **CLOSED**

The next INSTANCE of Monday, not the Monday of next week. A schedule is written
before the day it names, so the nearest forward match is what the writer meant.
`Policy.next_weekday_min_offset = 1`; set it to `7` for the other reading.

### OQ-14 — what happens to non-temporal text?  **CLOSED: it is the title**

Closed once as "leave it untagged", then REVERSED the same day.

The first answer said `please arrive early` answers none of the three questions,
so it should be dropped. Measurement showed that conflicts with the rule sitting
next to it: if everything non-temporal is SUMMARY then chatter is SUMMARY too,
and no rule separates `dinner` (a real title fragment) from `bro dont forget your
towel` (chatter). Telling those apart is judgement, not pattern.

Resolved in favour of keeping it. `Gym, bro dont forget your water bottle and
towel please` is how the writer wanted the note to read, and silently discarding
someone's own words is the worse failure. No DESCRIPTION slot — it lands in
SUMMARY, with non-adjacent fragments joined by a comma.

Effect: SUMMARY F1 0.565 → 0.717, whole-event exact match 0.512 → 0.689.

### OQ-15 — time-of-day words  **CLOSED**

Implemented as symbolic `TOD:` values resolved by policy at L3. Measured 3.3%
load-bearing (no clock time present) and 7.0% redundant (a clock time is also
there, so the word is ignored). A time-of-day word beside a bare hour also SETS
the meridiem: `3 in the morning` is 03:00, not the 1–6 default of 15:00.

Named holidays were not implemented on that pass — 0 hits in 512 real strings —
but were added later, once it was clear the zero came from the prompt design
rather than from the world. See `holidays.py`.

### OQ-16 — LOCATION slot  **CLOSED: removed**

A place is part of the answer to "what goes on the calendar", so it belongs in
SUMMARY, the same call already made for PERSON. Keeping it measurably hurt: at
0.43 F1 it was the weakest slot, and every missed location became a SUMMARY
boundary error as well.

Folding PERSON in too was tested and was WORSE (0.689 → 0.643) — `with X` is a
reliable cue for where the title ends, so that span earns its place.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| v0 | 2026-08-26 | Initial draft. Written pre-corpus; all open questions unanswered. |
