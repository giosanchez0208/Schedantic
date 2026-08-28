# Prior art: what the temporal-annotation field already settled

Written 2026-08-28, after being told to stop guessing and go read. Every claim
below was fetched during that session; sources at the bottom.

The short version: most of what we have been calling open questions are closed
questions elsewhere, our `unrepresentable` bucket is partly a design gap rather
than a language limit, and there is a free, permissively licensed negative
corpus that our model fails 79% of.

---

## 1. The standards

**TIMEX2** (MITRE/DARPA TIDES, 2003) and **TIMEX3** (TimeML, later ISO-TimeML)
are the two annotation standards for temporal expressions. TIMEX3 keeps TIMEX2's
`DATE`/`TIME`/`DURATION` and adds `SET` for recurrence. Values normalize to ISO
8601 with documented extensions.

**SCATE** (Semantically Compositional Annotations for Temporal Expressions) is
the modern alternative, explicitly built because ISO-TimeML "limits expressivity
and struggles with complex constructs". It models time as Intervals, Repeating
Intervals, Periods, and *operators over them*: Last, Next, Before, After, Nth,
This, Between, Intersection, These, LastN, NextN, ShiftUnion,
RepeatingIntersection.

---

## 2. Where our design already agrees

Reassuring, and worth recording so we stop relitigating:

| ours | theirs |
|---|---|
| L2 never stores a resolved date | TIMEX2 normalizes against a document creation time |
| `REL:NEXT_MO@REL:MD_11_2` | `ANCHOR_VAL` + `ANCHOR_DIR` (BEFORE / AFTER / AS_OF / WITHIN) |
| symbolic `REL:MD_9_3` so gold cannot expire | same motivation for underspecified `XXXX-09-03` |
| `TOD:MORNING` etc. | part-of-day tokens, below |
| status `unrepresentable` as a first-class label | TIMEX2 has explicit non-markable categories |

Our recursive `@` composition is the same idea as `ANCHOR_DIR`, and SCATE's
`Next`/`After` operators are the same idea again. That one was right.

---

## 3. Where they have a name for something we improvised

### Part-of-day tokens (TIMEX2 Table 4-8)

The value is appended to the date after `T`:

| token | meaning | ours |
|---|---|---|
| `MO` | morning | `TOD:MORNING` |
| `MI` | mid-day | — (we collapse to exact 12:00) |
| `AF` | afternoon | `TOD:AFTERNOON` |
| `EV` | evening | `TOD:EVENING` |
| `NI` | night | `TOD:NIGHT` |
| `DT` | daytime / working hours | **we have nothing** |

So `1999-07-15TMO` is "the morning of July 15". Durations use `PnMO`, `PnNI`.
We have no `DT`, which is what "during the day", "sometime today", "working
hours" mean -- and no `MI`.

The rule they state and we do not: *"these tokens are only used if the precise
time of day is not present in the expression"*. That is exactly the redundancy
gate in preannotate, arrived at independently and measured at 7.0% redundant vs
3.3% load-bearing.

### MOD: the dimension we flattened

TIMEX2/TIMEX3 carry a separate `MOD` attribute with twelve values:

`BEFORE`, `AFTER`, `ON_OR_BEFORE`, `ON_OR_AFTER`, `LESS_THAN`, `MORE_THAN`,
`EQUAL_OR_LESS`, `EQUAL_OR_MORE`, `START`, `MID`, `END`, `APPROX`

We squash all of this into one boolean flag, `time_approximate`. Consequences we
are already living with:

- `early morning` is `START` + `TMO`; we emit `TOD:MORNING` and lose "early".
- `late night` is `END` + `TNI`; we lose "late".
- `about 5` is `APPROX`; `no more than 10 days` is `EQUAL_OR_LESS`; both are just
  "approximate" to us, or nothing.
- `mid-February` is `MID`; we cannot say it at all.

Our generator emits "early morning" and "late night" as surfaces and then throws
the modifier away. That is a real information loss with a standard fix.

### PRESENT_REF / PAST_REF / FUTURE_REF

TIMEX2 assigns whole-span alphabetic tokens for expressions that name a
direction rather than a point: `now`, `currently`, `nowadays` become
`VAL="PRESENT_REF"` with `ANCHOR_DIR="AS_OF"`.

**This is the independent confirmation that refusing "later" was wrong.** The
standard's answer to a vague direction word is to give it a value and an anchor
direction, not to decline. `TOD:LATER` (added 2026-08-28) is the same move; the
standard would spell it `FUTURE_REF` anchored `AFTER` the reference.

### Seasons and weekends

`SP` / `SU` / `FA` / `WI` for seasons, `WE` for weekend as a positional token:
`1999-W28-WE` is "this weekend". We render weekends as `BYDAY=SA,SU`, which is
occurrence-equivalent but loses the concept -- and we have no season token at
all, in a corpus containing "fall semester" and "the rainy season".

---

## 4. The finding that changes what `unrepresentable` means

Several things we label `unrepresentable` are representable in TIMEX2 using **X
placeholders** in the value plus `FREQ`/`QUANT`:

