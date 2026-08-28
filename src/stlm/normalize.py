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



from . import holidays as hol

from . import lexicon as lx

from .convert import DEFAULT_POLICY, Policy

from .ir import FLAGS as _FLAGS

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

_NOON = re.compile(r"^(12\s*nn|nn|noon|12\s*n|12\s*noon|midday|noontime|high noon)$", re.I)

_MIDNIGHT = re.compile(r"^(12\s*mn|mn|midnight)$", re.I)

# A dot is a real time separator in the wild -- "7.30pm" is as common as

# "7:30pm" in handwritten notes, and it used to normalize to None, so the

# span was tagged correctly and then produced no time at all.

_HHMM = re.compile(r"^(\d{1,2})[:.](\d{2})")

_MILITARY = re.compile(r"^([01]\d|2[0-3])([0-5]\d)\s*h?$", re.I)

_BARE = re.compile(r"^(\d{1,2})\s*h?$", re.I)

# Generated FROM subjects.TOD_SURFACES so the two directions cannot drift:
# anything the generator can write, the parser can read back. Keeping
# these in sync by hand is what let "umaga" and "lunchtime" be emitted
# into training data that the pipeline itself could not parse.
_TOD = {
    "dawn": "TOD:DAWN",
    "daybreak": "TOD:DAWN",
    "madaling araw": "TOD:DAWN",
    "sunrise": "TOD:DAWN",
    "am": "TOD:MORNING",
    "morning": "TOD:MORNING",
    "mornings": "TOD:MORNING",
    "umaga": "TOD:MORNING",
    "lunchtime": "TOD:NOON",
    "tanghali": "TOD:NOON",
    "afternoon": "TOD:AFTERNOON",
    "afternoons": "TOD:AFTERNOON",
    "hapon": "TOD:AFTERNOON",
    "pm": "TOD:AFTERNOON",
    "dusk": "TOD:EVENING",
    "evening": "TOD:EVENING",
    "evenings": "TOD:EVENING",
    "gabi": "TOD:EVENING",
    "sundown": "TOD:EVENING",
    "night": "TOD:NIGHT",
    "nights": "TOD:NIGHT",
    "nighttime": "TOD:NIGHT",
    "tonight": "TOD:NIGHT",
    "afterwards": "TOD:LATER",
    "in a bit": "TOD:LATER",
    "in a while": "TOD:LATER",
    "later": "TOD:LATER",
    "later today": "TOD:LATER",
    "mamaya": "TOD:LATER",
    "sometime later": "TOD:LATER",
    "after dinner": "TOD:EVENING",
    "first thing": "TOD:MORNING",
    "lunch time": "TOD:NOON",
    "mamaya na": "TOD:LATER",
}

_TOD_RE = re.compile(r"\b(sometime\ later|madaling\ araw|after\ dinner|later\ today|first\ thing|afternoons|afterwards|in\ a\ while|lunch\ time|lunchtime|afternoon|nighttime|mamaya\ na|daybreak|mornings|tanghali|evenings|in\ a\ bit|sunrise|morning|evening|sundown|tonight|nights|mamaya|umaga|hapon|night|later|dawn|dusk|gabi|am|pm)\b", re.I)




def normalize_time(text: str, policy: Policy = DEFAULT_POLICY) -> tuple[str | None, set[str]]:

    """Surface time -> 'HH:MM'. Returns (value, flags)."""

    # Dots do two different jobs: separating h.mm and punctuating "a.m.".

    # Promote the separator to a colon BEFORE stripping the rest, or

    # "7.30pm" collapses to "730pm" and normalizes to nothing at all.

    t = re.sub(r"(?<=\d)\.(?=\d{2})", ":", text.strip().lower())

    t = t.replace(".", "")

    flags: set[str] = set()



    # A time-of-day word resolves to a symbol, not a clock time -- the collapse

    # happens at L3 under policy. Flagged approximate so the UI can say "~8am".

    m = _TOD_RE.search(t)

    if m and not re.search(r"\d", t):

        return _TOD[m.group(1).lower()], {"time_approximate"}



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





