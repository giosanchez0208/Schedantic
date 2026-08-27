"""Named-date interpreter: "christmas", "holy week", "undas" -> symbolic dates.

Why this exists despite 0 hits in the corpus: the corpus cannot see holidays.
Contributors wrote against prompts that asked for recurrence, bounds, negation
and times -- never for a named date. Absence here is a property of the prompt,
not of the world. Same reasoning already applied to the PERSON slot.

Three kinds of named date, and they resolve differently:

  fixed      Dec 25 every year          -> REL:MD_<month>_<day>   (existing symbol)
  computed   Good Friday = Easter - 2   -> REL:EASTER<+/-n>
             Thanksgiving = 4th Thu Nov -> REL:NTH_<n>_<weekday>_<month>
  lunar      Chinese New Year, Eid      -> not resolvable in code; flagged honestly

Locale matters. This table is Philippine-first because that is the target
register, with widely-known international dates alongside. A US-default table
would be wrong here: Undas, Bonifacio Day and EDSA are the ones that actually
appear in a Filipino student's calendar, and Thanksgiving is not.
"""

from __future__ import annotations

import datetime as dt
import re

PH = "ph"
INTL = "intl"
US = "us"

# name -> (symbol, locale). Surface variants are listed separately below.
FIXED: dict[str, tuple[str, str]] = {
    "new year": ("REL:MD_1_1", INTL),
    "new years eve": ("REL:MD_12_31", INTL),
    "valentines": ("REL:MD_2_14", INTL),
    "edsa": ("REL:MD_2_25", PH),
    "st patricks": ("REL:MD_3_17", INTL),
    "araw ng kagitingan": ("REL:MD_4_9", PH),
    "labor day": ("REL:MD_5_1", PH),
    "independence day": ("REL:MD_6_12", PH),
    "ninoy aquino day": ("REL:MD_8_21", PH),
    "halloween": ("REL:MD_10_31", INTL),
    "undas": ("REL:MD_11_1", PH),
    "all saints": ("REL:MD_11_1", PH),
    "all souls": ("REL:MD_11_2", PH),
    "bonifacio day": ("REL:MD_11_30", PH),
    "immaculate conception": ("REL:MD_12_8", PH),
    "christmas eve": ("REL:MD_12_24", INTL),
    "christmas": ("REL:MD_12_25", INTL),
    "boxing day": ("REL:MD_12_26", INTL),
    "rizal day": ("REL:MD_12_30", PH),
}

# Easter-relative. Holy Week is a major fixture of the Philippine calendar, so
# these earn their keep even though they need real computation.
EASTER_RELATIVE: dict[str, tuple[int, str]] = {
    "ash wednesday": (-46, INTL),
    "palm sunday": (-7, PH),
    "holy week": (-7, PH),      # the week starts at Palm Sunday
    "maundy thursday": (-3, PH),
    "holy thursday": (-3, PH),
    "good friday": (-2, PH),
    "black saturday": (-1, PH),
    "holy saturday": (-1, PH),
    "easter": (0, INTL),
    "easter sunday": (0, INTL),
}

# nth weekday of a month: (n, weekday 0=Mon, month). n = -1 means last.
NTH_WEEKDAY: dict[str, tuple[int, int, int, str]] = {
    "mothers day": (2, 6, 5, INTL),        # 2nd Sunday of May
    "fathers day": (3, 6, 6, INTL),        # 3rd Sunday of June
    "national heroes day": (-1, 0, 8, PH),  # last Monday of August
    "thanksgiving": (4, 3, 11, US),        # 4th Thursday of November
    "labour day uk": (1, 0, 5, INTL),
}

# Lunar / astronomically determined. Deliberately NOT guessed -- these move by
# weeks between years and a wrong guess is worse than an honest failure.
LUNAR = {
    "chinese new year", "cny", "lunar new year",
    "eid", "eid al fitr", "eidl fitr", "eid al adha", "eidl adha",
    "ramadan", "diwali", "hanukkah", "rosh hashanah",
}

