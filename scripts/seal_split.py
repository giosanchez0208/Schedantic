"""Seal the dev/test split by AUTHOR and write corpus/splits.json.

The split is by author, not random. Geva, Goldberg & Berant (EMNLP 2019) found
models learn annotator idiolect rather than the task, and recommend that test
annotators be disjoint from training annotators. A random split over a
3-author corpus would put all three authors on both sides and measure nothing.

Once sealed this file should not be regenerated. Re-running refuses to overwrite.
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.ir import read_jsonl

OUT = ROOT / "corpus" / "splits.json"

# Two authors held out, one from each writing batch.
#
#   bryan   batch 01. Lowest anchoring of that batch (17% vs 28% and 30%).
#   phil    batch 02. 0% anchoring, and he wrote 14 NOT-A-SCHEDULE strings.
#
# The batch-02 author is not optional. Question 1 ("is it a schedule?") has a
# threshold in TARGET.md, and only batch-02 authors wrote negatives -- a test set
# drawn from batch 01 alone cannot measure the project's headline capability.
TEST_AUTHORS = ["bryan", "phil"]


def main() -> None:
    force = "--force" in sys.argv
    if OUT.exists() and not force:
        print(f"{OUT.relative_to(ROOT)} already exists -- the split is SEALED.")
        print("Re-splitting after seeing results invalidates the test set.")
        print("Pass --force only if you are deliberately re-sealing before any")
        print("model or baseline has been evaluated against it.")
        return

    rows = read_jsonl(ROOT / "corpus" / "human_raw.jsonl")
    if not rows:
        print("no corpus/human_raw.jsonl -- run scripts/ingest_batch.py first")
        return

    test = [r for r in rows if r["author"] in TEST_AUTHORS]
    dev = [r for r in rows if r["author"] not in TEST_AUTHORS]

    def profile(rs):
        b = sorted(len(r["text"].encode()) for r in rs)
        return {
            "n": len(rs),
            "authors": dict(Counter(r["author"] for r in rs)),
            "prompt_anchored": sum(1 for r in rs if r.get("prompt_anchored")),
            "bytes_p50": b[len(b) // 2] if b else 0,
            "bytes_max": max(b) if b else 0,
        }

    doc = {
        "sealed": True,
        "split_by": "author",
        "rationale": (
            "Author-disjoint split per Geva, Goldberg & Berant (EMNLP 2019). "
            "A random split over 3 authors puts every author on both sides and "
            "measures memorised idiolect rather than task generalisation."
        ),
        "test_authors": TEST_AUTHORS,
        "test_ids": sorted(r["id"] for r in test),
        "dev_ids": sorted(r["id"] for r in dev),
        "test_profile": profile(test),
        "dev_profile": profile(dev),
        "caveats": [
            "bryan writes longer than the others (p50 37 bytes vs 24 and 29), so "
            "the test set is skewed toward longer strings. Report length-stratified "
            "scores alongside the headline number.",
            "Prompt anchoring means the three authors are not fully independent: "
            "26.6% of the corpus contains a verbatim example string from the batch "
            "prompts. Score with and without prompt_anchored rows.",
            "The project owner (Gio) wrote none of these, so he is a fourth unseen "
            "author at deployment. Any strings he writes later go to DEV, never test.",
        ],
        "reseal_history": [
            {"date": "2026-08-26", "test": ["bryan"], "n": 48,
             "reason": "initial seal, 3 authors"},
            {"date": "2026-08-27", "test": ["bryan", "phil"], "n": 98,
             "reason": "4 new authors added 200 strings that were in neither split; "
                       "and the batch-01-only test set contained zero negatives, so "
                       "Question 1 was unmeasurable. Legitimate because the test set "
                       "had never been opened -- no baseline had been scored on it."},
        ],
        "rules": [
            "Test is opened at most twice: once at the M6 gate, once at the end.",
            "New contributors' strings go to dev unless deliberately re-sealing.",
        ],
    }

    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"sealed {OUT.relative_to(ROOT)}")
    print(f"  TEST  {doc['test_profile']['n']:>4}  {doc['test_profile']['authors']}")
    print(f"  DEV   {doc['dev_profile']['n']:>4}  {doc['dev_profile']['authors']}")
    print(f"\n  test anchored: {doc['test_profile']['prompt_anchored']}"
          f"/{doc['test_profile']['n']}")
    print(f"  dev  anchored: {doc['dev_profile']['prompt_anchored']}"
          f"/{doc['dev_profile']['n']}")


if __name__ == "__main__":
    main()