| expression | TIMEX2 |
|---|---|
| hourly | `FREQ=EVERY`, `VAL=XXXX-XX-XXTXX` |
| **almost weekly** | `FREQ=LESS_THAN_EVERY`, `VAL=XXXX-WXX` |
| every July | `FREQ=EVERY`, `VAL=XXXX-07` |
| every Thursday in 1999 | `FREQ=EVERY`, `VAL=1999-WXX-4` |
| the past three summers | `QUANT=3`, `VAL=XXXX-SU`, `ANCHOR_DIR=BEFORE` |
| **numerous Saturdays last summer** | `QUANT=X`, `VAL=1998-WXX-6`, `ANCHOR_DIR=WITHIN` |

`LESS_THAN_EVERY` and `QUANT=X` cover "mostly Sundays" and "2-3x a week", which
we currently refuse as `unrepresentable`. SCATE's `Between` operator covers
`Oct 21-23`, our other refusal category. So at least two of our eight refusal
families are a schema gap on our side, not a property of language.

Worth weighing against that: TIMEX2 **removed** its `GRANULARITY` and
`PERIODICITY` attributes between versions because they "were insufficient for
the task and were confusing to annotators". Adding expressive power to a schema
has a cost they paid and documented. We have one annotator and 407 rows; that
warning is aimed straight at us.

---

## 5. The immediately usable thing: Duckling's negative corpus

`facebook/duckling` (BSD-3) ships `Duckling/Time/EN/Corpus.hs` with ~1,100
positive examples and a **`negativeCorpus`** of 28 strings a production temporal
parser is asserted *not* to parse. We already harvested Duckling's positives
during the corpus build; we never took the negatives.

Measured 2026-08-28 against `tagger_v4`:

```
  model schedules : 22/28 = 0.79   (should be 0)
  rules schedule  : 28/28 = 1.00   (should be 0)
```

Failing at p(ok) = 1.00: `25`, `3 30`, `Rat 6`, `4a`, `A4 A5`, `Pay ABC 2000`,
`at 650.650.6500`, `two sixty a m`, `three twenty`, `two three`, `palm`,
`Martin Luther King' day`, `1 adult`, `this one`, `at a few`.

The classes are legible and they are ours:

- **phone numbers** -- `at 650.650.6500`, and our dot-time fix makes this worse,
  since `650.650` now looks more like a time than it did
- **product / seat / room codes** -- `Pay ABC 2000`, `A4 A5`, `Rat 6`
- **bare quantities** -- `25`, `1 adult`, `at a few`, `at dozens`
- **spelled-out numbers** -- `three twenty`, `two sixty a m`, `two three`
- **truncated holidays** -- `palm` (Palm Sunday), `Martin Luther King' day`
- **pronoun "one"** -- `this one`, `this past one`, mistaken for an ordinal

Our own probe put `neg_number` at 0.00 on 8 items. This is a wider, externally
curated set and it says the problem is bigger than we had measured.

**These stay evaluation.** Training on them destroys the measurement, exactly as
with the 56 human negatives and the 28 human refusals. What may be lifted is the
*class* -- a phone-number frame, a product-code frame -- never the string.

---

## 6. What I would do with this

Ranked by evidence, not by appeal:

1. **Negative frames for the six Duckling classes.** The largest measured gap in
   the project, now with an independent yardstick that is not mine.
2. **Add `MOD`.** START / MID / END / APPROX / BEFORE / AFTER as an L2 field.
   Cheap, standard, and it recovers "early", "late", "about", "mid-" which the
   generator already writes and the IR already discards.
3. **`TOD:DAYTIME`** for `DT`, and decide whether `MI` is worth having.
4. **Reconsider two refusal families** -- fuzzy frequency and date ranges --
   against the X-placeholder and `Between` treatments, while remembering that
   TIMEX2 deleted two attributes for being too confusing to annotate.
5. **Vendor Duckling's positive corpus as a second dev set.** ~1,100 examples in
   a register close to ours, BSD-3, with expected values attached.

Seasons and the weekend token are real gaps but rank below these.

---

## Sources

- [TimeML Specification 1.2](https://www.cs.brandeis.edu/~cs112/cs112-2004/annPS/TimeML12wp.htm)
- [TIDES 2003 Standard for the Annotation of Temporal Expressions v1.3](https://catalog.ldc.upenn.edu/docs/LDC2010T18/2003_timex2_standard_v1_3.pdf)
- [ISO-TimeML: An International Standard for Semantic Annotation](https://www.researchgate.net/publication/43406713_ISO-TimeML_An_International_Standard_for_Semantic_Annotation)
- [TempEval-3: Evaluating Events, Time Expressions, and Temporal Relations](https://arxiv.org/pdf/1206.5333)
- [A Semantic Parsing Framework for End-to-End Time Normalization (SCATE)](https://arxiv.org/html/2507.06450)
- [Time expression recognition and normalization: a survey](https://dl.acm.org/doi/10.1007/s10462-023-10400-y)
- [facebook/duckling Time/EN/Corpus.hs](https://github.com/facebook/duckling/blob/main/Duckling/Time/EN/Corpus.hs)
- [facebook/duckling](https://github.com/facebook/duckling)