# Surface spelling -> canonical key. Everything is matched case-insensitively
# with punctuation and apostrophes stripped, so "Valentine's" needs no entry.
ALIASES: dict[str, str] = {
    "xmas": "christmas",
    "x mas": "christmas",
    "christmas day": "christmas",
    "pasko": "christmas",
    "noche buena": "christmas eve",
    "xmas eve": "christmas eve",
    "new years": "new year",
    "new years day": "new year",
    "nye": "new years eve",
    "media noche": "new years eve",
    "valentine": "valentines",
    "valentines day": "valentines",
    "vday": "valentines",
    "hallows eve": "halloween",
    "all saints day": "all saints",
    "all souls day": "all souls",
    "undas": "undas",
    "araw ng mga patay": "all souls",
    "edsa revolution": "edsa",
    "people power": "edsa",
    "day of valor": "araw ng kagitingan",
    "bataan day": "araw ng kagitingan",
    "mother s day": "mothers day",
    "father s day": "fathers day",
    "heroes day": "national heroes day",
    "turkey day": "thanksgiving",
    "semana santa": "holy week",
    "mahal na araw": "holy week",
    "biernes santo": "good friday",
    "huwebes santo": "maundy thursday",
    "paskuwa": "easter",
}


def canon(text: str) -> str:
    """Normalise a surface form for lookup: lowercase, no punctuation."""
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


def _all_keys() -> list[str]:
    keys = set(FIXED) | set(EASTER_RELATIVE) | set(NTH_WEEKDAY) | set(LUNAR) | set(ALIASES)
    return sorted(keys, key=len, reverse=True)


# Longest-first so "christmas eve" wins over "christmas", and "new years eve"
# over "new year".
HOLIDAY_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(k).replace(r"\ ", r"[\s'.-]*")
                              for k in _all_keys()) + r")(?![a-z])",
    re.I,
)


def lookup(text: str) -> tuple[str | None, set[str]]:
    """Surface holiday name -> symbolic date. Returns (symbol, flags)."""
    key = canon(text)
    key = ALIASES.get(key, key)
    if key in LUNAR:
        # Honest failure. Chinese New Year moved by 5 weeks between 2024 and 2025;
        # a computed guess would be confidently wrong, which is the worst outcome.
        return None, {"named_date_unresolvable"}
    if key in FIXED:
        return FIXED[key][0], {"named_date"}
    if key in EASTER_RELATIVE:
        off = EASTER_RELATIVE[key][0]
        return f"REL:EASTER{off:+d}", {"named_date"}
    if key in NTH_WEEKDAY:
        n, wd, month, _loc = NTH_WEEKDAY[key]
        return f"REL:NTH_{n}_{wd}_{month}", {"named_date"}
    return None, set()


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous computus, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month, day = divmod(h + L - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """n-th `weekday` of `month`. n = -1 means the last one."""
    if n == -1:
        d = dt.date(year, month, 1)
        nxt = dt.date(year + (month == 12), (month % 12) + 1, 1)
        last = nxt - dt.timedelta(days=1)
        return last - dt.timedelta(days=(last.weekday() - weekday) % 7)
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


# --- EXDATE support ----------------------------------------------------------

def dates_between(start: dt.date, end: dt.date,
                  locales: tuple[str, ...] = (PH, INTL)) -> list[dt.date]:
    """Every known holiday falling in [start, end].

    This is what turns "MTWThF except holidays" from unrepresentable into an
    RFC 5545 EXDATE list. It is only as good as the table: lunar holidays are
    absent, and "holidays" may not mean national holidays to the writer. Callers
    should flag the result as approximate rather than presenting it as complete.
    """
    out: list[dt.date] = []
    for year in range(start.year, end.year + 1):
        for key, (sym, loc) in FIXED.items():
            if loc not in locales:
                continue
            m, d = (int(x) for x in sym[len("REL:MD_"):].split("_"))
            try:
                cand = dt.date(year, m, d)
            except ValueError:
                continue
            if start <= cand <= end:
                out.append(cand)
        for key, (off, loc) in EASTER_RELATIVE.items():
            if loc not in locales:
                continue
            cand = easter(year) + dt.timedelta(days=off)
            if start <= cand <= end:
                out.append(cand)
        for key, (n, wd, month, loc) in NTH_WEEKDAY.items():
            if loc not in locales:
                continue
            cand = nth_weekday(year, month, wd, n)
            if start <= cand <= end:
                out.append(cand)
    return sorted(set(out))
