"""Parse filled batch files into corpus/human_raw.jsonl.

  uv run python scripts/ingest_batch.py                    # all batches + loose *.txt
  uv run python scripts/ingest_batch.py kylar.txt bryan.txt

Tolerant by design, because real contributors will not preserve your file format:
  - bare lines with no structure at all          (author taken from the filename)
  - the template with every '#' stripped         (boilerplate detected and dropped)
  - the template intact                          (parsed normally)

Idempotent: re-reads every source file and rewrites human_raw.jsonl from scratch.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.analyze import CONSTRUCTIONS
from stlm.ir import write_jsonl

BATCH_DIR = ROOT / "corpus" / "batches"

# Structural lines, with or without a leading '#'.
CELL_RE = re.compile(r"^\[(\d+)\]\s*(.+?)\s*<(P\d),\s*currently", re.I)
META_RE = re.compile(r"^(author|device)\s*:\s*(.+?)\s*$", re.I)
STYLEWANT_RE = re.compile(r"^(style|want)\s*:", re.I)
BATCH_RE = re.compile(r"^STLM corpus batch\s*(\d+)", re.I)

# Template preamble. These appear as CONTENT in files where '#' was stripped, so
# they must be recognised and dropped or the instructions become training data.
BOILERPLATE = {
    "how to use",
    "write one string per line under each '##' heading.",
    "blank lines are ignored. lines starting with # are ignored.",
    "write what you would actually type. typos stay. don't clean it up.",
    "can't think of one? leave it blank and move on. blank is fine.",
    "weird/unsure? write it anyway and put ?? at the end of the line.",
    "if someone else types some: add a line like",
    "and everything after it is credited to them. this is what lets us keep",
    "a test set written by someone other than you. one line, do not skip it.",
    "do not read documentation/ir_spec_v0.md before writing. knowing what the",
    "schema supports changes what you write, and then the corpus stops being",
    "evidence.",
    "end of batch",
}

# Example strings quoted in the 'want:' prompts. Contributors copy these, so any
# harvested string that contains one verbatim is prompt-anchored, not freely
# written, and must be flagged.
ANCHOR_EXAMPLES: list[str] = []
for _cid, _lbl, _rx, _why, _what, _shape in CONSTRUCTIONS:
    ANCHOR_EXAMPLES.extend(re.findall(r"'([^']+)'", _what))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


ANCHOR_NORMS = [(e, norm(e)) for e in ANCHOR_EXAMPLES if len(norm(e)) >= 6]


def anchor_hit(text: str) -> str | None:
    n = norm(text)
    best = None
    for original, an in ANCHOR_NORMS:
        if an and an in n:
            if best is None or len(an) > len(norm(best)):
                best = original
    return best


def resolve_author(declared: str, path: pathlib.Path) -> str:
    """Filename wins over a default 'me' -- contributors rarely edit the header."""
    stem = path.stem.lower()
    is_batch_file = bool(re.match(r"^batch[_\-]?\d+", stem))
    if declared and declared.lower() not in ("me", "unknown", ""):
        return declared.lower()
    if not is_batch_file:
        return stem
    return "me"


def parse(path: pathlib.Path) -> list[dict]:
    declared_author, device, batch = "", "unknown", path.stem
    cell_id = cell_label = cell_band = None
    rows: list[dict] = []
    pending_author: str | None = None
    suppress_meta = 0

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        # Strip a leading comment marker for structural matching, but remember
        # whether it was there -- files with '#' stripped need the same handling.
        body = line.lstrip("#").strip()
        low = body.lower()

        if low in BOILERPLATE:
            # The instruction block literally contains "# author: p1 / # device:
            # phone" as an EXAMPLE. With '#' stripped those parse as real
            # declarations and silently mis-attribute the whole file. Suppress
            # the next two meta lines after the instruction that introduces them.
            if low.startswith("if someone else types some"):
                suppress_meta = 2
            continue
        mb = BATCH_RE.match(body)
        if mb:
            batch = f"batch_{int(mb.group(1)):02d}"
            continue
        mm = META_RE.match(body)
        if mm:
            if suppress_meta > 0:
                suppress_meta -= 1
                continue
            key, val = mm.group(1).lower(), mm.group(2).strip()
            if key == "author":
                if not declared_author:
                    declared_author = val
                pending_author = val
            else:
                device = val
            continue
        mc = CELL_RE.match(body)
        if mc:
            cell_id, cell_label, cell_band = mc.group(1), mc.group(2), mc.group(3)
            continue
        if STYLEWANT_RE.match(body):
            continue
        if line.startswith("#"):
            continue  # any other comment

        text = line
        uncertain = text.endswith("??")
        if uncertain:
            text = text[:-2].rstrip()
        if not text:
            continue

        author = resolve_author(pending_author or declared_author, path)
        rows.append({
            "id": "h" + hashlib.sha1(f"{path.stem}|{author}|{text}".encode()).hexdigest()[:10],
            "text": text,
            "source": "human",
            "author": author,
            "device": device,
            "batch": batch,
            "file": path.name,
            "cell_id": cell_id,
            "cell_label": cell_label,
            "cell_band": cell_band,
            "uncertain": uncertain,
            "prompt_anchored": anchor_hit(text),
            "line": lineno,
        })
    return rows


def main() -> None:
    if len(sys.argv) > 1:
        targets = [pathlib.Path(a) for a in sys.argv[1:]]
    else:
        targets = (sorted(BATCH_DIR.glob("*.txt"))
                   + sorted((ROOT / "corpus" / "contrib").glob("*.txt"))
                   + sorted(ROOT.glob("*.txt")))

    all_rows: list[dict] = []
    for p in targets:
        if not p.exists():
            print(f"  MISSING {p}")
            continue
        rows = parse(p)
        if not rows:
            print(f"  {p.name}: 0 strings (template only)")
            continue
        all_rows.extend(rows)
        who = Counter(r["author"] for r in rows).most_common()
        print(f"  {p.name}: {len(rows)} strings  ({', '.join(f'{a}={n}' for a, n in who)})")

    # Exact-duplicate removal only; near-identical strings from DIFFERENT authors
    # are signal (two people independently writing the same thing), not noise.
    seen: dict[tuple, dict] = {}
    dupes = []
    for r in all_rows:
        k = (r["author"], norm(r["text"]))
        if not k[1]:
            continue
        if k in seen:
            dupes.append((seen[k], r))
        else:
            seen[k] = r
    kept = list(seen.values())

    write_jsonl(ROOT / "corpus" / "human_raw.jsonl", kept)
    print(f"\nwrote corpus/human_raw.jsonl: {len(kept)} strings "
          f"({len(dupes)} same-author duplicates dropped)")

    by_author = Counter(r["author"] for r in kept)
    print("\nby author:")
    for k, v in by_author.most_common():
        print(f"  {v:>4}  {k}")

    cross = defaultdict(set)
    for r in kept:
        cross[norm(r["text"])].add(r["author"])
    shared = {k: v for k, v in cross.items() if len(v) > 1}
    if shared:
        print(f"\n{len(shared)} strings written IDENTICALLY by >1 author "
              f"-- evidence of prompt anchoring, not coincidence.")

    anchored = [r for r in kept if r["prompt_anchored"]]
    print(f"\nprompt-anchored: {len(anchored)}/{len(kept)} "
          f"({100*len(anchored)/max(1,len(kept)):.1f}%) contain a verbatim example "
          f"string from the batch prompts")
    per_author_anchor = Counter(r["author"] for r in anchored)
    for a, n in per_author_anchor.most_common():
        tot = by_author[a]
        print(f"    {a:<12} {n:>3}/{tot:<4} ({100*n/tot:.0f}%)")
    for r in anchored[:10]:
        print(f"      {r['author']:<8} {r['text']!r}")
        print(f"               <- prompt example {r['prompt_anchored']!r}")

    unc = sum(1 for r in kept if r["uncertain"])
    if unc:
        print(f"\n{unc} flagged uncertain (??)")

    pool = [r["text"] for r in kept]
    n = len(pool) or 1
    print("\nconstruction coverage in the hand-written corpus:")
    for _cid, lbl, rx, _why, _what, _shape in CONSTRUCTIONS:
        c = sum(1 for t in pool if rx.search(t))
        print(f"  {c:>4}  ({100*c/n:>5.1f}%)  {lbl}")

    print("\nnext:  uv run python scripts/gap_report.py")


if __name__ == "__main__":
    main()
