# Roadmap

`[x]` done · `[~]` in progress · `[ ]` not started · **bold** = currently blocking

Last updated 2026-08-26.

---

## Milestones

| | # | Milestone | Done when | Artifact |
|---|---|---|---|---|
| `[x]` | M0 | Fixtures | 7 example strings hand-mapped to **L2** (never jCal), all validating | [tests/test_core.py](../tests/test_core.py) |
| `[x]` | M1 | IR schema v0 | L1/L2 dataclasses + validation; 12 open questions *enumerated* | [ir.py](../src/stlm/ir.py) · [IR_SPEC_v0.md](IR_SPEC_v0.md) |
| `[x]` | M1.5 | Accuracy target declared | Per-slot thresholds written **before** any baseline number exists | [TARGET.md](TARGET.md) |
| `[x]` | M2 | Converter | Fixtures pass **and** every default is a config knob, not a constant | [convert.py](../src/stlm/convert.py) |
| `[x]` | M3 | Scorer | Own tests pass, incl. equivalent-but-different-string RRULE pairs | [score.py](../src/stlm/score.py) |
| `[x]` | M3.5 | Reality reference corpus | ≥500 real unlabeled strings, provenance-tracked, spot-verified | `corpus/harvested.jsonl` (610) |
| `[~]` | **M4a** | **Tier A human gold** | **500 strings collected, split sealed, annotated to L1+L2** | `corpus/human_raw.jsonl` (207) |
| `[ ]` | M4b | Tier B silver dev set | Generated dev set, meaning-first, verified against M5 | — |
| `[ ]` | M5 | Rule baseline → IR | A number on Tier A dev. **This is the bar.** | — |
| `[ ]` | M6 | Error analysis | **Branch gate** — categorized failures + ship-rules-or-build-model call | — |
| `[x]` | M7a | Generator infrastructure | Emits balanced classes, 0 validation failures at scale | [generate.py](../src/stlm/generate.py) |
| `[ ]` | M7b | Generator calibration | `AXIS_PRIOR` recalibrated from M4a; sample survives M5 | — |
| `[ ]` | M7c | Lexicon mining | Surface tables evidence-backed, not seeded from priors | [lexicon.py](../src/stlm/lexicon.py) |
| `[ ]` | M7.5 | Segmentation mechanism | A chosen answer for how the model emits `event_groups` | — |
| `[ ]` | M8 | Byte-level tagger v0 | Beats or loses to M5 — either is informative | — |
| `[ ]` | M9 | Data iteration | *(phase marker, not a gate)* | — |
| `[ ]` | M10-R | **If rules win:** package rule engine | Ships without a model | — |
| `[ ]` | M10-N | **If model wins:** compress + export | Accuracy delta <1–2%, latency on real hardware | — |
| `[ ]` | M11 | On-device integration | — | — |

---

## The M6 branch

The project is **"best parser wins."** M6 is a real gate, not a formality:

- Rule baseline clears every [TARGET.md](TARGET.md) threshold → **M10-R**, ship rules, no model.
- It doesn't → **M7.5 → M8 → M10-N**.

M10-R and M10-N are mutually exclusive. Only one gets built.

---

## Blocking now

1. **M4a** — 207/500 strings. Needs: the rest collected, the split sealed, then annotation to L1+L2.
2. **M7.5** — segmentation is unsolved and blocks M8. Flat BIO has no way to say which event a span belongs to, and multi-event is 14.5% of the corpus. Don't discover this inside M8.

Everything downstream of M5 is speculation until M4a exists.

---

## Dependencies worth remembering

- M5 cannot start before **M1.5** (done) and **M4a**.
- M4b's verifier *is* the M5 baseline, so M4b cannot finish before M5.
- M7b needs M4a to recalibrate against. Until then `AXIS_PRIOR` is mostly guesses,
  tagged `[H]` in source where harvest-anchored.
- M8 needs M7.5 decided first.

---

## Open questions

Tracked in [IR_SPEC_v0.md](IR_SPEC_v0.md), answered in [FINDINGS.md](FINDINGS.md).
Everything currently decided by default or judgement rather than evidence:
[OPEN_DECISIONS.md](OPEN_DECISIONS.md).

| State | OQs |
|---|---|
| Answered with evidence | OQ-1, OQ-4, OQ-5, OQ-8, OQ-9, OQ-12 |
| Answered, weak evidence | OQ-3, OQ-7 |
| Open | (none from the original 15) |
| Closed | OQ-2 · OQ-6 · OQ-10 · OQ-11 · OQ-13 · OQ-14 · OQ-15 |

---

## Resolved decisions

Do not re-litigate these without a reason recorded here.

| Decision | Why |
|---|---|
| Best parser wins; model is optional | M6 can legitimately end the project |
| Python-only through M9 | `dateutil.rrule` is the reference impl; port only at M11 |
| Gold is L2, never jCal | jCal serialization isn't canonical; slot F1 needs slots |
| L2 dates are symbolic, never resolved | Otherwise gold expires and the test set rots |
| Spans non-overlapping; SUMMARY is the residual | Flat BIO can't emit overlapping spans |
| `events` is a list from day one | RFC 5545 can't pair weekday→time in one RRULE |
| `DURATION` span type dropped | 0.98% in real data; becomes a normalization rule |
| EXDATE deferred | Negation is 0.33%; "except holidays" stays `unrepresentable` |
| Two synthetic pools, balanced + realistic | Coverage and realism are different jobs |
| Contributor prompts carry no copyable examples | They caused 26.6% prompt-anchoring in batch 01 |
