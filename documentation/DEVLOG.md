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