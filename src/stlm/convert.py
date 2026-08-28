"""L2 -> L3. Symbolic date resolution and jCal (RFC 7265) emission.

This is the deterministic layer. All date arithmetic and RRULE assembly happen
here, in testable code, never in the model.

Resolution policy is explicit and centralised in resolve_date() so it can be
changed without re-annotating anything -- that is the whole point of keeping L2
symbolic.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from dateutil import rrule as du

from . import holidays as hol
from .ir import _OFFSET_RE, L2, L2Event, RRule

WEEKDAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
DU_WEEKDAY = {
    "MO": du.MO, "TU": du.TU, "WE": du.WE, "TH": du.TH,
    "FR": du.FR, "SA": du.SA, "SU": du.SU,
}
DU_FREQ = {"DAILY": du.DAILY, "WEEKLY": du.WEEKLY, "MONTHLY": du.MONTHLY, "YEARLY": du.YEARLY}


class ResolutionError(ValueError):
    pass


@dataclass
class Policy:
    """Every defaulting decision in one place. Change here, not in the gold data."""

    # "this Monday" issued ON a Monday: does it mean today or next week?
    this_weekday_includes_today: bool = True
    # "next Monday" means the NEXT INSTANCE of Monday, not the Monday of next
    # week. Rule of thumb: a schedule is written BEFORE the day it refers to, so
    # the nearest forward match is what the writer meant. Resolved OQ-13.
    # Set to 7 to get the "Monday of next week" reading instead.
    next_weekday_min_offset: int = 1
    # A recurrence with no explicit anchor starts at the first matching date >= ref.
    default_to_future: bool = True
    # Bare month name ("until December") resolves to the 1st of that month, in the
    # next occurrence of that month at or after the reference date. See OQ-7.
    month_only_day: int = 1
    # Event with a date but no time.
    all_day_time: dt.time = dt.time(0, 0)
    # Event with a start but no end.
    default_duration_minutes: int = 60
    # "later" is the one time-of-day word that is relative to WHEN IT WAS SAID
    # rather than to a fixed hour: "gym later" at 9am and at 8pm mean different
    # clock times. So it gets an offset from the reference instead of a slot in
    # tod_times, rounded to the next half hour because nobody means 12:47.
    later_offset_minutes: int = 180
    later_round_to_minutes: int = 30
    # If the offset would spill past this, "later" was said too late in the day
    # to mean today; it lands here instead of rolling into tomorrow silently.
    later_latest: dt.time = dt.time(21, 0)
    # Where each time-of-day word lands. These are the midpoint-ish hours people
    # actually mean, not the middle of the literal range. Change here, not in gold.
    tod_times: dict = field(default_factory=lambda: {
        "TOD:DAWN": dt.time(6, 0), "TOD:MORNING": dt.time(8, 0),
        "TOD:NOON": dt.time(12, 0), "TOD:AFTERNOON": dt.time(14, 0),
        "TOD:EVENING": dt.time(18, 0), "TOD:NIGHT": dt.time(20, 0),
        "TOD:LATER": dt.time(15, 0),
    })


DEFAULT_POLICY = Policy()


def resolve_date(symbol: str, ref: dt.datetime, rule: RRule | None = None,
                 policy: Policy = DEFAULT_POLICY) -> dt.date:
    """Resolve an L2 symbolic date against a reference datetime."""
    if symbol is None:
        raise ResolutionError("cannot resolve None")
    if symbol.startswith("ABS:"):
        return dt.date.fromisoformat(symbol[4:])
    if symbol == "REL:TODAY":
        return ref.date()
    if symbol == "REL:TOMORROW":
        return ref.date() + dt.timedelta(days=1)
    if symbol == "REL:DAY_AFTER_TOMORROW":
        return ref.date() + dt.timedelta(days=2)
    if symbol.startswith("REL:DOM_"):
        # The next occurrence of that day-of-month, this month or next. Months
        # that are too short are skipped rather than clamped: "the 31st" in
        # February means the 31st of the next month that has one, not Feb 28.
        day = int(symbol[len("REL:DOM_"):])
        y, mo = ref.year, ref.month
        for _ in range(14):
            try:
                cand = dt.date(y, mo, day)
            except ValueError:
                cand = None
            if cand is not None and cand >= ref.date():
                return cand
            mo += 1
            if mo > 12:
                mo, y = 1, y + 1
        raise ResolutionError(f"no month with day {day}")
    m = _OFFSET_RE.match(symbol)
    if m:
        # Composed date: resolve the ANCHOR first, then step from it. This is
        # what makes "the Monday after All Souls Day" work -- the parser becomes
        # its own sub-parser rather than needing a symbol per holiday-offset pair.
        op, anchor_sym = m.group(1), m.group(2)
        anchor = resolve_date(anchor_sym, ref, rule, policy)
        if op.startswith("NEXT_"):
            wd = WEEKDAY_INDEX[op[len("NEXT_"):]]
            # Strictly after: "the Monday after" a Monday is the following week.
            return anchor + dt.timedelta(days=(wd - anchor.weekday()) % 7 or 7)
        return anchor + dt.timedelta(days=int(op[:-1]))
    if symbol.startswith("REL:EASTER"):
        off = int(symbol[len("REL:EASTER"):])
        d = hol.easter(ref.year) + dt.timedelta(days=off)
        if d < ref.date():
            d = hol.easter(ref.year + 1) + dt.timedelta(days=off)
        return d
    if symbol.startswith("REL:NTH_"):
        n, wd, month = (int(x) for x in symbol[len("REL:NTH_"):].split("_"))
        d = hol.nth_weekday(ref.year, month, wd, n)
        if d < ref.date():
            d = hol.nth_weekday(ref.year + 1, month, wd, n)
        return d
    if symbol.startswith("REL:MD_"):
        m, d = (int(x) for x in symbol[len("REL:MD_"):].split("_"))
        year = ref.year if (m, d) >= (ref.month, ref.day) else ref.year + 1
        while True:
            try:
                return dt.date(year, m, d)
            except ValueError:
                # e.g. Feb 29 in a non-leap year -- roll to the next year that has it
                year += 1
                if year > ref.year + 8:
                    raise ResolutionError(f"no valid date for {symbol!r}")
    if symbol.startswith("REL:MONTH_"):
        # "until December" means the NEXT December, not December of whatever year
        # the annotation happened to be written in. Keeping it symbolic is what
        # stops gold from expiring. See OQ-7.
        m = int(symbol[len("REL:MONTH_") :])
        year = ref.year if (m, policy.month_only_day) >= (ref.month, ref.day) else ref.year + 1
        return dt.date(year, m, policy.month_only_day)
    if symbol == "REL:NEXT_OCCURRENCE":
        if rule is None:
            return ref.date()
        midnight = dt.datetime.combine(ref.date(), dt.time(0, 0))
        occ = build_rrule(rule, midnight, policy, ref)
        # Compare against the reference DATE, not its time of day: NEXT_OCCURRENCE
        # picks which day the series starts on, and the clock time comes from
        # dtstart.time independently. Comparing against ref itself would skip
        # today whenever the reference time is later than midnight.
        first = occ.after(midnight - dt.timedelta(seconds=1), inc=True)
        if first is None:
            raise ResolutionError(f"rule {rule} has no occurrence at or after {ref.date()}")
        return first.date()
    if symbol.startswith("REL:THIS_"):
        wd = WEEKDAY_INDEX[symbol[len("REL:THIS_") :]]
        delta = (wd - ref.weekday()) % 7
        if delta == 0 and not policy.this_weekday_includes_today:
            delta = 7
        return ref.date() + dt.timedelta(days=delta)
    if symbol.startswith("REL:NEXT_"):
        wd = WEEKDAY_INDEX[symbol[len("REL:NEXT_") :]]
        delta = (wd - ref.weekday()) % 7
        if delta < policy.next_weekday_min_offset:
            delta += 7 * ((policy.next_weekday_min_offset - delta + 6) // 7)
        return ref.date() + dt.timedelta(days=delta)
    raise ResolutionError(f"unknown symbol {symbol!r}")


def _du_day(code: str):
    """"2SU" -> dateutil SU(2); "SU" -> SU. Ordinal prefix per RFC 5545."""
    n = code[:-2]
    wd = DU_WEEKDAY[code[-2:]]
    return wd(int(n)) if n else wd


def build_rrule(rule: RRule, dtstart: dt.datetime, policy: Policy = DEFAULT_POLICY,
                ref: dt.datetime | None = None) -> du.rrule:
    kw: dict = {
        "freq": DU_FREQ[rule.freq],
        "dtstart": dtstart,
        "interval": rule.interval,
    }
    if rule.byday:
        kw["byweekday"] = [_du_day(d) for d in rule.byday]
    if rule.bymonthday:
        kw["bymonthday"] = rule.bymonthday
    if rule.count:
        kw["count"] = rule.count
    elif rule.until:
        u = None
        if rule.until.startswith("ABS:"):
            u = dt.date.fromisoformat(rule.until[4:])
        elif rule.until.startswith("REL:"):
            u = resolve_date(rule.until, ref or dtstart, None, policy)
        if u:
            until = dt.datetime.combine(u, dt.time(23, 59, 59))
            # A bound earlier than the start makes the rule empty, which then
            # explodes downstream. Clamp to at least one occurrence and let the
            # caller see it rather than raising from deep inside expansion.
            kw["until"] = max(until, dtstart)
    return du.rrule(**kw)


def _resolve_later(d: dt.date, ref: dt.datetime, policy: Policy) -> dt.datetime:
    """"later" -> a while after the reference time, on the resolved day.

    Guessing here rather than refusing is the same call the rest of Policy makes:
    a bare hour of 1-6 becomes PM, a date with no time becomes midnight, a start
    with no end gets an hour. "Later" is no less defensible than any of those --
    it says "not now, still today" -- and it carries time_approximate so the UI
    can show it as a guess.
    """
    base = ref + dt.timedelta(minutes=policy.later_offset_minutes)
    step = policy.later_round_to_minutes
    if step:
        over = (base.minute % step)
        if over or base.second:
            base = (base.replace(second=0, microsecond=0)
                    + dt.timedelta(minutes=step - over))
    if d != ref.date():
        # "later" pinned to another day has no now to be later than, so it falls
        # back to the same fixed treatment the other time-of-day words get.
        return dt.datetime.combine(d, policy.tod_times.get("TOD:LATER", dt.time(15, 0)))
    if base.time() > policy.later_latest or base.date() != d:
        return dt.datetime.combine(d, policy.later_latest)
    return dt.datetime.combine(d, base.time().replace(second=0, microsecond=0))


def resolve_event(ev: L2Event, ref: dt.datetime, policy: Policy = DEFAULT_POLICY) -> dict:
    """Resolve one L2 event to concrete datetimes."""
    d = resolve_date(ev.dtstart.date, ref, ev.rrule, policy)
    if ev.dtstart.time == "TOD:LATER":
        start = _resolve_later(d, ref, policy)
        all_day = False
    elif ev.dtstart.time and ev.dtstart.time.startswith("TOD:"):
        start = dt.datetime.combine(d, policy.tod_times[ev.dtstart.time])
        all_day = False
    elif ev.dtstart.time:
        h, m = (int(x) for x in ev.dtstart.time.split(":"))
        start = dt.datetime.combine(d, dt.time(h, m))
        all_day = False
    else:
        start = dt.datetime.combine(d, policy.all_day_time)
        all_day = True

    end = None
    if ev.dtend and ev.dtend.time and ev.dtend.time.startswith("TOD:"):
        end = dt.datetime.combine(d, policy.tod_times[ev.dtend.time])
        if end <= start:
            end += dt.timedelta(days=1)
    elif ev.dtend and ev.dtend.time:
        h, m = (int(x) for x in ev.dtend.time.split(":"))
        end = dt.datetime.combine(d, dt.time(h, m))
        if end <= start:
            end += dt.timedelta(days=1)
    elif ev.duration_minutes:
        end = start + dt.timedelta(minutes=ev.duration_minutes)
    elif not all_day:
        end = start + dt.timedelta(minutes=policy.default_duration_minutes)

    return {"start": start, "end": end, "all_day": all_day}


def rrule_to_jcal(rule: RRule, ref: dt.datetime | None = None,
                  policy: Policy = DEFAULT_POLICY) -> dict:
    """RFC 7265 3.6.10: recur value is a JSON object with lowercase keys."""
    out: dict = {"freq": rule.freq}
    if rule.interval != 1:
        out["interval"] = rule.interval
    if rule.byday:
        out["byday"] = list(rule.byday)
    if rule.bymonthday:
        out["bymonthday"] = list(rule.bymonthday)
    if rule.count:
        out["count"] = rule.count
    if rule.until:
        u = None
        if rule.until.startswith("ABS:"):
            u = dt.date.fromisoformat(rule.until[4:])
        elif rule.until.startswith("REL:") and ref is not None:
            u = resolve_date(rule.until, ref, None, policy)
        if u:
            # RFC 5545: UNTIL must be UTC when DTSTART is tz-aware.
            out["until"] = dt.datetime.combine(u, dt.time(0, 0)).strftime("%Y%m%dT%H%M%SZ")
    return out


def l2_to_jcal(l2: L2, ref: dt.datetime, tzid: str | None = None,
               policy: Policy = DEFAULT_POLICY, prodid: str = "-//Gio//STLM//EN",
               exdate_horizon_days: int = 365) -> list:
    """Emit an RFC 7265 jCal vcalendar. Deterministic given (l2, ref, tzid)."""
    props = [["version", {}, "text", "2.0"], ["prodid", {}, "text", prodid]]
    comps = []
    for n, ev in enumerate(l2.events):
        r = resolve_event(ev, ref, policy)
        params = {"tzid": tzid} if tzid and not r["all_day"] else {}
        vtype = "date" if r["all_day"] else "date-time"
        fmt = (lambda x: x.date().isoformat()) if r["all_day"] else (lambda x: x.isoformat())
        eprops = [
            ["uid", {}, "text", f"{l2.id}-{n}@stlm"],
            ["dtstamp", {}, "date-time", ref.replace(microsecond=0).isoformat() + "Z"],
            ["dtstart", dict(params), vtype, fmt(r["start"])],
        ]
        if r["end"]:
            # RFC 5545: DTEND is exclusive. For all-day events that means the day
            # AFTER the last day, which is the classic off-by-one interop trap.
            end = r["end"] + dt.timedelta(days=1) if r["all_day"] else r["end"]
            eprops.append(["dtend", dict(params), vtype, fmt(end)])
        if ev.summary:
            eprops.append(["summary", {}, "text", ev.summary])
        # OQ-2 resolved: a named person is part of the answer to "what goes on
        # the calendar", so they live in SUMMARY. No ATTENDEE property -- a
        # fabricated mailto for "Ate Bea" is worse than nothing.
        if ev.rrule:
            eprops.append(["rrule", {}, "recur", rrule_to_jcal(ev.rrule, ref, policy)])
        if ev.exclude and ev.rrule:
            # "MTWThF except holidays" becomes a real EXDATE list, expanded from
            # the offline holiday table over the series horizon. Approximate by
            # construction: the table has no lunar holidays, and the writer may
            # not have meant national holidays. Flagged, not presented as exact.
            occ = occurrences(ev, ref, exdate_horizon_days, policy)
            if occ:
                hol_days = set(hol.dates_between(occ[0].date(), occ[-1].date()))
                skipped = [o for o in occ if o.date() in hol_days]
                if skipped:
                    eprops.append(["exdate", dict(params), vtype,
                                   *[fmt(x) for x in skipped]])
        comps.append(["vevent", eprops, []])
    return ["vcalendar", props, comps]


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "." for c in s).strip(".") or "x"


def occurrences(ev: L2Event, ref: dt.datetime, horizon_days: int = 180,
                policy: Policy = DEFAULT_POLICY, cap: int = 500) -> list[dt.datetime]:
    """Expand an event to concrete occurrence datetimes.

    This is the basis for RRULE EQUIVALENCE scoring. Two rules that differ as
    strings ("BYDAY=MO,WE" vs "BYDAY=WE,MO", COUNT=10 vs the matching UNTIL) are
    semantically identical, so comparing occurrence sets is the only honest test.
    """
    r = resolve_event(ev, ref, policy)
    start = r["start"]
    if ev.rrule is None:
        return [start]
    rule = build_rrule(ev.rrule, start, policy, ref)
    end = start + dt.timedelta(days=horizon_days)
    out = []
    for occ in rule:
        if occ > end or len(out) >= cap:
            break
        out.append(occ)
    return out


def occurrence_set(l2: L2, ref: dt.datetime, horizon_days: int = 180,
                   policy: Policy = DEFAULT_POLICY) -> set:
    s = set()
    for ev in l2.events:
        for o in occurrences(ev, ref, horizon_days, policy):
            s.add(o.isoformat())
    return s
