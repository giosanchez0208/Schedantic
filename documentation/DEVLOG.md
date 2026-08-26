# Devlog
A/N: This is my attempt at logging my thought process throughout the whole project from start to completion. I already have the idea: Create a model that converts schedule NL to jCal format. 

[ 8/26/2026 ]

## Phase 1: Dataset Generation

To start, we'll manually write the first few lines of data in our dataset. My instinct tells me we'll be following this pipeline after initial dataset construction:
1. Find patterns in how these sentences were constructed
2. Use that as basis for tokenization 
3. Use the identified patterns to "augment" our dataset.
   
Item 2 is where I got it wrong. If we go byte-level, there is no tokenizer to design. The vocabulary of our dataset is 256 plus a few special characters. Byte-level models degrade less under typos, casing chaos, and unseen character sequences than subword models, and can even handle abbreviations without splitting artifacts. This robustness _is_ the feature that separates our model from parsers and wrappers that tackle the same problem.

TLDR: "Auto-tokenization from discovered patterns" would be solving a problem we've already designed away.

A [paper by Geva, Goldberg, and  Berant](https://aclanthology.org/D19-1107.pdf) already looked at crowdsourcing from high-quality annotators to massively generate examples. Key findings:
- Model performace improves when you add "annotator identifiers" as features, which means the model learns the annotator and not the task.
- Models can identify which annotator wrote an example.
- Models do not generalize to examples from annotators absent from training.

So their recommendation is something that already exists in any machine learning evaluation problem. Which is that test set annotators should be disjoint from training set annotators. This is just a diagnostic probe.

I've decided to keep the more technical details behind the design for the NL &rarr; IR &rarr; jCal [here](IR_SPEC_v0.md).

## Phase 2: The IR is three layers

Splitting it: L1 is spans over the raw text (what it _says_), L2 is normalized symbolic semantics (what it _means_), L3 is jCal. The reason is annotation. If I merge them, then labeling means _I_ decide by hand, 500 times, whether bare "8" is 08:00 or 20:00, and I will not be consistent about it. Keep the spans dumb and put the defaulting policy in code where I can change it without re-annotating anything.

Second reason: L2 never stores a resolved date. If gold said `2026-08-27` it would be welded to the day I wrote it and the test set rots. Symbolic only. `until December` is `REL:MONTH_12`, meaning _the next December_, not December of whatever year I happened to be annotating in.

Also learned that RFC 5545 can't pair a weekday to a time. `BYDAY=MO,WE;BYHOUR=12,17` gives you the cross product &mdash; four occurrences, not two. So "Monday 12pm, Wednesday 5pm Lab" is two VEVENTs. Means `events` is a list from day one.

## Phase 3: Data, and what real schedule text actually looks like

I can't write my own dataset without baking in my own idiolect, and I can't have Claude write it either. That just measures the generator against itself. Compromise: harvest real human-written strings from public parser test suites (ctparse, Duckling, chrono, recurrent, Sherlock, natty) plus a forum thread where students typed out their own schedules. 610 strings, 305 of them close to my target register. Spot-checked two sources by hand and they're real.

Built the deterministic layer and the scorer _before_ anything else, so there's something to measure with. RRULE equality is compared by expanding occurrence sets, never by string &mdash; `BYDAY=MO,WE` and `BYDAY=WE,MO` are the same rule.

Findings that actually changed my plans, full writeup [here](FINDINGS.md):

1. **AM/PM ambiguity is ~26% of real strings, 37% of the informal ones.** I assumed this was an edge case. It isn't, it's a third of the data. It gets its own metric now.
2. **COUNT bounds ("for 10 weeks", "x8") appear literally zero times.** Natural sampling will never teach it. Has to be hand-written on purpose.
3. **DURATION is under 1%.** Dropping the slot. "for 2 hrs" becomes a normalization rule that computes TEND.
4. Negation is 0.3%, so EXDATE gets deferred and "except holidays" stays `unrepresentable`.

Biggest thing I got wrong: I sampled the axes uniformly at first and got a corpus that was 46% multi-event and 46% location. Complete coverage, garbage distribution. Coverage and realism are different jobs, so there are two pools now &mdash; balanced for class coverage, realistic for calibration.

TLDR: the NLP was never the hard part. It's the data, exactly like the research said.

Next: write the 500 myself. [COVERAGE_GAPS.md](COVERAGE_GAPS.md) ranks what's missing so I fill cells instead of writing 500 variants of my five favorite patterns. Still need to write down an accuracy target before the rule baseline gives me a number, otherwise I'll just reverse-engineer the target from whatever I get.

[ 8/27/2026 ]

## Phase 4: Outsourcing Data

Didn't write the 500 myself in the end. I had three friends help me write entries. Better than what I planned, because now the test set can be an entire held-out person instead of a random slice of my own writing. That is the actual Geva et al. recommendation, not an approximation of it. One of them is test (48), two of them are dev (159). I wrote none of it, which means I'm a fourth unseen author at deployment.

Also declared the accuracy target before running anything, which was the thing I said I'd do and nearly didn't. TARGET.md.

## Phase 5: Annotation

Wrote an annotation tool that pre-fills spans with the rule parser so I correct instead of typing. Two things went wrong immediately.

First, I looked at the 40 pre-annotated items and thought "looks right." That's the exact failure the pre-annotation causes. Seeing a filled-in answer makes it look correct. Real edit rate turned out to be 2 out of 40, so it mostly was right, but I wasn't checking, I was agreeing. Test set is emitted blank for this reason: if gold matches the rules because gold was copied from the rules, M5 scores near-perfect and tells me nothing.

Second, I hit `Biweekly staff meeting every other Tuesday` and couldn't tell which recurrence span to keep. Turned out the answer is both, and the instruction to delete one was wrong. If `Biweekly` is tagged when it's alone but dropped when a fuller phrase sits nearby, the model sees the same string labeled two ways and learns neither. Consistency beats elegance. Merging redundancy is the normalizer's job. Wrote [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md) so these get decided once instead of re-argued.

Renamed the `UNTIL` span to `BOUND` while I was there. `x8` is a count, not a date, and the old name implied otherwise.

## Phase 6: The Rule Baseline

Built the L1 → L2 normalizer, which was the missing link. Pipeline now runs end to end: text → spans → structured event → jCal. 6/7 on the hand-written fixtures.

The one failure is `Monday 12pm, Wednesday 5pm Laboratory`. Rules flatten it to one event and Wednesday silently becomes noon. That's the RFC 5545 cross-product trap showing up as a real miss, and it's a silent catastrophic error by my own definition: wrong time, no warning. Wrote it in as a test that asserts the broken behavior so it fails loudly the day segmentation lands.

Then the finding that reframed everything. Ran the rules over 25 strings that shouldn't be schedulable at all:

**25 out of 25 got scheduled.** `nvm` becomes an event today. `Sat down for coffee` becomes a weekly Saturday. `Fri is short for Frida` becomes a weekly Friday.

Rules fail at this structurally, not by accident. A pattern that matches `Sat` has no access to whether the sentence is about scheduling. That needs sentence-level context, which is what a model has and a lookup table can't. Every existing tool has the same hole. chrono, Duckling, ML Kit will all happily pull March out of "March was fun." This is the strongest argument for the model existing that I've found.

### Phase 7: Three questions

Which is where it got simple. The whole product is:

1. Is it a schedule?
2. What goes on the calendar?
3. When?

That's it. Stupidly simple, even if the work to get there is intricate. Restructured [TARGET.md](target.md) into three groups of thresholds, one per question, each cleared independently. Worth noting question 1 had no threshold at all before this. The worst number in the project was sitting outside the gate.

The framing immediately started deciding things:

- Killed the DESCRIPTION slot. `please arrive early` isn't an answer to any of the three questions. Untagged, dropped, done.
- Built the time-of-day interpreter. `morning`, `tmrw afternoon`, `at dawn` are answers to question 3. Measured 3.3% of real strings where it's load-bearing (no clock time present), 7.0% where it's redundant. Symbolic TOD:MORNING at L2, policy collapses it to 08:00 at L3, same as dates. Flagged time_approximate so the UI can say "~8am" instead of faking precision.

TLDR: every simplification this week came from measuring, not from thinking harder. The IR has picked up four open questions since it was written, and all four came from implementing or annotating. None from imagination. Writing the spec first was still right, but doubting it was always an option.