"""Deciding how many events a line contains, and which spans belong to each.

A line becomes more than one VEVENT for two unrelated reasons, and the reason
matters because the fix is different:

1. TWO SUBJECTS. "Monday call the dentist, Wednesday pick up the meds" is two
   different things happening. Handled by segment(), below.

2. ONE SUBJECT, INCOMPATIBLE SLOTS. "Lab Mon12pm Wed5pm" is one thing, but
   RFC 5545 makes BYDAY x BYHOUR a cross product -- a single VEVENT there
   schedules four occurrences instead of two. Handled by temporal_groups().

The product rule is that one prompt is one subject, so case 1 is mostly a guard
AGAINST splitting rather than a splitter. That is deliberate: a wrong split
corrupts a line that parsed fine, while a missed split leaves it exactly where
it already was. The measured false-split rate on gold is 0/232.
"""

from __future__ import annotations

import re

# Spans that describe the event rather than schedule it. They belong to every
# group in their segment: "Lab" is the title of both the Monday and the
# Wednesday VEVENT, and duplicating it is what the jCal output needs anyway.
SHARED = {"SUMMARY", "PERSON", "BOUND", "DURATION"}

# Slots that DEFINE an occurrence. A repeat of one of these is the signal that a
# second VEVENT has started.
DEFINING = {"RECUR", "DATE", "TSTART"}

# Slots that answer "which day". A fragment without one of these cannot stand as
# an event on its own.
DAY = {"RECUR", "DATE"}

# Candidate cut points. Deliberately narrow: these are the separators that
# actually appeared between two full events in the corpus. "at", "with" and
# bare whitespace are not here, and should not be -- they separate slots inside
# one event far more often than they separate events.
DELIM = re.compile(r",\s+|\s+and\s+|\s+then\s+|;\s*", re.I)

_MAX_DEPTH = 3


def _standalone(text: str) -> bool:
    """Could this fragment be an event by itself?

    It needs its own day slot AND its own subject. That double test is the whole
    of the segmentation logic:

      "Mon, Wed and Fri"      -- no half has a subject, so no cut. One event.
      "gym tmrw, 7pm start"   -- right half has no day, so no cut. One event.
      "Mon call X, Wed see Y" -- both halves have both, so cut. Two events.
    """
    from .preannotate import with_summary

    proposals = with_summary(text)
    return (any(p.type in DAY for p in proposals)
            and any(p.type == "SUMMARY" for p in proposals))


def segment(text: str, offset: int = 0, depth: int = 0) -> list[tuple[str, int]]:
    """Split text into one-subject fragments. Returns (fragment, start_offset).

    Recursive on both halves, the same shape as the "@" composition in
    resolve_date: cut once, then ask the same question of each piece.
    """
    if depth < _MAX_DEPTH:
        for m in DELIM.finditer(text):
            left, right = text[:m.start()], text[m.end():]
            if _standalone(left) and _standalone(right):
                return (segment(left, offset, depth + 1)
                        + segment(right, offset + m.end(), depth + 1))
    return [(text, offset)]


def temporal_groups(spans: list) -> list[list[int]]:
    """Group one segment's spans into occurrences. Returns lists of span index.

    A defining slot that repeats starts a new group, but only when another
    defining slot sits BETWEEN this one and the previous of the same type:

        Lab  Mon    12pm    Wed    5pm
             RECUR  TSTART  RECUR  TSTART
                            ^ RECUR repeats and a TSTART intervenes -> cut

    Without the intervening test, "Mon Wed Fri 9am" splits three ways. The gap
    is what distinguishes a day LIST (one event, several BYDAYs) from a day-time
    PAIRING (several events, one BYDAY each).
    """
    timed = [s for s in spans if s.type not in SHARED]
    groups: list[list[int]] = [[]]
    last: dict[str, int] = {}

    for k, s in enumerate(timed):
        if (s.type in DEFINING and s.type in last
                and any(x.type in DEFINING for x in timed[last[s.type] + 1:k])):
            groups.append([])
            last = {}
        groups[-1].append(s.i)
        last[s.type] = k

    shared = [s.i for s in spans if s.type in SHARED]
    groups = [g for g in groups if g]
    if not groups:
        return [sorted(shared)] if shared else []
    return [sorted(set(g) | set(shared)) for g in groups]


def spans_and_groups(text: str) -> tuple[list, list[list[int]]]:
    """Raw text -> (spans with global indices, event_groups).

    Segmentation runs BEFORE span proposal on purpose, not after. The
    bare-weekday demotion in preannotate counts a second day slot as evidence of
    recurrence, and that is only sound within one subject: "Lab Mon12pm Wed5pm"
    is weekly, while "Monday call X, Wednesday call Y" is two one-off dates.
    Same spans, opposite answers -- the segment boundary is what tells them
    apart, so it has to exist first.
    """
    from .ir import Span
    from .preannotate import with_summary

    all_spans: list[Span] = []
    groups: list[list[int]] = []

    for fragment, offset in segment(text):
        base = len(all_spans)
        local = [Span(i=base + n, type=p.type, start=p.start + offset,
                      end=p.end + offset, text=p.text)
                 for n, p in enumerate(with_summary(fragment))]
        all_spans.extend(local)
        groups.extend(temporal_groups(local))

    return all_spans, groups


def groups_for_spans(text: str, spans: list) -> list[list[int]]:
    """Event groups for spans that ALREADY exist -- the model's, not the rules'.

    spans_and_groups() re-runs the rule proposer on each fragment, which is
    right when the rules are the source of truth. At inference the model has
    already tagged the whole string, so re-tagging it with regexes would throw
    away the judgement that was the entire point of training something.

    Same two stages and the same tests, applied to a given span list: cut at a
    delimiter only where both sides own a day slot and a subject, then split
    each segment where a defining slot repeats with another one in between.
    """
    if not spans:
        return []

    ordered = sorted(spans, key=lambda s: s.start)

    def owns_event(subset: list) -> bool:
        types = {s.type for s in subset}
        return bool(types & DAY) and "SUMMARY" in types

    # Candidate cuts are delimiters that fall BETWEEN two spans, never inside one.
    cuts = [0]
    for m in DELIM.finditer(text):
        if any(s.start < m.end() and m.start() < s.end for s in ordered):
            continue
        left = [s for s in ordered if s.end <= m.start()]
        right = [s for s in ordered if s.start >= m.end()]
        if owns_event(left[len(cuts) - 1:] if len(cuts) > 1 else left) and owns_event(right):
            cuts.append(m.end())

    segments: list[list] = []
    for k, start in enumerate(cuts):
        stop = cuts[k + 1] if k + 1 < len(cuts) else len(text) + 1
        seg = [s for s in ordered if start <= s.start < stop]
        if seg:
            segments.append(seg)

    out: list[list[int]] = []
    for seg in segments:
        out.extend(temporal_groups(seg))
    return out
