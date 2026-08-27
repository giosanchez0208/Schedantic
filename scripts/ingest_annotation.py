"""Parse edited annotation files into corpus/gold_l1.jsonl.

Offsets are LOCATED, never typed: each span's value is matched back against the
source line. Every failure is reported loudly rather than silently dropped --
a silently-lost span is label noise, which is exactly what gold must not have.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.ir import L1, FLAGS, SPAN_TYPES, Span, read_jsonl, write_jsonl

ANN_DIR = ROOT / "corpus" / "annotate"

HEAD_RE = re.compile(r"^===\s*(\S+)\s*\[([^\]]+)\]\s*===")
SPAN_RE = re.compile(r"^([A-Z_]+)\s*\|\s*(.*?)\s*(?:#(\d+))?\s*$")
KV_RE = re.compile(r"^(events|status|flags|note)\s*:\s*(.*)$", re.I)

_CONNECT = re.compile(r"^[\s,\-@:]*(?:with|w/|w|and|at|in|on|of|the|a|an)?[\s,\-@:]*$", re.I)

problems: list[str] = []


def locate(text: str, value: str, occurrence: int) -> tuple[int, int] | None:
    """Find the occurrence-th instance of `value` in `text`."""
    if not value:
        return None
    idx, found = -1, 0
    while True:
        idx = text.find(value, idx + 1)
        if idx < 0:
            return None
        found += 1
        if found == occurrence:
            return idx, idx + len(value)


def parse_file(path: pathlib.Path) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None

    def flush():
        if cur is None:
            return
        text = cur["text"]
        spans: list[Span] = []
        for i, (typ, val, occ) in enumerate(cur["raw_spans"]):
            if typ not in SPAN_TYPES:
                problems.append(f"{cur['id']}: unknown span type {typ!r}")
                continue
            if not val.strip():
                continue
            loc = locate(text, val, occ)
            if loc is None:
                problems.append(
                    f"{cur['id']}: {typ} value {val!r} not found in line "
                    f"{text!r} -- check for a typo or a changed character")
                continue
            spans.append(Span(i=len(spans), type=typ, start=loc[0], end=loc[1], text=val))
        spans.sort(key=lambda s: s.start)
        # One SUMMARY span per contiguous non-temporal region. Annotators
        # naturally tag "mass" and "at the chapel" separately; with LOCATION
        # gone they are one title fragment, and the parser emits them as one.
        merged: list[Span] = []
        for s in spans:
            if (merged and merged[-1].type == "SUMMARY" and s.type == "SUMMARY"
                    and _CONNECT.match(text[merged[-1].end:s.start])):
                prev = merged[-1]
                merged[-1] = Span(i=0, type="SUMMARY", start=prev.start,
                                  end=s.end, text=text[prev.start:s.end])
            else:
                merged.append(s)
        spans = merged
        for n, s in enumerate(spans):
            s.i = n

        ev = cur["events"].strip().lower()
        if ev in ("", "all", "1"):
            groups = [[s.i for s in spans]] if spans else []
        else:
            groups = []
            for part in cur["events"].split(";"):
                want = part.split()
                idxs = []
                for tok in want:
                    m = re.match(r"^([A-Z_]+)(?:#(\d+))?$", tok.strip())
                    if not m:
                        continue
                    typ, nth = m.group(1), int(m.group(2) or 1)
                    matching = [s for s in spans if s.type == typ]
                    if len(matching) >= nth:
                        idxs.append(matching[nth - 1].i)
                    else:
                        problems.append(
                            f"{cur['id']}: events references {tok} but only "
                            f"{len(matching)} {typ} span(s) exist")
                if idxs:
                    groups.append(sorted(set(idxs)))

        status = cur["status"].strip() or "ok"
        flags = [f.strip() for f in cur["flags"].replace(",", " ").split() if f.strip()]
        for f in flags:
            if f not in FLAGS:
                problems.append(f"{cur['id']}: unknown flag {f!r}")
        if status != "ok":
            groups = []

        l1 = L1(id=cur["id"], text=text, spans=spans, event_groups=groups,
                status=status, flags=flags, notes=cur["note"].strip() or None)
        errs = l1.validate()
        if errs:
            for e in errs:
                problems.append(f"{cur['id']}: {e}")
        row = l1.to_json()
        row["author"] = cur["author"]
        row["file"] = path.name
        out.append(row)

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m = HEAD_RE.match(line)
        if m:
            flush()
            cur = {"id": m.group(1), "author": m.group(2), "text": "",
                   "raw_spans": [], "events": "all", "status": "ok",
                   "flags": "", "note": ""}
            continue
        if cur is None or not line.strip():
            continue
        if line.startswith(">"):
            cur["text"] = line[1:].strip()
            continue
        if line.lstrip().startswith("#"):
            continue
        mk = KV_RE.match(line)
        if mk:
            cur[mk.group(1).lower()] = mk.group(2)
            continue
        ms = SPAN_RE.match(line)
        if ms:
            cur["raw_spans"].append(
                (ms.group(1), ms.group(2), int(ms.group(3) or 1)))
    flush()
    return out


def main() -> None:
    targets = [pathlib.Path(a) for a in sys.argv[1:]] or sorted(ANN_DIR.glob("*.txt"))
    if not targets:
        print("no annotation files. run scripts/make_annotation.py first.")
        return

    rows: list[dict] = []
    for p in targets:
        if not p.exists():
            print(f"  MISSING {p}")
            continue
        got = parse_file(p)
        rows.extend(got)
        print(f"  {p.name}: {len(got)} annotated")

    # Only keep items that actually got annotated (a blank test template would
    # otherwise land in gold as an empty annotation).
    real = [r for r in rows if r["spans"] or r["status"] != "ok"]
    skipped = len(rows) - len(real)

    # Overlapping batch files silently double-count into gold, which inflates
    # every metric computed from it. Keep the last annotation of each id and say
    # loudly which files collided.
    by_id: dict[str, dict] = {}
    collisions: dict[str, list[str]] = {}
    for r in real:
        if r["id"] in by_id and by_id[r["id"]]["file"] != r["file"]:
            collisions.setdefault(r["id"], [by_id[r["id"]]["file"]]).append(r["file"])
        by_id[r["id"]] = r
    if collisions:
        files = sorted({f for v in collisions.values() for f in v})
        print(f"\n!! {len(collisions)} id(s) annotated in more than one file: {files}")
        print("   Kept the last occurrence. Delete the superseded file to silence this.")
    real = list(by_id.values())

    write_jsonl(ROOT / "corpus" / "gold_l1.jsonl", real)
    print(f"\nwrote corpus/gold_l1.jsonl: {len(real)} items"
          + (f"  ({skipped} left blank, skipped)" if skipped else ""))

    if problems:
        print(f"\n!! {len(problems)} PROBLEM(S) -- fix these, gold must be clean:")
        for p in problems[:25]:
            print(f"   {p}")
        if len(problems) > 25:
            print(f"   ... and {len(problems) - 25} more")
    else:
        print("\nno problems: every span located, all items validate.")

    if real:
        print(f"\nstatus:  {dict(Counter(r['status'] for r in real))}")
        st = Counter(s["type"] for r in real for s in r["spans"])
        print(f"spans:   {dict(st.most_common())}")
        multi = sum(1 for r in real if len(r["event_groups"]) > 1)
        print(f"multi-event: {multi}/{len(real)}")
        unrep = [r for r in real if r["status"] == "unrepresentable"]
        if unrep:
            print(f"\nUNREPRESENTABLE ({len(unrep)}) -- these drive IR v1:")
            for r in unrep:
                print(f"   {r['text']!r}")
                if r.get("notes"):
                    print(f"      note: {r['notes']}")


if __name__ == "__main__":
    main()
