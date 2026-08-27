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

### Phase 8: Annotating everything, and the first honest number

Annotated all 309 dev strings. Three friends wrote batch 01, four more wrote batch 02, and the second batch is where the corpus finally got interesting &mdash; they wrote the NOT-A-SCHEDULE cells. `Ms. Sunday in Accounts Payable`. `the pallet Sat in the alley for 2 hrs`. `AUGUST FROM THE FLOWER STALL`. I could not have invented those.

First real scores against gold, one per question:

| | rules | target |
|---|---|---|
| Q1 is it a schedule | 100% false-schedule | <= 5% |
| Q2 what goes on it | 0.650 | >= 0.75 |
| Q3 when | 0.820 / 0.857 | >= 0.90 |

Q1 is a total failure and I'm fine with that. A regex that matches `Sat` cannot see whether the sentence is about scheduling. That is not a tuning problem, it's the wrong tool. Determining it is a _judgement_, and judgements are what the model is for. Same with the summary text. Same, partly, with where the temporal info actually is. Three judgements, which is exactly the three questions again.

Two slot decisions, both settled by measuring instead of arguing:

1. **Killed LOCATION.** A place is part of what goes on the calendar, so it belongs in the summary &mdash; same call I already made for PERSON. It was also the worst slot at 0.43 F1, and because summary is defined as the residual, every missed location became a summary error too. One fix, two metrics.
2. **Kept PERSON.** Tried folding it in as well, since consistency said I should. It got _worse_ (0.689 to 0.643). `with X` turns out to be a reliable signal for where the title ends, so that span earns its place. Consistency lost to evidence.

Then the chatter question. `gYm tmrw at 6pm bro dont forget your water bottle and towel please` &mdash; is the bro part of the title? I'd earlier said no, drop it. Changed my mind. `Gym, bro dont forget your water bottle and towel please` is exactly how the writer would want that note to look. It's charming. Keeping it also reversed OQ-14, which I'd closed the other way a day earlier.

Where I got it wrong: I re-derived every gold summary using the same trim code the parser uses, then reported the score as if it meant something. It didn't. Gold and parser were making identical trim mistakes and scoring them as agreement &mdash; leading commas, dangling `til`, articles stripped off the front of titles. Fixed the trim, and the number fell from 0.717 to 0.650. The lower one is the real one.

TLDR: gold that is _derived_ instead of _annotated_ stops being an independent measurement. If the thing being measured and the yardstick share code, the yardstick is decoration. Worth remembering before I touch the test set.
### Phase 9: Segmentation, or how many events is this

The one gap I'd been carrying since M5. `Monday 12pm, Wednesday 5pm Laboratory` flattened to one event and Wednesday silently became noon. I'd written it in as a test that asserts the broken behavior so it would fail loudly the day I fixed it.

First thing I got right was measuring before designing. My gut said multi-event was common; a comma-counting regex said 14.5%. Actually annotating it says **4.9%**, 12 items out of 244. And of those 12, only 3 share a subject. So the thing I was about to build a general machine for barely happens.

Second thing was deciding the scope instead of inferring it. `Class MW 9, lab F` &mdash; one prompt, two subjects. I don't want that in the pipeline. **One prompt is one subject.** Even if it takes several VEVENTs to express the timing, the subject is the same. That kills most of the problem outright.

So there are only two reasons a line becomes multiple events, and they're unrelated:

1. **Two subjects.** `Monday call the dentist, Wednesday pick up the meds`.
2. **One subject, slots that can't share a rule.** `Lab Mon12pm Wed5pm`. That's the RFC 5545 cross product again &mdash; one VEVENT there schedules four occurrences instead of two.

Then I asked whether this couldn't just be a parser-parser like the date resolver, and it can. Cut at a delimiter, run the span proposer on each half, keep the cut only if **both halves stand alone** &mdash; own day slot AND own subject. Recurse. That one test does everything: `Mon, Wed and Fri` doesn't cut because neither half has a subject, `gym tmrw, 7pm start` doesn't cut because the right half has no day.

