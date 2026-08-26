"""Corpus analysis: surface-form inventory, coverage/gap matrix, and the
IR_SPEC_v0 open questions measured as actual counts.

Two very different jobs, kept separate on purpose:

  analyze_labelled()   -- runs on generated data, which HAS gold labels. Answers
                          OQs about the GENERATOR, not about reality. Anything
                          reported here is circular unless cross-checked.
  analyze_raw()        -- runs on harvested/human strings, which have NO labels.
                          Surface statistics + regex probes only. Weaker signal,
                          but it is the only signal that is actually about the world.

Gap analysis compares the two and reports which axis cells reality has that the
generator lacks, and vice versa.
"""

from __future__ import annotations

import re
import statistics

from . import holidays as _hol
from collections import Counter, defaultdict

from .generate import AXES, KEY_PAIRS, cell_is_valid

# --- regex probes for unlabelled text ---------------------------------------

DAY_TOKEN = re.compile(
    r"\b(?:M(?:on(?:day)?)?|T(?:u(?:e(?:s(?:day)?)?)?)?|W(?:ed(?:nesday)?)?|"
    r"Th(?:u(?:r(?:s(?:day)?)?)?)?|R|F(?:ri(?:day)?)?|S(?:at(?:urday)?)?|"
    r"Su(?:n(?:day)?)?|U|MWF|TTh|TR|MW|MTWRF|MTWThF)\b",
    re.I,
)
TIME_TOKEN = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|nn|mn|noon|h)?\b", re.I
)
MERIDIEM = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.|nn|mn|noon)\b", re.I)
BARE_HOUR = re.compile(r"(?<![\d:])\b([1-9]|1[0-2])\b(?!\s*(?::|am|pm|a\.m|p\.m|nn|mn|noon))", re.I)
RANGE = re.compile(r"\d\s*(?:-|–|—|to|till|until|thru|~)\s*\d", re.I)
INTERVAL = re.compile(r"\b(every other|biweekly|bi-weekly|fortnightly|every \d+|every (?:two|three))\b", re.I)
UNTIL_P = re.compile(r"\b(until|till|til|thru|through|up to|ends?)\b", re.I)
COUNT_P = re.compile(r"\b(for \d+ (?:weeks?|sessions?|times?)|x\d+|\d+ sessions?)\b", re.I)
NEGATION_P = re.compile(r"\b(except|exc|but not|minus|excluding|no)\b", re.I)
DURATION_P = re.compile(r"\b(for \d+\s*(?:min(?:ute)?s?|hrs?|hours?)|\d+\s*(?:hr|hour)s?\s+long)\b", re.I)
LOCATION_P = re.compile(r"(\b(?:rm|room|bldg|building|hall|lab|gym|library|avr)\b\.?\s*\S*|@\s*\S+)", re.I)
PERSON_P = re.compile(r"\b(?:with|w/)\s+([A-Z][a-z]+|(?:sir|maam|ma'am|mr|ms|mrs|prof|dr|engr|atty)\.?\s*\w+)", re.I)
RELDATE_P = re.compile(r"\b(today|tdy|tomorrow|tmrw|tmr|tomo|2moro|day after tmrw|day after tomorrow|this \w+day|next \w+day|nxt \w+)\b", re.I)
MONTH_P = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)(?:[a-z]*)\b", re.I)
MONTHDAY_P = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{1,2}\b|\b\d{1,2}(?:st|nd|rd|th)\b", re.I)
MULTI_SEP = re.compile(r"[;,/]|\band\b|\n")