_MERIDIEM_HINT = {

    "morning": "am", "dawn": "am", "am": "am",

    "afternoon": "pm", "evening": "pm", "tonight": "pm",

    "night": "pm", "dusk": "pm", "pm": "pm",

}

_HINT_RE = re.compile(r"\b(morning|dawn|afternoon|evening|tonight|night|dusk)\b", re.I)





def meridiem_hint(context: str) -> str | None:

    """A time-of-day word next to a bare hour SETS the meridiem.



    "3 in the morning" is 03:00 even though the 1-6 default says PM, and

    "8 in the evening" is 20:00 even though 7-12 defaults to as-written. The

    word is doing real disambiguating work here, so it must not be discarded as

    redundant the way it is when an explicit am/pm is already present.

    """

    m = _HINT_RE.search(context or "")

    return _MERIDIEM_HINT[m.group(1).lower()] if m else None





def apply_meridiem_hint(value: str, hint: str | None) -> str:

    """Re-point an inferred HH:MM at the half of the day the hint names."""

    if not value or not hint:

        return value

    h, mnt = (int(x) for x in value.split(":"))

    h12 = h % 12

    h = h12 if hint == "am" else (h12 + 12 if h12 else 12)

    if hint == "am" and h12 == 0:

        h = 12 if value.startswith("12") else 0

    return f"{h:02d}:{mnt:02d}"





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





_DATE_LEAD = re.compile(r"^(?:on|by|due|before|starting|start|from|at)\s+", re.I)





def normalize_date(text: str) -> tuple[str | None, set[str]]:

    t = re.sub(r"\s+", " ", text.strip().lower())

    # The annotation guide keeps a leading preposition inside the span ("on the

    # 15th"), but every matcher below is anchored, so it has to come off here.

    t = _DATE_LEAD.sub("", t).strip()

    flags: set[str] = set()



    m = hol.HOLIDAY_RE.search(t)

    if m:

        sym, hflags = hol.lookup(m.group(1))

        if sym or hflags:

            return sym, hflags



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

        # A BARE weekday, with no this/next qualifier. Read as the coming one,

        # but flagged: "Wed stock" may well be a weekly rhythm. "this Monday"

        # takes the branch above and is NOT flagged -- it is unambiguous.

        return f"REL:THIS_{code}", {"relative_date", "recurrence_ambiguous"}



    m = _MD.match(t)

    if m:

        if m.group(1) and m.group(2):

            mon, day = _MONTHS.get(m.group(1)[:3].lower()), int(m.group(2))

        elif m.group(3) and m.group(4):

            mon, day = _MONTHS.get(m.group(4)[:3].lower()), int(m.group(3))

        else:

            # Bare "the 15th": the month is unstated, so it is the NEXT 15th.

            # This used to return None, which meant the DATE span parsed and

            # then resolved to nothing -- the date silently disappeared between

            # L1 and L3. REL:DOM_ gives it somewhere to live.

            dom = int(m.group(5) or 0)

            if 1 <= dom <= 31:

                return f"REL:DOM_{dom}", {"relative_date"}

            return None, {"relative_date"}

        if mon and 1 <= day <= 31:

            # Symbolic, NOT ABS:. "Sept 3" means the next Sept 3, and pinning a

            # year here would make gold expire. Same reasoning as REL:MONTH_.

            return f"REL:MD_{mon}_{day}", set()

    return None, flags





# --- recurrence --------------------------------------------------------------



_INTERVAL_WORDS = {

    "other": 2, "second": 2, "2nd": 2, "two": 2, "2": 2,

    "biweekly": 2, "bi-weekly": 2, "fortnightly": 2, "alt": 2,

    "third": 3, "3rd": 3, "three": 3, "3": 3,

    "fourth": 4, "4th": 4, "four": 4, "4": 4,

}

