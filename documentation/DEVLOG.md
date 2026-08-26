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