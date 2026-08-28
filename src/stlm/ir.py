"""L1 / L2 intermediate representation. Implements documentation/IR_SPEC_v0.md.

L1 = typed character spans over raw text (what the text SAYS).
L2 = normalized symbolic event list (what it MEANS). Never holds a resolved date.
L3 = jCal, produced in convert.py from L2 + reference time + tz.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

# --- closed vocabularies -----------------------------------------------------

SPAN_TYPES = (
    "SUMMARY",
    "RECUR",
    "TSTART",
    "TEND",
    "DATE",
    "BOUND",   # end of the series: a date ("until Dec") OR a count ("x8").
               # One span type on purpose -- L1 records WHERE, the normalizer
               # decides which kind and fills rrule.until or rrule.count.
    "PERSON",
    "DURATION",  # provisional; gated on OQ-8
)

STATUSES = ("ok", "no_temporal", "unresolvable", "unrepresentable")

FLAGS = (
    "ampm_ambiguous",
    "ampm_inferred",
    "missing_end_time",
    "missing_date",
    "missing_summary",
    "temporal_lookalike",
    "multi_event",
    "relative_date",
    "negated_recurrence",
    "bounded_until",
    "bounded_count",
    "all_day",
    "duration_given",
    "recur_with_anchor",  # "every MWF starting next week" -- the OQ-6 pattern
    "time_approximate",   # time came from "morning"/"evening", not a clock
    "named_date",         # "christmas", "good friday" -- see holidays.py
    "named_date_unresolvable",  # lunar holiday; moves yearly, not guessed
    "recurrence_ambiguous",     # bare single weekday: one-off or weekly? See guide.
    "offset_from_anchor",       # "the Monday after <named date>"
    "excluded_dates",           # EXDATE emitted from the holiday table
    # A recurrence that is a tendency rather than a rule ("mostly Sundays").
    "frequency_approximate",
    # dtstart and dtend on different DAYS -- one multi-day VEVENT.
    "multi_day",
)

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

# Time-of-day words name a RANGE, not a point ("morning" is roughly 06:00-11:00).
# Kept symbolic for the same reason dates are: the collapse to a clock time is a
# policy decision, and policy must be changeable without re-annotating. See OQ-15.
# Part-of-day tokens. TIMEX2 Table 4-8 calls these MO/MI/AF/EV/NI/DT; the
# names are ours but the inventory is theirs, with two deliberate deltas.
# DAYTIME is their DT ("morning + afternoon, basically working hours").
# Their MI (mid-day) is NOT here: we read "midday" as exactly 12:00, which
# an M0 fixture asserts, and making it a window would lose that precision.
# LATER is ours -- their nearest equivalent is FUTURE_REF plus an anchor.
TOD_SYMBOLS = ("TOD:DAWN", "TOD:MORNING", "TOD:NOON", "TOD:AFTERNOON",
               "TOD:EVENING", "TOD:NIGHT", "TOD:DAYTIME", "TOD:LATER")

# The MOD attribute, verbatim from TIMEX2 Table 4-9 / TimeML 1.2. We carried
# one boolean, time_approximate, and threw away the difference between
# "early morning", "late night", "about 5" and "no more than 10 days".
MODS = ("BEFORE", "AFTER", "ON_OR_BEFORE", "ON_OR_AFTER",
        "LESS_THAN", "MORE_THAN", "EQUAL_OR_LESS", "EQUAL_OR_MORE",
        "START", "MID", "END", "APPROX")

# Symbolic date prefixes. L2 NEVER stores a resolved datetime -- see spec 1.
REL_SYMBOLS = (
    "REL:TODAY",
    "REL:TOMORROW",
    "REL:DAY_AFTER_TOMORROW",
    "REL:NEXT_OCCURRENCE",
    *[f"REL:THIS_{d}" for d in WEEKDAYS],
    *[f"REL:NEXT_{d}" for d in WEEKDAYS],
    # "until December" = the NEXT December, not December of the annotation year.
    # Keeping month bounds symbolic is what stops gold from expiring. See OQ-7.
    *[f"REL:MONTH_{m}" for m in range(1, 13)],
    # "Sept 3" = the NEXT Sept 3. Pinning a year here would make gold expire
    # exactly the way an absolute date would. Same reasoning as REL:MONTH_.
    *[f"REL:MD_{m}_{d}" for m in range(1, 13) for d in range(1, 32)],
    # "on the 15th" = the NEXT 15th of a month. Same non-expiry reasoning again.
    # This was missing: 10 dev rows carry a DATE span for an ordinal day-of-month
    # and L2 had nowhere to put it, so the date silently vanished on the way to
    # jCal -- a date span that parses and then resolves to nothing.
    *[f"REL:DOM_{d}" for d in range(1, 32)],
    # Season and weekend tokens, TIMEX2 Tables 4-4 and 4-7. Seasons are
    # northern-hemisphere academic usage ("fall semester"), which is how they
    # appear in this corpus; they are NOT a claim about Philippine weather.
    *[f"REL:SEASON_{s}" for s in ("SP", "SU", "FA", "WI")],
    "REL:WEEKEND",
)

# Computed named dates. These are patterned rather than enumerated -- Easter
# moves every year and is the anchor for the whole of Holy Week.
#   REL:EASTER-2      Good Friday
#   REL:NTH_4_3_11    4th Thursday of November
#   REL:NTH_-1_0_8    last Monday of August
_BYDAY_RE = re.compile(r"^[+-]?[1-5]?(?:MO|TU|WE|TH|FR|SA|SU)$")
_EASTER_RE = re.compile(r"^REL:EASTER[+-]\d{1,3}$")
_NTH_RE = re.compile(r"^REL:NTH_(-1|[1-5])_[0-6]_(1[0-2]|[1-9])$")


# Composed dates: an OFFSET applied to an ANCHOR, joined by "@". Resolution
# recurses -- resolve the anchor first, then step from it.
#   REL:NEXT_MO@REL:MD_11_2    "the Monday after All Souls Day"
#   REL:-7D@REL:MD_12_25       "the week before Christmas"
_OFFSET_RE = re.compile(r"^REL:(NEXT_(?:MO|TU|WE|TH|FR|SA|SU)|[+-]\d{1,3}D)@(.+)$")


def is_valid_date_symbol(sym: str) -> bool:
    """A symbolic date is one of the enumerated ones, an ABS:, or a computed form."""
    if sym.startswith("ABS:"):
        return True
    if sym in REL_SYMBOLS:
        return True
    m = _OFFSET_RE.match(sym)
    if m:
        return is_valid_date_symbol(m.group(2))
    return bool(_EASTER_RE.match(sym) or _NTH_RE.match(sym))


# --- L1 ----------------------------------------------------------------------


@dataclass
class Span:
    i: int
    type: str
    start: int
    end: int
    text: str

    def validate(self, source: str) -> list[str]:
        errs = []
        if self.type not in SPAN_TYPES:
            errs.append(f"span {self.i}: unknown type {self.type!r}")
        if not (0 <= self.start < self.end <= len(source)):
            errs.append(f"span {self.i}: bad offsets [{self.start},{self.end}) for len {len(source)}")
        elif source[self.start : self.end] != self.text:
            errs.append(
                f"span {self.i}: text {self.text!r} != source slice {source[self.start:self.end]!r}"
            )
        return errs


@dataclass
class L1:
    id: str
    text: str
    spans: list[Span] = field(default_factory=list)
    event_groups: list[list[int]] = field(default_factory=list)
    status: str = "ok"
    flags: list[str] = field(default_factory=list)
    notes: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.status not in STATUSES:
            errs.append(f"unknown status {self.status!r}")
        for f in self.flags:
            if f not in FLAGS:
                errs.append(f"unknown flag {f!r}")
        for s in self.spans:
            errs.extend(s.validate(self.text))
        # Design rule 1: spans must not overlap.
        ordered = sorted(self.spans, key=lambda s: s.start)
        for a, b in zip(ordered, ordered[1:]):
            if a.end > b.start:
                errs.append(f"spans {a.i} and {b.i} overlap (violates design rule 1)")
        idx = {s.i for s in self.spans}
        for g_no, g in enumerate(self.event_groups):
            for i in g:
                if i not in idx:
                    errs.append(f"event_group {g_no} references missing span {i}")
        if self.status == "ok" and not self.event_groups and self.spans:
            errs.append("status=ok with spans but no event_groups")
        if self.status in ("no_temporal", "unresolvable", "unrepresentable") and self.event_groups:
            errs.append(f"status={self.status} should have no event_groups")
        return errs

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "L1":
        return L1(
            id=d["id"],
            text=d["text"],
            spans=[Span(**s) for s in d.get("spans", [])],
            event_groups=[list(g) for g in d.get("event_groups", [])],
            status=d.get("status", "ok"),
            flags=list(d.get("flags", [])),
            notes=d.get("notes"),
            provenance=d.get("provenance", {}),
        )


# --- L2 ----------------------------------------------------------------------


@dataclass
class RRule:
    freq: str  # DAILY | WEEKLY | MONTHLY | YEARLY
    interval: int = 1
    byday: list[str] = field(default_factory=list)
    bymonthday: list[int] = field(default_factory=list)
    until: str | None = None  # symbolic: "ABS:YYYY-MM-DD" or REL:*
    count: int | None = None
    # "mostly Sundays", "2-3x a week", "almost weekly". TIMEX2 encodes these
    # with FREQ=LESS_THAN_EVERY or QUANT=X over an X-placeholder value; we
    # keep the rule and mark it inexact. Emitting a best-effort rule with a
    # flag beats refusing, which is the same call Policy makes everywhere.
    mod: str | None = None   # APPROX | LESS_THAN | MORE_THAN

    def validate(self) -> list[str]:
        errs = []
        if self.mod is not None and self.mod not in MODS:
            errs.append(f"unknown rrule mod {self.mod!r}")
        if self.freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            errs.append(f"bad freq {self.freq!r}")
        if self.interval < 1:
            errs.append(f"interval must be >= 1, got {self.interval}")
        for d in self.byday:
            # RFC 5545 allows an ordinal prefix: BYDAY=2SU is the 2nd Sunday of
            # the month. Distinct from INTERVAL=2 on a weekly rule, which is
            # every other Sunday. "every 2nd sunday" means the latter;
            # "every second sunday OF THE MONTH" means this.
            if not _BYDAY_RE.match(d):
                errs.append(f"bad byday {d!r}")
        if self.until and self.count:
            errs.append("RFC 5545: UNTIL and COUNT are mutually exclusive")
        if self.until is not None:
            if not is_valid_date_symbol(self.until):
                errs.append(f"until {self.until!r} is not a known symbolic date")
        if self.count is not None and self.count < 1:
            errs.append(f"count must be >= 1, got {self.count}")
        return errs


@dataclass
class DateTimeSpec:
    date: str | None = None  # symbolic only
    time: str | None = None  # "HH:MM"
    mod: str | None = None   # one of MODS; see TIMEX2 Table 4-9

    def validate(self) -> list[str]:
        errs = []
        if self.mod is not None and self.mod not in MODS:
            errs.append(f"unknown mod {self.mod!r}")
        if self.date is not None:
            if not is_valid_date_symbol(self.date):
                errs.append(f"date {self.date!r} is not a known symbolic date")
        if self.time is not None and self.time.startswith("TOD:"):
            if self.time not in TOD_SYMBOLS:
                errs.append(f"unknown time-of-day symbol {self.time!r}")
        elif self.time is not None:
            try:
                h, m = self.time.split(":")
                if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                    raise ValueError
            except Exception:
                errs.append(f"bad time {self.time!r}, want HH:MM")
        return errs


@dataclass
class L2Event:
    summary: str | None = None
    dtstart: DateTimeSpec = field(default_factory=DateTimeSpec)
    dtend: DateTimeSpec | None = None
    duration_minutes: int | None = None
    rrule: RRule | None = None
    attendees: list[str] = field(default_factory=list)
    # Symbolic exclusions -- "HOLIDAYS" rather than a date list, so the set stays
    # resolvable against a reference time and gold does not expire. L3 expands
    # these into RFC 5545 EXDATE entries over the series horizon.
    exclude: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        errs = list(self.dtstart.validate())
        for x in self.exclude:
            if x not in ("HOLIDAYS",):
                errs.append(f"unknown exclusion {x!r}")
        if self.dtend:
            errs.extend(self.dtend.validate())
        if self.rrule:
            errs.extend(self.rrule.validate())
        if self.dtend and self.duration_minutes:
            errs.append("RFC 5545: DTEND and DURATION are mutually exclusive")
        return errs


@dataclass
class L2:
    id: str
    events: list[L2Event] = field(default_factory=list)
    status: str = "ok"
    flags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errs = []
        if self.status not in STATUSES:
            errs.append(f"unknown status {self.status!r}")
        for f in self.flags:
            if f not in FLAGS:
                errs.append(f"unknown flag {f!r}")
        if self.status == "ok" and not self.events:
            errs.append("status=ok requires >=1 event")
        if self.status != "ok" and self.events:
            errs.append(f"status={self.status} requires 0 events")
        for e in self.events:
            errs.extend(e.validate())
        return errs

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "L2":
        evs = []
        for e in d.get("events", []):
            evs.append(
                L2Event(
                    summary=e.get("summary"),
                    dtstart=DateTimeSpec(**e.get("dtstart", {})),
                    dtend=DateTimeSpec(**e["dtend"]) if e.get("dtend") else None,
                    duration_minutes=e.get("duration_minutes"),
                    rrule=RRule(**e["rrule"]) if e.get("rrule") else None,
                    attendees=list(e.get("attendees", [])),
                    exclude=list(e.get("exclude", [])),
                )
            )
        return L2(
            id=d["id"],
            events=evs,
            status=d.get("status", "ok"),
            flags=list(d.get("flags", [])),
            provenance=d.get("provenance", {}),
        )


# --- jsonl helpers -----------------------------------------------------------


def write_jsonl(path, rows) -> int:
    import pathlib

    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path) -> list[dict]:
    import pathlib

    p = pathlib.Path(path)
    if not p.exists():
        return []
    out = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