_NEG = re.compile(r"^(?:except|exc|excluding|but\s+not|not|minus|xcpt|no)\s*(?:on\s+)?(.*)$", re.I)





def _daycodes(text: str) -> list[str]:

    """Look a surface day-code up in the lexicon; fall back to letter parsing."""

    key = re.sub(r"[^a-z]", "", text.lower())

    canon = lx.DAY_CODE_LOOKUP.get(text.strip().lower()) or lx.DAY_CODE_LOOKUP.get(key)

    if canon:

        return canon.split(",")

    word = _DAY_ABBR.get(text.strip().lower())

    if word:

        return [word]

    # Tokenise the string as a day-code cluster, longest form first. Any

    # ALPHABETIC character that cannot be consumed as a day token means this is

    # not a day code at all, and the whole string is rejected.

    #

    # That strictness is load-bearing: without it "holidays" parses as Th + junk

    # and "MTWThF except holidays" silently drops Thursday from the schedule.

    # Skipping unrecognised letters rather than rejecting is the bug.

    FULL = {"monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH",

            "friday": "FR", "saturday": "SA", "sunday": "SU"}

    THREE = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH",

             "fri": "FR", "sat": "SA", "sun": "SU"}

    TWO = {"th": "TH", "tu": "TU", "sa": "SA", "su": "SU",

           "mo": "MO", "we": "WE", "fr": "FR"}

    ONE = {"M": "MO", "T": "TU", "W": "WE", "R": "TH", "H": "TH",

           "F": "FR", "S": "SA", "U": "SU"}



    s = text.strip()

    out, i = [], 0

    while i < len(s):

        if not s[i].isalpha():

            i += 1                      # separators are free

            continue

        for width, table in ((9, FULL), (3, THREE), (2, TWO)):

            for w in range(min(width, len(s) - i), 1, -1):

                tok = s[i : i + w].lower()

                if tok in table:

                    out.append(table[tok])

                    i += w

                    break

            else:

                continue

            break

        else:

            mapped = ONE.get(s[i].upper())

            if mapped is None:

                return []               # an alphabetic char that is not a day

                                        # token -- this is an ordinary word

            out.append(mapped)

            i += 1

    seen = []

    for d in out:

        if d not in seen:

            seen.append(d)

    return seen





_ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,

            "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1}

# "2nd sunday OF THE MONTH" is monthly BYDAY=2SU. Without the "of the month"

# tail, "every 2nd sunday" means every OTHER sunday -- INTERVAL=2. Order and

# the trailing phrase are the only things distinguishing them.

_MONTHLY_ORDINAL_RE = re.compile(

    r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\s+"

    r"(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\s+of\s+(?:the|every|each)\s+month\b",

    re.I)