# The construction inventory. Shared by gap_report.py (measures how absent each
# one is) and make_batch.py (turns the absent ones into writing assignments).
# (id, label, probe, why it matters, what to write, abstract shape)
# 'what to write' contains quoted examples and is for the PROJECT OWNER
# reading the gap report. 'abstract shape' is what goes in contributor
# batch files -- quoted examples get copied verbatim and anchor the corpus.
CONSTRUCTIONS = [
    ("weekday-code", "Weekday day-codes (MWF, TTh, TR)", DAY_TOKEN,
     "Core of the target register.",
     "Schedules using MWF / TTh / MW / TR / MTWThF, in every casing you'd actually type.",
     "A repeating class/event on specific weekdays, written as a day-code cluster rather than full day names."),
    ("time-range", "Explicit time RANGES (8-12, 9:30 to 11)", RANGE,
     "DTSTART+DTEND in one span pair; drives TEND recall.",
     "Ranges with varied separators: '8-12', '8 - 12', '8 to 12', '8till12', '0800-1200'.",
     "An event with BOTH a start and an end time, joined by whatever separator you'd actually type."),
    ("bare-hour", "Bare hour, no am/pm ('MW 8')", BARE_HOUR,
     "Highest-frequency ambiguity class. Sets the whole defaulting policy.",
     "Times with no meridiem at all, across morning and afternoon readings.",
     "A time with NO am/pm marker at all. Pick hours where the intended meaning is obvious to you but not stated."),
    ("meridiem", "Explicit meridiem (8am, 5PM, 12NN)", MERIDIEM,
     "The unambiguous counterpart; needed so the model does not over-guess.",
     "am/pm/NN/MN forms including 12NN, 12nn, noon, 12mn.",
     "A time WITH an explicit am/pm/noon/midnight marker, including local conventions for noon."),
    ("interval", "Interval recurrence (every other, biweekly)", INTERVAL,
     "INTERVAL=2. Rare in the wild, must be deliberately oversampled.",
     "'every other Tue', 'biweekly standup', 'every 2 weeks', 'alt Fridays'.",
     "A recurrence that skips periods -- happens every second or third week rather than every week."),
    ("until", "UNTIL bound (until December, till finals)", UNTIL_P,
     "Bounded series. Requires the symbolic month policy.",
     "'MWF 8-10 until Dec', 'TTh 5pm till finals week', 'daily thru March'.",
     "A recurring event with a stated END POINT: a month, a date, or a named end-of-term milestone."),
    ("count", "COUNT bound (for 10 weeks, x8)", COUNT_P,
     "ZERO instances in the target-like harvest. Model will never learn it otherwise.",
     "'therapy every Tue for 8 weeks', 'gym MWF x12', '6 sessions starting Mon'.",
     "A recurring event that happens a FIXED NUMBER OF TIMES, with the number stated."),
    ("negation", "Negated recurrence (except Friday)", NEGATION_P,
     "Near-zero in harvest. Decides whether EXDATE is v1 scope.",
     "'daily except Sun', 'MWF except holidays', 'every day but not Friday'.",
     "A recurrence stated as an exclusion: happens on a broad schedule, minus certain days."),
    ("duration", "DURATION instead of end time (for 2 hrs)", DURATION_P,
     "Near-zero in harvest. Decides whether the DURATION slot survives.",
     "'gym at 6 for 90 mins', '2 hours from 8', 'standup 9am 15min'.",
     "A start time plus HOW LONG it lasts, instead of an end time."),
    ("relative", "Relative dates (tmrw, this Mon)", RELDATE_P,
     "Symbolic date resolution; the whole REL: vocabulary.",
     "'tmrw', 'tom', 'day after tmrw', 'this Mon', 'nxt tuesday', '2moro'.",
     "A date expressed relative to now rather than as a calendar date, in whatever abbreviation you'd type."),
    ("month-day", "Absolute date-of-month (Sept 3, the 15th)", MONTHDAY_P,
     "Drives ABS: handling and possibly BYMONTHDAY.",
     "'Sept 3 2pm defense', 'exam on the 15th', 'Oct 21-23 conference'.",
     "A specific calendar date -- month plus day number, or an ordinal day."),
    ("multi-event", "Multiple events in one string", MULTI_SEP,
     "RFC 5545 cannot pair weekday->time, so these need 2+ VEVENTs. Architecture-deciding.",
     "'Mon 12pm, Wed 5pm Lab', 'MWF 8-10 and TTh 1-3', 'lecture MW 9, lab F 2'.",
     "ONE line describing TWO OR MORE separate events at different days/times."),
    ("person", "Named attendee (with Sir Jefferson)", PERSON_P,
     "0.33% in harvest, but ALL SIX of your own examples have one. The harvest "
     "register simply cannot see this -- forum posts and parser tests do not name people.",
     "'CCC100 with Sir Jefferson', 'sync w/ boss', '1on1 with Ate Bea', 'dentist w/ Dr Cruz'.",
     "An event with a named person attending, using whatever honorific/nickname you'd actually use."),
    ("holiday", "Named date (christmas, holy week, undas)", _hol.HOLIDAY_RE,
     "An interpreter exists but its real rate is unmeasured -- no contributor was "
     "ever prompted for a holiday, so 0%% in the corpus means nothing.",
     "'xmas dinner 7pm', 'good friday mass', 'undas cemetery visit', 'holy week retreat'.",
     "An event pinned to a named day rather than a date -- a holiday, a feast day, "
     "or a season everyone knows by name."),
    ("location", "Location (Rm 201, @ gym, online)", LOCATION_P,
     "3.6% in harvest -- borderline against the 2% delete-the-slot threshold.",
     "'MWF 8-10 Rm 201', 'lab @ CS Bldg', 'standup on Zoom', 'PE at Court 2'.",
     "An event with a place attached -- a room, a building, or an online platform."),
]

