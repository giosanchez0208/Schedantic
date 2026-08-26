# Annotation guide

Decidable rules for L1 annotation. If a case isn't covered here, that's a bug in
this document — add the case rather than guessing twice.

---

## The one rule

> **Tag every temporal expression you see. Do not rank them, do not deduplicate
> them, do not skip one because another says the same thing.**

The test is *"is this text a temporal expression?"* — never *"is this text
necessary?"*

**Why.** The tagger has to learn a consistent function from text to labels. If
`Biweekly` is tagged RECUR when it stands alone but dropped when `every other
Tuesday` happens to appear nearby, the model sees the same string labeled two
different ways and learns neither. Consistency beats elegance. Merging redundant
spans is the normalizer's job, and it is easy; recovering a span that gold
silently omitted is impossible.

---

## Span types

| Type | Tag it when the text… | Examples |
|---|---|---|
| `RECUR` | says the event repeats, or which weekdays | `MWF`, `every other Tue`, `Biweekly`, `daily`, `except Sunday` |
| `TSTART` | is a clock time the event starts at | `8`, `8am`, `0800`, `12nn` |
| `TEND` | is a clock time the event ends at | the `12` in `8-12` |
| `DATE` | is a specific day, absolute or relative | `tmrw`, `this Mon`, `Sept 3`, `the 15th` |
| `BOUND` | says when the *series* stops | `until Dec`, `till finals`, `x8`, `for 8 weeks` |
| `DURATION` | says how long it lasts, instead of an end time | `for 90 mins`, `2 hrs` |
| `PERSON` | names who is attending | `Sir Jefferson`, `mom`, `Ate Bea` |
| `LOCATION` | says where | `Rm 201`, `at the chapel`, `Zoom` |
| `SUMMARY` | is the title — everything left over | `CCC100`, `staff meeting`, `mass` |

`SUMMARY` is the **residual**: whatever is not one of the others. It never
includes a time, a weekday, a person, or a place.

Spans **must not overlap**. One character belongs to at most one span.

---

## Resolved cases

These are the ones that actually come up. Decided once, here, so they're
annotated the same way every time.

| Case | Decision |
|---|---|
| Two phrases say the same recurrence — `Biweekly … every other Tuesday` | **Tag both** as RECUR, same event. |
| Recurrence stated as base + exception — `every day but not Sunday` | **Tag both** as RECUR, same event. |
| Recurrence words inside a title — `Biweekly staff meeting` | `Biweekly` is RECUR, `staff meeting` is SUMMARY. Temporal words are never part of the title. |
| Title and place run together — `mass at the chapel` | SUMMARY `mass`, LOCATION `at the chapel`. |
| No title at all — `Every other Tue` | No SUMMARY span. Add flag `missing_summary`. That is a valid annotation, not a mistake. |
| Leading preposition — `at the chapel`, `in room 201` | Include it in the span. Be consistent: always include, never sometimes. |
| Connector between spans — the `with` in `X with Y` | Belongs to no span. Leave it untagged. |
| Bare hour, no am/pm — `MW 8` | Tag `8` as TSTART. Add flags `ampm_ambiguous ampm_inferred`. |
| Time range — `8-12nn` | TSTART `8`, TEND `12nn`. The `-` is untagged. |
| Two events in one line — `Class MW 9, lab F` | Nothing gets deleted. Split with the `events:` line. |
| Same text appears twice — `8am gym 9am` | Disambiguate with `#`: `TSTART \| 8am` and `TEND \| 9am #2` if needed. |

---

## `events:`

Default is `events: all` — every span belongs to one event. That covers most
lines.

When one line describes **two or more separate events**, list the spans per
event, separated by `;`:

```
> Class MW 9, lab F
SUMMARY  | Class
RECUR    | MW
TSTART   | 9
RECUR    | F
events: SUMMARY RECUR#1 TSTART ; SUMMARY RECUR#2
flags: multi_event
```

`RECUR#1` is the first RECUR in the list, `RECUR#2` the second. A span listed in
both groups (like `SUMMARY` here) is shared between the events.

You need this because RFC 5545 cannot bind different weekdays to different times
in a single rule — `Class MW 9` and `lab F` genuinely become two calendar
entries.

---

## `status:`

| Status | Use when | Example |
|---|---|---|
| `ok` | normal, even if underspecified | almost everything |
| `no_temporal` | no scheduling information at all | `ok thanks`, `My friends are to be wed` |
| `unresolvable` | a real event, but no defensible time can be chosen | `lunch sometime next week` |
| `unrepresentable` | **the schema genuinely cannot express it** | `vitamins daily except when I forget` |

`unrepresentable` is the most valuable label in the whole exercise. It is how the
IR finds out it is wrong. Always add a `note:` saying what broke.

Do **not** force a line into spans that half-fit. A wrong annotation is worse
than a flagged one.

---

## When you are genuinely unsure

Annotate what seems right and write a `note:`. A flagged uncertainty is useful
data; a silent guess is label noise.

If a case comes up twice and this document doesn't decide it, that means the
document is incomplete — say so and it gets added here.

---

## Reading order matters

For each item: **read the `>` line first, decide what the spans should be, and
only then look at the proposal.**

The proposals come from the rule-based parser that later becomes the M5 baseline.
If gold ends up matching the rules because gold was copied from the rules, M5
scores near-perfect and the number means nothing — the baseline would be grading
its own homework, and that false number feeds the M6 ship-or-build decision.

This is why the 48 test items are emitted blank.