def normalize_recur(texts: list[str]) -> tuple[RRule | None, set[str], list[str]]:

    """Merge every RECUR span into one rule.



    Multiple spans are normal and expected -- "Biweekly ... every other Tuesday"

    states the same rule twice, and the annotation guide says to tag both. They

    are unioned here, which is exactly why redundancy is the normalizer's problem

    and not the annotator's.

    """

    flags: set[str] = set()

    byday: list[str] = []

    excluded: list[str] = []

    exclusions: list[str] = []

    interval = 1

    freq = None



    for raw in texts:

        t = re.sub(r"\s+", " ", raw.strip())

        low = t.lower()



        mo = _MONTHLY_ORDINAL_RE.search(low)

        if mo:

            n = _ORDINAL[mo.group(1).lower()]

            wd = _DAY_ABBR.get(mo.group(2).lower()) or _daycodes(mo.group(2))[0]

            byday = [f"{n}{wd}"]

            freq = "MONTHLY"

            continue



        neg = _NEG.match(low)

        if neg:

            flags.add("negated_recurrence")

            days = _daycodes(neg.group(1))

            if days:

                for d in days:

                    if d not in excluded:

                        excluded.append(d)

            elif re.search(r"\bholidays?\b", neg.group(1)):

                # "except holidays" is not a weekday subtraction -- it is an

                # EXDATE against a calendar. Kept symbolic; L3 expands it.

                if "HOLIDAYS" not in exclusions:

                    exclusions.append("HOLIDAYS")

                flags.add("excluded_dates")

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



        # Strip the recurrence lead-in so only the weekday cluster is left.

        # \d+ alone missed ordinals -- "every 2nd sunday" kept "2nd" and the

        # day tokenizer then rejected the whole string, returning no rule at all.

        stripped = re.sub(

            r"^(?:every|each|tuwing)\s+"

            r"(?:other\s+|second\s+|third\s+|fourth\s+|two\s+|three\s+|four\s+"

            r"|\d+(?:st|nd|rd|th)?\s+)?",

            "", low).strip()

        for d in _daycodes(stripped or low):

            if d not in byday:

                byday.append(d)



    if excluded:

        base = byday or (ALL_WEEK if freq == "DAILY" else WEEKDAYS_ONLY)

        byday = [d for d in base if d not in excluded]

        freq = "WEEKLY"



    if freq == "MONTHLY":

        return RRule(freq="MONTHLY", interval=interval, byday=byday), flags, exclusions

    if not byday and freq is None:

        return None, flags, exclusions

    if byday:

        freq = "WEEKLY"

    if freq != "MONTHLY":

        byday.sort(key=WEEKDAYS.index)

    return RRule(freq=freq or "WEEKLY", interval=interval, byday=byday), flags, exclusions





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



        rrule, rflags, exclusions = normalize_recur(pick("RECUR"))

        all_flags |= rflags



        hint = meridiem_hint(l1.text)

        tstarts = pick("TSTART")

        start_val, sflags = (None, set())

        if tstarts:

            start_val, sflags = normalize_time(tstarts[0], policy)

            if "ampm_inferred" in sflags and hint and not start_val.startswith("TOD:"):

                start_val = apply_meridiem_hint(start_val, hint)

                sflags.discard("ampm_ambiguous")

                sflags.discard("ampm_inferred")

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

        # Two title fragments split by a temporal span ("Mom's birthday Oct 21

        # dinner") are tagged as two SUMMARY spans and rejoined with a comma.

        # No discontinuous-span machinery needed -- repeated span types are

        # already legal, the same way RECUR repeats.

        summary = ", ".join(p.strip() for p in summary_parts if p.strip()) or None

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

            exclude=exclusions,

        ))



    if len(events) > 1:

        all_flags.add("multi_event")



    # A named date we cannot compute (lunar holidays move by weeks between

    # years) must not fall through to the REL:TODAY default. Scheduling Chinese

    # New Year lunch for today is a silent catastrophic error by TARGET.md's own

    # definition; refusing is the honest answer.

    if "named_date_unresolvable" in all_flags:

        known = set(_FLAGS)

        return L2(id=l1.id, events=[], status="unresolvable",

                  flags=sorted(f for f in all_flags if f in known)), trace



    known = set()

    from .ir import FLAGS as _F

    known = set(_F)

    l2 = L2(id=l1.id, events=events, status="ok",

            flags=sorted(f for f in all_flags if f in known))

    trace.flags = all_flags - known

    return l2, trace





def parse(text: str, item_id: str = "x", policy: Policy = DEFAULT_POLICY) -> tuple[L2, Trace]:

    """Full rule pipeline: raw text -> L2. This IS the M5 baseline."""

    from .segment import spans_and_groups



    spans, groups = spans_and_groups(text)

    l1 = L1(id=item_id, text=text, spans=spans, event_groups=groups,

            status="ok" if spans else "no_temporal")

    return l1_to_l2(l1, policy)