Grouping within a subject needed its own trick. A day slot that repeats starts a new event, but only if another slot sits *between* it and the previous one of its type. Without that gap test a day list splits three ways. With it, `Lab Mon12pm Wed5pm` splits and `Mon Wed Fri 9am` doesn't.

Also found an ordering constraint I didn't expect. Segmentation has to run **before** span proposal, not after. The bare-weekday rule treats a second day slot as evidence of recurrence, and that's only true inside one subject &mdash; `Lab Mon12pm Wed5pm` is weekly, `Monday call X, Wednesday call Y` is two one-off dates. Same spans, opposite answers. The segment boundary is the thing that tells them apart, so it has to exist first.

One string, `Lab Mon12pm Wed5pm`, turned out to be hiding two separate bugs. The time regex had one lookbehind for every branch, so a time flush against a letter never matched and both clock times fell into the summary. And the weekday demotion promised in its own comment to count a second recurrence span as repetition, then never implemented the clause. Neither had anything to do with segmentation; I only saw them because I had a case that needed both.

Left one gold item disagreeing with me: `tmrw meet the sneaker buyer at the mall then deliv the bars`, annotated as two events. Two subjects sharing one time, which is the exact inverse of the case I decided to support. Relabelled it to one event. If gold contradicts the spec, one of them is wrong, and this time it was gold.

| | before | after |
|---|---|---|
| event count correct | &mdash; | **244/244** |
| single events falsely split | &mdash; | **0/233** |
| temporal exact | 0.820 | **0.861** |
| RRULE equivalence | 0.857 | **0.897** |
| whole-event exact | 0.627 | 0.664 |

RRULE is three items off target now. Zero false splits matters more to me than the 11/12 catch rate &mdash; a wrong split wrecks a line that already parsed fine, a missed split leaves it exactly where it was.

Last thing, and it's the annoying one. My `check()` helper appends to a list and prints; it never raises. Running under pytest, that meant every failing check was invisible and the suite reported "12 passed" while I was actively changing behavior underneath it. Only caught it because I expected a test to break and it didn't. Added the assertion that actually fails the run.

TLDR: a test that can't fail isn't a test, it's a print statement. Same shape as the gold problem last phase &mdash; both times the measuring instrument was quietly agreeing with whatever I did.

### Phase 10: The test set, and the number I didn't want

Annotated all 98 test strings myself. I'd been arguing against this on the grounds that derived gold isn't a measurement, and the counter-argument won: a human annotating would be applying the same three rules from the same guide, and the point of the labels is to teach those rules. So the honest framing isn't "don't do it," it's "say what it is." This measures the parser against *my* judgment, not against a second person. Written into the commit so nobody reads it as more than that.

What I did keep is the part that actually mattered: I never looked at a parser proposal. Read the line, decide the spans, move on. Offsets are resolved by forward scan from the span texts, and every flag that's a pure function of the span set gets cross-checked against what I wrote by hand instead of overwriting it. That check caught exactly one slip in 98, which is about the rate I'd expect and the reason to run it.

Settled a handful of judgment calls against dev precedent rather than inventing them: time-of-day words are TSTART only when there's no clock time (`every tues night at 9PM` puts `night` in the summary), month-day takes no `on` prefix but ordinals do, a count bound promotes a bare weekday from DATE to RECUR. Found one stale dev row while I was at it &mdash; `the Monday after All Souls Day` was marked unrepresentable while three identical-shaped rows were fine, and that exact phrase is the worked example in the IR's own comment.

Then the numbers.

| | dev | test |
|---|---|---|
| status accuracy | 0.793 | 0.796 |
| false-schedule | 1.000 | 1.000 |
| SUMMARY F1 | 0.659 | **0.559** |
| event count | 1.000 | **0.910** |
| temporal exact | 0.857 | **0.564** |
| RRULE equivalent | 0.894 | 0.718 |

Temporal exact drops 29 points. My first instinct was that I'd annotated test wrong.

I hadn't. It's one construction. Bryan writes `8am gym 9am` &mdash; start time, title, end time, no dash, no `to`, nothing. The parser reads the second time as another start. Nineteen of 78 schedulable test items are shaped like that, and temporal exact on those nineteen is **0.000**. Not low. Zero. Six of the seven event-count misses are the same bug downstream: a second TSTART with a day between them looks exactly like the multi-event pattern I just built, so it splits one event in half. Take those nineteen out and test goes 0.564 → 0.746.

