"""Rule-based L1 span proposal.

Two jobs, and it is important to keep them separate in your head:

  1. It drafts annotations so a human corrects rather than types from scratch.
  2. Its span-detection half is the seed of the M5 rule baseline.

Because of (2) there is a bias hazard in (1): a human shown a proposal tends to
accept it, so gold pre-annotated by the baseline flatters the baseline. The
project rule is therefore: PRE-ANNOTATE DEV ONLY. The frozen test set is
annotated from scratch, so the M6 number is not measuring the baseline against
its own suggestions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import lexicon as lx

# --- surface patterns --------------------------------------------------------

_DAY_ALT = sorted(
    {s for surfaces in lx.DAY_CODES.values() for s, _w in surfaces},
    key=len, reverse=True,
)
DAY_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(d) for d in _DAY_ALT) + r")(?![A-Za-z])", re.I)

# "w mom" is "with mom", not Wednesday. A one-letter day code only counts when
# it is not immediately followed by a lowercase word -- real day codes abut a
# time, another code, or the end of the field.
AMBIGUOUS_SINGLE = {"w", "a", "s", "t", "m", "f", "r", "u"}


def _plausible_daycode(text: str, m: re.Match) -> bool:
    tok = m.group(1)
    if len(tok) > 1 or tok.lower() not in AMBIGUOUS_SINGLE:
        return True
    after = text[m.end(1):]
    return not re.match(r"\s+[A-Za-z]{2,}", after)


EVERY_RE = re.compile(
    r"\b((?:every|each|tuwing)\s+(?:other\s+|second\s+|third\s+|\d+\s+|two\s+|three\s+)?"
    r"[A-Za-z]+(?:day|days)?|daily|everyday|every\s?day|biweekly|bi-weekly|fortnightly|weekly)\b",
    re.I,
)

TIME_RE = re.compile(
    r"(?<![\w:])("
    r"\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?"          # 8:30am / 08:30
    r"|\d{1,2}\s*(?:[ap]\.?m\.?|nn|mn|noon)"      # 8am / 12nn
    r"|\d{3,4}\s*h"                               # 0800h
    r"|(?:[01]\d|2[0-3])[0-5]\d(?![\d:])"         # 0800 / 1200 military
    r"|\bnoon\b|\bmidnight\b"
    r"|\d{1,2}"                                   # bare hour, last resort
    r")(?![\w:])",
    re.I,
)

RANGE_SEP_RE = re.compile(r"^\s*(?:-|–|—|to|till|til|until|thru|through|~|--)\s*$", re.I)

RELDATE_RE = re.compile(
    r"\b((?:the\s+)?day\s+after\s+(?:tomorrow|tmrw|tmr)"
    r"|tomorrow|tmrw|tmr|tomo|2moro|tom(?![a-z])"
    r"|today|tdy|2day"
    r"|(?:this|next|nxt|last)\s+(?:coming\s+)?"
    r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*"
    r"|next\s+week|this\s+week)\b",
    re.I,
)

ABSDATE_RE = re.compile(
    r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{1,2}"
    r"(?:\s*[-–]\s*\d{1,2})?"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"|the\s+\d{1,2}(?:st|nd|rd|th))\b",
    re.I,
)

UNTIL_RE = re.compile(
    r"\b((?:until|till|til|thru|through|up\s+to|ends?)\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
    r"|(?:until|till|til)\s+[a-z]+(?:\s+week)?"
    r"|for\s+(?:the\s+next\s+)?\d+\s*(?:weeks?|sessions?|times?|months?)"
    r"|x\s?\d+"
    r"|\d+\s+sessions?)\b",
    re.I,
)

DURATION_RE = re.compile(
    r"\b(for\s+(?:an?\s+)?\d*\s*(?:hrs?|hours?|mins?|minutes?)"
    r"|\d+\s*(?:hrs?|hours?|mins?|minutes?)\s*(?:long)?"
    r"|for\s+an\s+(?:hr|hour))\b",
    re.I,
)

PERSON_RE = re.compile(
    r"\b(?:with|w/|w)\s+("
    r"(?:sir|maam|ma'am|mr|mrs|ms|prof|dr|engr|atty|coach|tita|kuya|ate|nanay|tatay)\.?\s+[A-Z][a-z]+"
    r"|(?:sir|maam|ma'am|mr|mrs|ms|prof|dr|engr|atty|coach|tita|kuya|ate|nanay|tatay)\.?\s+\w+"
    r"|the\s+\w+"
    r"|[A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)?"
    r"|\w+"
    r")",
    re.I,
)

LOCATION_RE = re.compile(
    r"(@\s*[\w\s]+?(?=\s*$|\s+(?:on|at|every|mwf|tth)\b)"
    r"|\b(?:in|at)\s+(?:the\s+)?(?:[\w]+\s+)?(?:rm|room|bldg|building|hall|lab|court|field|gym|library|annex|office)\.?\s*[\w]{0,10}?(?=\s*$|\s+\b(?:on|every|with|w/)\b)"
    r"|\b(?:rm|room)\.?\s*\d+\w*"
    r"|\b(?:zoom|google\s*meet|gmeet|online|teams)\b)",
    re.I,
)

NEGATION_RE = re.compile(
    r"\b((?:except|exc|excluding|but\s+not|minus|xcpt)\s*"
    r"(?:on\s+)?[A-Za-z\s]{0,20}?(?=\s*$|\s*\d|\s+\b(?:at|in|with|w/|room|rm|and)\b))",
    re.I,
)


@dataclass
class Proposal:
    type: str
    start: int
    end: int
    text: str
    rule: str


# Priority when two proposals overlap. Higher wins.
PRIORITY = {
    "BOUND": 90, "DURATION": 85, "DATE": 82, "RECUR": 80,
    "TEND": 70, "TSTART": 70, "PERSON": 60, "LOCATION": 55,
}


def _add(out: list[Proposal], typ: str, m: re.Match, rule: str, group: int = 0) -> None:
    s, e = m.span(group)
    txt = m.group(group)
    stripped = txt.rstrip()
    e -= len(txt) - len(stripped)
    txt = stripped
    lead = len(txt) - len(txt.lstrip())
    s += lead
    txt = txt.lstrip()
    if txt:
        out.append(Proposal(typ, s, e, txt, rule))


def propose(text: str) -> list[Proposal]:
    """Propose non-overlapping typed spans over `text`."""
    out: list[Proposal] = []

    for m in UNTIL_RE.finditer(text):
        _add(out, "BOUND", m, "until", 1)
    for m in DURATION_RE.finditer(text):
        _add(out, "DURATION", m, "duration", 1)
    for m in NEGATION_RE.finditer(text):
        _add(out, "RECUR", m, "negation", 1)
    for m in EVERY_RE.finditer(text):
        _add(out, "RECUR", m, "every", 1)
    for m in DAY_RE.finditer(text):
        if _plausible_daycode(text, m):
            _add(out, "RECUR", m, "daycode", 1)
    for m in RELDATE_RE.finditer(text):
        _add(out, "DATE", m, "reldate", 1)
    for m in ABSDATE_RE.finditer(text):
        _add(out, "DATE", m, "absdate", 1)
    for m in PERSON_RE.finditer(text):
        _add(out, "PERSON", m, "person", 1)
    for m in LOCATION_RE.finditer(text):
        _add(out, "LOCATION", m, "location", 1)

    times = [m for m in TIME_RE.finditer(text)]
    consumed = [(p.start, p.end) for p in out]

    def inside(a, b):
        return any(a >= s and b <= e for s, e in consumed)

    kept = [m for m in times if not inside(m.start(1), m.end(1))]
    # A time immediately followed by a range separator and another time is a
    # START/END pair; anything else is a lone start.
    i = 0
    while i < len(kept):
        m = kept[i]
        if i + 1 < len(kept):
            gap = text[m.end(1) : kept[i + 1].start(1)]
            if RANGE_SEP_RE.match(gap) or gap.strip() in ("-", "to", "till", "–"):
                _add(out, "TSTART", m, "range_start", 1)
                _add(out, "TEND", kept[i + 1], "range_end", 1)
                i += 2
                continue
        _add(out, "TSTART", m, "lone_time", 1)
        i += 1

    # Resolve overlaps by priority, then by length.
    out.sort(key=lambda p: (-PRIORITY.get(p.type, 0), -(p.end - p.start), p.start))
    chosen: list[Proposal] = []
    for p in out:
        if any(not (p.end <= c.start or p.start >= c.end) for c in chosen):
            continue
        chosen.append(p)
    chosen.sort(key=lambda p: p.start)
    return chosen


def with_summary(text: str) -> list[Proposal]:
    """Add SUMMARY over the largest residual gap (design rule 1: residual)."""
    spans = propose(text)
    gaps: list[tuple[int, int]] = []
    cur = 0
    for p in spans:
        if p.start > cur:
            gaps.append((cur, p.start))
        cur = max(cur, p.end)
    if cur < len(text):
        gaps.append((cur, len(text)))

    # Connectives that belong to a neighbouring span, not to the title.
    EDGE = r"(?:with|w/|w|and|at|on|in|of|the|a|an|for|to|re|,|-|@|:|\.)"
    STOP = {"with", "w", "and", "at", "on", "in", "of", "the", "a", "an",
            "for", "to", "re", "is", "my", "please", "pls"}

    def trim(s: int, e: int) -> tuple[int, int]:
        frag = text[s:e]
        m = re.match(rf"^(?:\s|{EDGE}\b)+", frag, re.I)
        if m and m.end() < len(frag):
            s += m.end()
        frag = text[s:e]
        m = re.search(rf"(?:\s|\b{EDGE})+$", frag, re.I)
        if m and m.start() > 0:
            e = s + m.start()
        return s, e

    def score(s: int, e: int) -> float:
        """Prefer the fragment that reads like a title, not like a prepositional
        tail. Length alone picks 'for students' over 'Labs open'."""
        words = re.findall(r"[A-Za-z0-9]+", text[s:e])
        if not words:
            return -1.0
        content = [w for w in words if w.lower() not in STOP]
        pts = 2.0 * len(content) + 0.2 * (e - s)
        if words[0].lower() in STOP:
            pts -= 3.0          # starts with a preposition -> probably a tail
        if s == 0:
            pts += 1.0          # leading fragments are titles more often than not
        return pts

    best = None
    best_pts = 0.0
    for s, e in gaps:
        if not text[s:e].strip():
            continue
        s2, e2 = trim(s, e)
        if e2 <= s2:
            continue
        if re.fullmatch(rf"(?:{EDGE}|\s)+", text[s2:e2], re.I):
            continue
        pts = score(s2, e2)
        if best is None or pts > best_pts:
            best, best_pts = (s2, e2), pts
    if best:
        spans.append(Proposal("SUMMARY", best[0], best[1], text[best[0]:best[1]], "residual"))
    spans.sort(key=lambda p: p.start)
    return spans
