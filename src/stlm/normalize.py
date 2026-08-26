"""L1 -> L2. The normalizer: turns typed spans into structured event semantics.

This is the deterministic half of the pipeline. The span finder (preannotate, or
later a tagger) does the fuzzy work of locating text; everything exact happens
here -- lookup tables, defaulting policy, and RRULE assembly.

Nothing in this module resolves a date to a calendar day. L2 stays symbolic;
convert.py does resolution against a reference time. See IR_SPEC_v0.md section 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lexicon as lx
from .convert import DEFAULT_POLICY, Policy
from .ir import L1, L2, DateTimeSpec, L2Event, RRule, Span

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
ALL_WEEK = list(WEEKDAYS)
WEEKDAYS_ONLY = ["MO", "TU", "WE", "TH", "FR"]


@dataclass
class Trace:
    """Why each field got its value. Cheap, and it makes error analysis possible."""

    rules: dict = field(default_factory=dict)
    flags: set = field(default_factory=set)

    def note(self, field_path: str, rule: str, source: str = "") -> None:
        self.rules[field_path] = {"rule": rule, "from": source}


# --- time --------------------------------------------------------------------

_MERIDIEM = re.compile(r"(a\.?m\.?|p\.?m\.?)\s*$", re.I)
_NOON = re.compile(r"^(12\s*nn|nn|noon|12\s*n|12\s*noon)$", re.I)
_MIDNIGHT = re.compile(r"^(12\s*mn|mn|midnight)$", re.I)
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})")
_MILITARY = re.compile(r"^([01]\d|2[0-3])([0-5]\d)\s*h?$", re.I)
_BARE = re.compile(r"^(\d{1,2})\s*h?$", re.I)


def normalize_time(text: str, policy: Policy = DEFAULT_POLICY) -> tuple[str | None, set[str]]:
    """Surface time -> 'HH:MM'. Returns (value, flags)."""
    t = text.strip().lower().replace(".", "")
    flags: set[str] = set()

    if _NOON.match(t):
        return "12:00", flags
    if _MIDNIGHT.match(t):
        return "00:00", flags

    mer = None
    m = _MERIDIEM.search(t)
    if m:
        mer = "am" if m.group(1).lower().startswith("a") else "pm"
        t = _MERIDIEM.sub("", t).strip()

    hh = mm = None
    m = _HHMM.match(t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    else:
        m = _MILITARY.match(t)
        if m and mer is None and len(re.sub(r"\D", "", t)) >= 3:
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}", flags
        m = _BARE.match(t)
        if m:
            hh, mm = int(m.group(1)), 0

    if hh is None:
        return None, flags

    if mer == "pm" and hh < 12:
        hh += 12
    elif mer == "am" and hh == 12:
        hh = 0
    elif mer is None:
        # No meridiem stated. This is ~26% of real strings, so the policy here
        # carries real weight: 7..12 read as written, 1..6 read as afternoon.
        # Mirrors chrono-node's PM-guessing refiner. See OQ-5.
        if 1 <= hh <= 6:
            hh += 12
        flags.update({"ampm_ambiguous", "ampm_inferred"})

    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None, flags
    return f"{hh:02d}:{mm:02d}", flags


def normalize_end_time(text: str, start: str | None,
                       policy: Policy = DEFAULT_POLICY) -> tuple[str | None, set[str]]:
    """End times are constrained by the start: '8-5' means 08:00-17:00, not 05:00."""
    val, flags = normalize_time(text, policy)
    if val is None or start is None:
        return val, flags
    if val <= start and "ampm_inferred" in flags:
        h, m = (int(x) for x in val.split(":"))
        bumped = f"{(h + 12) % 24:02d}:{m:02d}"
        if bumped > start:
            return bumped, flags
    if val <= start and not _MERIDIEM.search(text.strip().lower()):
        h, m = (int(x) for x in val.split(":"))
        if h + 12 <= 23 and f"{h + 12:02d}:{m:02d}" > start:
            flags.update({"ampm_ambiguous", "ampm_inferred"})
            return f"{h + 12:02d}:{m:02d}", flags
    return val, flags


# --- dates -------------------------------------------------------------------

_MONTHS = {m[:3].lower(): i for i, m in enumerate(lx.MONTHS, start=1)}
_MONTHS["sept"] = 9

_REL_SIMPLE = {
    "today": "REL:TODAY", "tdy": "REL:TODAY", "2day": "REL:TODAY",
    "tomorrow": "REL:TOMORROW", "tmrw": "REL:TOMORROW", "tmr": "REL:TOMORROW",
    "tom": "REL:TOMORROW", "tomo": "REL:TOMORROW", "2moro": "REL:TOMORROW",
}
_DAY_ABBR = {
    "mon": "MO", "monday": "MO", "tue": "TU", "tues": "TU", "tuesday": "TU",
    "wed": "WE", "wednesday": "WE", "thu": "TH", "thur": "TH", "thurs": "TH",
    "thursday": "TH", "fri": "FR", "friday": "FR", "sat": "SA", "saturday": "SA",
    "sun": "SU", "sunday": "SU",
}
_MD = re.compile(
    r"^(?:the\s+)?(?:(\w{3,9})\.?\s*(\d{1,2})|(\d{1,2})\s+(\w{3,9})|(\d{1,2})(?:st|nd|rd|th))",
    re.I,
)


def normalize_date(text: str) -> tuple[str | None, set[str]]:
    t = re.sub(r"\s+", " ", text.strip().lower())
    flags: set[str] = set()

    if re.match(r"^(the\s+)?day\s+after\s+(tomorrow|tmrw|tmr)$", t):
        return "REL:DAY_AFTER_TOMORROW", {"relative_date"}
    if t in _REL_SIMPLE:
        return _REL_SIMPLE[t], {"relative_date"}

    m = re.match(r"^(this|next|nxt|last)\s+(?:coming\s+)?(\w+)$", t)
    if m:
        qual, day = m.group(1), m.group(2)
        code = _DAY_ABBR.get(day)
        if code:
            pre = "THIS" if qual == "this" else "NEXT"
            return f"REL:{pre}_{code}", {"relative_date"}
        if day == "week":
            return "REL:NEXT_MO" if qual != "this" else "REL:TODAY", {"relative_date"}

    code = _DAY_ABBR.get(t)
    if code:
        return f"REL:THIS_{code}", {"relative_date"}

    m = _MD.match(t)
    if m:
        if m.group(1) and m.group(2):
            mon, day = _MONTHS.get(m.group(1)[:3].lower()), int(m.group(2))
        elif m.group(3) and m.group(4):
            mon, day = _MONTHS.get(m.group(4)[:3].lower()), int(m.group(3))
        else:
            return None, {"relative_date"}   # bare "the 15th" -- month unknown
        if mon and 1 <= day <= 31:
            # Symbolic, NOT ABS:. "Sept 3" means the next Sept 3, and pinning a
            # year here would make gold expire. Same reasoning as REL:MONTH_.
            return f"REL:MD_{mon}_{day}", set()
    return None, flags


# --- recurrence --------------------------------------------------------------

_INTERVAL_WORDS = {
    "other": 2, "second": 2, "two": 2, "2": 2, "biweekly": 2, "bi-weekly": 2,
    "fortnightly": 2, "alt": 2, "third": 3, "three": 3, "3": 3,
}
_NEG = re.compile(r"^(?:except|exc|excluding|but\s+not|minus|xcpt|no)\s*(?:on\s+)?(.*)$", re.I)


def _daycodes(text: str) -> list[str]:
    """Look a surface day-code up in the lexicon; fall back to letter parsing."""
    key = re.sub(r"[^a-z]", "", text.lower())
    canon = lx.DAY_CODE_LOOKUP.get(text.strip().lower()) or lx.DAY_CODE_LOOKUP.get(key)
    if canon:
        return canon.split(",")
    word = _DAY_ABBR.get(text.strip().lower())
    if word:
        return [word]
    # "MWF", "TThS" style clusters, longest-token-first so Th beats T.
    out, i = [], 0
    s = text.strip()
    while i < len(s):
        two = s[i : i + 2].lower()
        if two in ("th", "tu", "sa", "su", "mo", "we", "fr"):
            out.append({"th": "TH", "tu": "TU", "sa": "SA", "su": "SU",
                        "mo": "MO", "we": "WE", "fr": "FR"}[two])
            i += 2
            continue
        one = s[i].upper()
        mapped = {"M": "MO", "T": "TU", "W": "WE", "R": "TH", "H": "TH",
                  "F": "FR", "S": "SA", "U": "SU"}.get(one)
        if mapped:
            out.append(mapped)
        i += 1
    seen = []
    for d in out:
        if d not in seen:
            seen.append(d)
    return seen


def normalize_recur(texts: list[str]) -> tuple[RRule | None, set[str]]:
    """Merge every RECUR span into one rule.

    Multiple spans are normal and expected -- "Biweekly ... every other Tuesday"
    states the same rule twice, and the annotation guide says to tag both. They
    are unioned here, which is exactly why redundancy is the normalizer's problem
    and not the annotator's.
    """
    flags: set[str] = set()
    byday: list[str] = []
    excluded: list[str] = []
    interval = 1
    freq = None

    for raw in texts:
        t = re.sub(r"\s+", " ", raw.strip())
        low = t.lower()

        neg = _NEG.match(low)
        if neg:
            flags.add("negated_recurrence")
            for d in _daycodes(neg.group(1)):
                if d not in excluded:
                    excluded.append(d)
            continue

        for word, iv in _INTERVAL_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", low):
                interval = max(interval, iv)

        if re.search(r"\b(daily|every\s?day|everyday)\b", low):
            freq = freq or "DAILY"
            continue
        if re.search(r"\bweekdays?\b|\bm-f\b|\bmon-fri\b", low):
            for d in WEEKDAYS_ONLY:
                if d not in byday:
                    byday.append(d)
            continue
        if re.fullmatch(r"(bi-?weekly|fortnightly|weekly|every week)", low):
            freq = freq or "WEEKLY"
            continue

        stripped = re.sub(
            r"^(every|each|tuwing)\s+(other\s+|second\s+|third\s+|\d+\s+|two\s+|three\s+)?",
            "", low).strip()
        for d in _daycodes(stripped or low):
            if d not in byday:
                byday.append(d)

    if excluded:
        base = byday or (ALL_WEEK if freq == "DAILY" else WEEKDAYS_ONLY)
        byday = [d for d in base if d not in excluded]
        freq = "WEEKLY"

    if not byday and freq is None:
        return None, flags
    if byday:
        freq = "WEEKLY"
    byday.sort(key=WEEKDAYS.index)
    return RRule(freq=freq or "WEEKLY", interval=interval, byday=byday), flags


# --- bound (UNTIL date or COUNT) ---------------------------------------------

_COUNT_RE = re.compile(
    r"(?:^x\s?(\d+)$|for\s+(?:the\s+next\s+)?(\d+)\s*(?:weeks?|sessions?|times?)"
    r"|^(\d+)\s+sessions?$)", re.I)
_UNTIL_MONTH = re.compile(
    r"(?:until|till|til|thru|through|up\s+to|ends?)\s+(\w{3,9})", re.I)


def normalize_bound(text: str) -> tuple[dict, set[str]]:
    """A BOUND span is either a COUNT ('x8') or an UNTIL date ('until Dec')."""
    t = text.strip()
    m = _COUNT_RE.search(t)
    if m:
        n = next(g for g in m.groups() if g)
        return {"count": int(n)}, {"bounded_count"}
    m = _UNTIL_MONTH.search(t)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            return {"until": f"REL:MONTH_{mon}"}, {"bounded_until"}
        # "till finals", "until the sem ends" -- a real bound we cannot date.
        return {}, {"bounded_until", "unresolvable_bound"}
    return {}, set()


_DURATION_RE = re.compile(
    r"(\d+)\s*(hrs?|hours?|mins?|minutes?)|for\s+an?\s+(hr|hour|min|minute)", re.I)


def normalize_duration(text: str) -> int | None:
    m = _DURATION_RE.search(text)
    if not m:
        return None
    if m.group(1):
        n, unit = int(m.group(1)), m.group(2).lower()
        return n * 60 if unit.startswith("h") else n
    unit = (m.group(3) or "").lower()
    return 60 if unit.startswith("h") else 1


# --- main --------------------------------------------------------------------


def l1_to_l2(l1: L1, policy: Policy = DEFAULT_POLICY) -> tuple[L2, Trace]:
    """Spans -> structured events. Pure function of (l1, policy)."""
    trace = Trace()
    if l1.status != "ok":
        return L2(id=l1.id, events=[], status=l1.status, flags=list(l1.flags)), trace

    by_i = {s.i: s for s in l1.spans}
    groups = l1.event_groups or ([[s.i for s in l1.spans]] if l1.spans else [])
    events: list[L2Event] = []
    all_flags: set[str] = set(l1.flags)

    for g_no, group in enumerate(groups):
        spans = [by_i[i] for i in group if i in by_i]
        pick = lambda t: [s.text for s in spans if s.type == t]  # noqa: E731

        rrule, rflags = normalize_recur(pick("RECUR"))
        all_flags |= rflags

        tstarts = pick("TSTART")
        start_val, sflags = (None, set())
        if tstarts:
            start_val, sflags = normalize_time(tstarts[0], policy)
            all_flags |= sflags
            trace.note(f"events[{g_no}].dtstart.time", "normalize_time", tstarts[0])

        tends = pick("TEND")
        end_val = None
        if tends:
            end_val, eflags = normalize_end_time(tends[0], start_val, policy)
            all_flags |= eflags
            trace.note(f"events[{g_no}].dtend.time", "normalize_end_time", tends[0])
        elif start_val:
            all_flags.add("missing_end_time")

        date_val = None
        for d in pick("DATE"):
            date_val, dflags = normalize_date(d)
            all_flags |= dflags
            if date_val:
                trace.note(f"events[{g_no}].dtstart.date", "normalize_date", d)
                break

        for b in pick("BOUND"):
            bound, bflags = normalize_bound(b)
            all_flags |= bflags
            if rrule and bound:
                rrule.until = bound.get("until", rrule.until)
                rrule.count = bound.get("count", rrule.count)
                trace.note(f"events[{g_no}].rrule.bound", "normalize_bound", b)

        duration = None
        for d in pick("DURATION"):
            duration = normalize_duration(d)
            if duration:
                all_flags.add("duration_given")
                break

        if date_val is None:
            if rrule is not None:
                date_val = "REL:NEXT_OCCURRENCE"
                trace.note(f"events[{g_no}].dtstart.date", "default_next_occurrence")
            else:
                date_val = "REL:TODAY"
                all_flags.add("missing_date")
                trace.note(f"events[{g_no}].dtstart.date", "default_today")

        summary_parts = pick("SUMMARY")
        persons = pick("PERSON")
        summary = " ".join(summary_parts).strip() or None
        if summary and persons:
            summary = f"{summary} with {persons[0]}"
        elif summary is None and persons:
            summary = persons[0]
        if not summary_parts:
            all_flags.add("missing_summary")
        if start_val is None:
            all_flags.add("all_day")

        events.append(L2Event(
            summary=summary,
            dtstart=DateTimeSpec(date=date_val, time=start_val),
            dtend=DateTimeSpec(time=end_val) if end_val else None,
            duration_minutes=duration if not end_val else None,
            rrule=rrule,
            attendees=list(persons),
            location=(pick("LOCATION") or [None])[0],
        ))

    if len(events) > 1:
        all_flags.add("multi_event")

    known = set()
    from .ir import FLAGS as _F
    known = set(_F)
    l2 = L2(id=l1.id, events=events, status="ok",
            flags=sorted(f for f in all_flags if f in known))
    trace.flags = all_flags - known
    return l2, trace


def parse(text: str, item_id: str = "x", policy: Policy = DEFAULT_POLICY) -> tuple[L2, Trace]:
    """Full rule pipeline: raw text -> L2. This IS the M5 baseline."""
    from .preannotate import with_summary

    spans = [Span(i=n, type=p.type, start=p.start, end=p.end, text=p.text)
             for n, p in enumerate(with_summary(text))]
    l1 = L1(id=item_id, text=text, spans=spans,
            event_groups=[[s.i for s in spans]] if spans else [],
            status="ok" if spans else "no_temporal")
    return l1_to_l2(l1, policy)