TARGET_LIKE_REGISTERS = {
    "informal", "real-user-terse", "institutional", "event-title+datetime",
    "terse-time-range", "terse-date-dialect", "terse-time", "terse-datetime",
}


def pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p / 100))]


def _lenstats(texts: list[str]) -> dict:
    ch = [len(t) for t in texts]
    by = [len(t.encode("utf-8")) for t in texts]
    nonascii = Counter()
    for t in texts:
        for c in t:
            if ord(c) > 127:
                nonascii[c] += 1
    return {
        "n": len(texts),
        "chars": {"p50": pct(ch, 50), "p90": pct(ch, 90), "p99": pct(ch, 99), "max": max(ch, default=0),
                  "mean": round(statistics.mean(ch), 1) if ch else 0},
        "bytes": {"p50": pct(by, 50), "p90": pct(by, 90), "p99": pct(by, 99), "max": max(by, default=0),
                  "mean": round(statistics.mean(by), 1) if by else 0},
        "byte_char_inflation": round(sum(by) / sum(ch), 4) if ch and sum(ch) else 1.0,
        "nonascii_chars": {f"U+{ord(c):04X} {c!r}": n for c, n in nonascii.most_common(12)},
        "pct_strings_with_nonascii": round(
            100 * sum(1 for t in texts if any(ord(c) > 127 for c in t)) / len(texts), 2
        ) if texts else 0.0,
    }


def _casing(texts: list[str]) -> dict:
    c = Counter()
    for t in texts:
        letters = [ch for ch in t if ch.isalpha()]
        if not letters:
            c["none"] += 1
        elif all(ch.islower() for ch in letters):
            c["all_lower"] += 1
        elif all(ch.isupper() for ch in letters):
            c["all_upper"] += 1
        elif t[:1].isupper():
            c["title_ish"] += 1
        else:
            c["mixed"] += 1
    n = sum(c.values()) or 1
    return {k: round(100 * v / n, 2) for k, v in c.most_common()}


def analyze_raw(texts: list[str], label: str) -> dict:
    """Regex-probe statistics over UNLABELLED text. Weak but honest."""
    n = len(texts) or 1
    def rate(rx):
        return round(100 * sum(1 for t in texts if rx.search(t)) / n, 2)

    ambiguous = 0
    for t in texts:
        if BARE_HOUR.search(t) and not MERIDIEM.search(t):
            ambiguous += 1

    return {
        "label": label,
        "length": _lenstats(texts),
        "casing_pct": _casing(texts),
        "probe_rates_pct": {
            "has_daycode": rate(DAY_TOKEN),
            "has_time": rate(TIME_TOKEN),
            "has_explicit_meridiem": rate(MERIDIEM),
            "has_time_range": rate(RANGE),
            "has_interval_phrase": rate(INTERVAL),
            "has_until_bound": rate(UNTIL_P),
            "has_count_bound": rate(COUNT_P),
            "has_negation": rate(NEGATION_P),
            "has_duration": rate(DURATION_P),
            "has_location_marker": rate(LOCATION_P),
            "has_person_marker": rate(PERSON_P),
            "has_relative_date": rate(RELDATE_P),
            "has_month_name": rate(MONTH_P),
            "has_month_day": rate(MONTHDAY_P),
            "has_multi_event_separator": rate(MULTI_SEP),
            "ampm_ambiguous_bare_hour": round(100 * ambiguous / n, 2),
        },
    }