The construction appears in zero dev rows and zero harvested strings. Every other instance of two times in one line has a connector &mdash; `to`, `until`, `through`, an en dash. So it's one person's house style that the parser had never once seen, and it took the whole thing down 29 points.

That is exactly the Geva et al. result, reproduced by accident on 98 strings. Held-out annotators aren't a formality. I built the split that way months of reasoning ago because a paper said to, and it just paid for itself.

And now the discipline problem: I know how to fix it in about ten minutes, and I'm not going to. Fixing a parser against the held-out set is how a test set stops being one. Same for the three other defects I found while poking at it &mdash; a greedy `NO ...` negation that eats the rest of the line, `next weds` not resolving, and `the tues after Halloween` silently flattening to Halloween itself, which is a silent catastrophic error by my own definition. All four are written up in FINDINGS.md under a heading that says don't fix these without re-splitting.

TLDR: the split did its job, which is to embarrass me. A number that only exists because the parser was built next to the data isn't a number.

### Stepping back: what the data actually is now

Worth writing down where this landed, because it is not where I started.

The plan on day one was: write 500 lines myself, find the patterns, augment. Every part of that turned out to be wrong in a different way. I can't write 500 lines without baking in my own idiolect. The patterns were never the hard part. And "augment" was doing a lot of work in that sentence for something I hadn't thought through.

What it became instead:

| | |
|---|---|
| harvested real strings | 610 |
| human-written strings | 407, from 7 people |
| fully annotated gold | 407 rows &mdash; 323 ok, 56 not-a-schedule, 18 unrepresentable, 10 unresolvable |
| dev / test | 309 / 98, split by author |
| generator axes | 9 |
| negative frames | 36, in 9 families &mdash; 8,048 distinct strings per 20k draws, up from 24 |
| weekday sets renderable | 127 |

The shape of it flipped somewhere around phase 8 and I didn't notice at the time. The human data stopped being the training set and became the **measuring stick**. 407 strings is not enough to train anything. It is more than enough to tell me whether a thing works, and to tell me *what kind* of writing exists in the world &mdash; which is the part I could never have invented, and the part that makes the synthetic layer honest instead of circular.

Because that's the trap I kept almost walking into. A generator I write, scored against gold I derive from the same code, is a machine for producing numbers that mean nothing. It happened once with the SUMMARY trim and cost me 0.067 of fake score. The defence isn't "don't generate", it's: **generate the training data, harvest the yardstick.** Real people wrote `Ms. Sunday in Accounts Payable` and `the pallet Sat in the alley for 2 hrs` and `8am gym 9am`. I write the 8,000 variations of things I already know are schedules.

The negatives are the clearest case. 56 humans-written not-a-schedule lines, which are the entire evaluation set for question 1 and are never trained on. From reading those 56 I could see *why* each one wasn't a schedule &mdash; day-as-name, day-as-verb, cancellation, question-about-when, number-that-isn't-a-time &mdash; and sampling the reason instead of the string took it from 24 distinct to 8,000. The frames are mine. The insight that "august body" is a thing people write isn't.

Same story with the weekday sets. There are 127 usable combinations and the corpus naturally contains about 13 of them, because people write MWF and TTh and almost nothing else. If I want the model to know SatSun and MoThSu are the same kind of object as MWF, that has to be manufactured. No amount of collecting gets there.

So: mostly synthetic, deliberately, with the human data doing the two jobs it's actually good at &mdash; telling me what real text looks like, and grading.

None of this is a model yet. Everything above is data, an IR, a rule baseline, and a scorer. The baseline is frozen at 1.000 false-schedule, which is a complete failure at question 1 and always was going to be &mdash; a regex that matches `Sat` cannot see whether the sentence is about scheduling. That's the whole argument for the thing I'm about to build, and it's now measured rather than asserted.

TLDR: I set out to collect data and ended up collecting judgement. The corpus is small on purpose. The generator is large on purpose. Next entry should have a loss curve in it.