def analyze_labelled(rows: list[dict], label: str) -> dict:
    """Full analysis over rows carrying gold l1/l2/cell."""
    texts = [r["l1"]["text"] for r in rows]
    n = len(rows) or 1

    flag_counts = Counter()
    status_counts = Counter()
    span_counts = Counter()
    events_per_row = Counter()
    strings_with_span = defaultdict(int)
    for r in rows:
        status_counts[r["l1"]["status"]] += 1
        for f in r["l1"].get("flags", []):
            flag_counts[f] += 1
        seen = set()
        for s in r["l1"].get("spans", []):
            span_counts[s["type"]] += 1
            seen.add(s["type"])
        for t in seen:
            strings_with_span[t] += 1
        events_per_row[len(r["l2"].get("events", []))] += 1

    return {
        "label": label,
        "n": len(rows),
        "length": _lenstats(texts),
        "casing_pct": _casing(texts),
        "status_pct": {k: round(100 * v / n, 2) for k, v in status_counts.most_common()},
        "flag_pct": {k: round(100 * v / n, 2) for k, v in flag_counts.most_common()},
        "span_type_pct_of_strings": {
            k: round(100 * v / n, 2) for k, v in sorted(strings_with_span.items(), key=lambda x: -x[1])
        },
        "events_per_string_pct": {
            str(k): round(100 * v / n, 2) for k, v in sorted(events_per_row.items())
        },
        "multi_event_pct": round(
            100 * sum(v for k, v in events_per_row.items() if k > 1) / n, 2
        ),
    }


# --- coverage / gap ----------------------------------------------------------

THIN = 0.005  # below 0.5% of the corpus counts as thin coverage


def coverage(rows: list[dict], total_hint: int | None = None) -> dict:
    """Marginal and key-pair coverage over the axis cells."""
    n = total_hint or len(rows) or 1
    marg: dict[str, Counter] = {a: Counter() for a in AXES}
    pairs: dict[str, Counter] = {f"{a}|{b}": Counter() for a, b in KEY_PAIRS}
    for r in rows:
        cell = r.get("cell") or {}
        for a in AXES:
            v = cell.get(a)
            if v and v != "n/a":
                marg[a][v] += 1
        for a, b in KEY_PAIRS:
            va, vb = cell.get(a), cell.get(b)
            if va and vb and va != "n/a" and vb != "n/a":
                pairs[f"{a}|{b}"][f"{va} x {vb}"] += 1

    gaps = []
    for a, values in AXES.items():
        for v in values:
            c = marg[a][v]
            if c / n < THIN:
                gaps.append({"kind": "marginal", "axis": a, "cell": v, "count": c,
                             "pct": round(100 * c / n, 3)})
    for a, b in KEY_PAIRS:
        for va in AXES[a]:
            for vb in AXES[b]:
                probe = {k: (va if k == a else vb if k == b else AXES[k][0]) for k in AXES}
                if not cell_is_valid(probe):
                    continue
                key = f"{va} x {vb}"
                c = pairs[f"{a}|{b}"][key]
                if c / n < THIN:
                    gaps.append({"kind": "pair", "axis": f"{a}|{b}", "cell": key,
                                 "count": c, "pct": round(100 * c / n, 3)})
    gaps.sort(key=lambda g: (g["count"], g["kind"]))
    return {
        "n": len(rows),
        "marginals": {a: dict(marg[a].most_common()) for a in AXES},
        "key_pairs": {k: dict(v.most_common()) for k, v in pairs.items()},
        "gaps": gaps,
        "n_empty": sum(1 for g in gaps if g["count"] == 0),
        "n_thin": sum(1 for g in gaps if 0 < g["count"]),
    }


def gap_vs_reality(syn: dict, raw: dict) -> list[dict]:
    """Where the generator's rate diverges most from the harvested-text rate.

    Both sides are imperfect: the synthetic side is exact but circular, the raw
    side is real but measured by regex. Large divergences are still the most
    actionable signal available before the human corpus exists.
    """
    pairs = [
        ("has_relative_date", "relative_date"),
        ("has_until_bound", "bounded_until"),
        ("has_count_bound", "bounded_count"),
        ("has_negation", "negated_recurrence"),
        ("has_duration", "duration_given"),
        ("has_multi_event_separator", "multi_event"),
        ("ampm_ambiguous_bare_hour", "ampm_ambiguous"),
    ]
    out = []
    for raw_key, syn_flag in pairs:
        rv = raw["probe_rates_pct"].get(raw_key, 0.0)
        sv = syn["flag_pct"].get(syn_flag, 0.0)
        out.append({
            "feature": syn_flag,
            "harvested_pct": rv,
            "synthetic_pct": sv,
            "delta_pp": round(sv - rv, 2),
            "verdict": ("synthetic OVER-represents" if sv - rv > 8
                        else "synthetic UNDER-represents" if rv - sv > 8
                        else "roughly aligned"),
        })
    out.sort(key=lambda d: -abs(d["delta_pp"]))
    return out
