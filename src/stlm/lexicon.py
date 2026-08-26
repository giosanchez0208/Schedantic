"""Surface-form inventory: canonical value <-> every way of writing it.

Read left-to-right this is the PARSER's normalization table (M2).
Read right-to-left it is the GENERATOR's realization table (M7).
One artifact, two stages.

Weights are sampling frequencies. Seed weights below are PROVISIONAL -- they are
the author's priors, not measurements. They get recalibrated from
corpus/harvested.jsonl and, when it exists, the human gold corpus.
Anything recalibrated is marked in documentation/FINDINGS.md.
"""

from __future__ import annotations

# --- day codes ---------------------------------------------------------------
# canonical is an RFC 5545 BYDAY list.

DAY_CODES: dict[str, list[tuple[str, float]]] = {
    "MO,WE,FR": [
        ("MWF", 10.0), ("mwf", 6.0), ("M/W/F", 2.0), ("M-W-F", 1.5),
        ("Mon Wed Fri", 1.5), ("MonWedFri", 0.5), ("M W F", 1.0), ("mon/wed/fri", 0.5),
    ],
    "TU,TH": [
        ("TTh", 8.0), ("tth", 4.0), ("TR", 5.0), ("T/Th", 2.0), ("TuTh", 1.5),
        ("Tue Thu", 1.5), ("T-Th", 1.0), ("TTH", 1.0), ("tues/thurs", 0.5),
    ],
    "MO,WE": [("MW", 6.0), ("mw", 3.0), ("M/W", 1.0), ("Mon Wed", 1.0)],
    "TU,TH,SA": [("TThS", 1.0), ("TTHS", 0.5)],
    "MO,TU,WE,TH,FR": [
        ("MTWThF", 3.0), ("MTWRF", 3.0), ("MTWHF", 1.5), ("M-F", 3.0),
        ("Mon-Fri", 2.5), ("weekdays", 1.5), ("daily", 1.0),
    ],
    "MO": [("M", 3.0), ("Mon", 3.0), ("Monday", 3.0), ("mon", 2.0), ("monday", 2.0)],
    "TU": [("T", 2.0), ("Tue", 2.5), ("Tues", 2.0), ("Tuesday", 3.0), ("tues", 1.5)],
    "WE": [("W", 3.0), ("Wed", 3.0), ("Wednesday", 3.0), ("wed", 2.0)],
    "TH": [("Th", 2.5), ("Thu", 2.0), ("Thurs", 2.0), ("Thursday", 3.0), ("R", 1.5)],
    "FR": [("F", 3.0), ("Fri", 3.0), ("Friday", 3.0), ("fri", 2.0)],
    "SA": [("S", 1.0), ("Sat", 3.0), ("Saturday", 2.5), ("sat", 2.0)],
    "SU": [("Su", 1.5), ("Sun", 2.5), ("Sunday", 2.5), ("U", 0.5)],
    "SA,SU": [("SS", 0.5), ("Sat Sun", 1.5), ("weekends", 1.5), ("Sat/Sun", 1.0)],
}

# --- times -------------------------------------------------------------------
# canonical is 24h "HH:MM".

def _hour_surfaces(h24: int) -> list[tuple[str, float]]:
    """Generate the standard family of surface forms for a whole hour."""
    h12 = h24 % 12 or 12
    mer = "am" if h24 < 12 else "pm"
    out = [
        (f"{h12}{mer}", 10.0),
        (f"{h12}{mer.upper()}", 2.0),
        (f"{h12} {mer}", 3.0),
        (f"{h12}:00{mer}", 2.0),
        (f"{h12}:00 {mer}", 1.5),
        (f"{h12}.{mer}", 0.4),
        (f"{h24:02d}:00", 3.0),
        (f"{h24:02d}00", 1.5),
        (f"{h24:02d}00H", 0.8),
        (f"{h12}:00", 2.0),
        (f"{h12}", 4.0),  # bare hour -- the ampm_ambiguous case
    ]
    return out


TIMES: dict[str, list[tuple[str, float]]] = {}
for _h in range(0, 24):
    TIMES[f"{_h:02d}:00"] = _hour_surfaces(_h)

# Noon and midnight get extra culturally-specific forms.
# "NN" for noon is a Philippine / SE-Asian academic convention -- central to the
# target user's own examples ("8-12NN").
TIMES["12:00"] += [
    ("12NN", 6.0), ("12nn", 4.0), ("noon", 3.0), ("12 noon", 1.5),
    ("NN", 1.0), ("12N", 0.8),
]
TIMES["00:00"] += [("12MN", 2.0), ("12mn", 1.5), ("midnight", 2.0), ("12 midnight", 0.8)]

# Half hours.
for _h in range(0, 24):
    _h12 = _h % 12 or 12
    _mer = "am" if _h < 12 else "pm"
    TIMES[f"{_h:02d}:30"] = [
        (f"{_h12}:30{_mer}", 8.0), (f"{_h12}:30 {_mer}", 3.0), (f"{_h12}:30", 4.0),
        (f"{_h:02d}:30", 3.0), (f"{_h:02d}30", 1.5), (f"{_h12}.30", 1.0),
        (f"half past {_h12}", 0.5),
    ]

# Quarter hours (much rarer, but real in university catalogs: 9:15, 3:45).
for _h in range(0, 24):
    _h12 = _h % 12 or 12
    _mer = "am" if _h < 12 else "pm"
    for _m in (15, 45, 50, 20):
        TIMES[f"{_h:02d}:{_m:02d}"] = [
            (f"{_h12}:{_m:02d}{_mer}", 5.0), (f"{_h12}:{_m:02d} {_mer}", 2.0),
            (f"{_h12}:{_m:02d}", 3.0), (f"{_h:02d}:{_m:02d}", 2.5), (f"{_h:02d}{_m:02d}", 1.0),
        ]

RANGE_SEPS: list[tuple[str, float]] = [
    ("-", 10.0), (" - ", 4.0), ("to", 3.0), (" to ", 3.0), ("~", 0.5),
    ("till", 1.0), ("until", 1.0), ("–", 1.0), ("thru", 0.5), ("--", 0.5),
]

# --- recurrence phrasing -----------------------------------------------------

INTERVAL_PHRASES: dict[int, list[tuple[str, float]]] = {
    2: [
        ("every other", 6.0), ("biweekly", 3.0), ("bi-weekly", 1.5),
        ("fortnightly", 1.0), ("every 2", 2.0), ("every two", 1.5), ("alt", 0.5),
    ],
    3: [("every 3", 1.0), ("every three", 0.8), ("every third", 0.8)],
}

RECUR_PREFIXES: list[tuple[str, float]] = [
    ("", 10.0), ("every ", 5.0), ("each ", 2.0), ("weekly on ", 1.0),
    ("tuwing ", 0.3), ("every single ", 0.3),
]

BOUND_UNTIL: list[tuple[str, float]] = [
    ("until {}", 5.0), ("till {}", 3.0), ("til {}", 1.5), ("thru {}", 1.0),
    ("up to {}", 0.8), ("ends {}", 1.0), ("- {}", 0.5),
]

BOUND_COUNT: list[tuple[str, float]] = [
    ("for {} weeks", 4.0), ("x{}", 2.0), ("{} sessions", 1.5),
    ("for {} sessions", 1.5), ("{} times", 1.0), ("for the next {} weeks", 1.0),
]

NEGATION: list[tuple[str, float]] = [
    ("except {}", 4.0), ("exc {}", 1.0), ("but not {}", 1.5),
    ("minus {}", 0.5), ("no {}", 1.0), ("except on {}", 1.0),
]

# --- relative dates ----------------------------------------------------------

REL_DATES: dict[str, list[tuple[str, float]]] = {
    "REL:TODAY": [("today", 6.0), ("tdy", 1.0), ("2day", 0.5), ("later today", 1.0)],
    "REL:TOMORROW": [
        ("tomorrow", 8.0), ("tmrw", 5.0), ("tmr", 2.0), ("tom", 1.5),
        ("2moro", 0.5), ("tomo", 1.0), ("bukas", 0.3),
    ],
    "REL:DAY_AFTER_TOMORROW": [
        ("day after tomorrow", 4.0), ("day after tmrw", 3.0), ("Day after Tmrw", 2.0),
        ("the day after tmrw", 1.0), ("in 2 days", 1.5), ("overmorrow", 0.2),
    ],
}
_DAY_NAMES = {
    "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday",
    "FR": "Friday", "SA": "Saturday", "SU": "Sunday",
}
for _c, _n in _DAY_NAMES.items():
    _s = _n[:3]
    REL_DATES[f"REL:THIS_{_c}"] = [
        (f"this {_n}", 6.0), (f"This {_n}", 3.0), (f"this {_s}", 2.0),
        (f"this coming {_n}", 1.0), (_n, 3.0), (_s, 1.5),
    ]
    REL_DATES[f"REL:NEXT_{_c}"] = [
        (f"next {_n}", 6.0), (f"nxt {_n}", 1.5), (f"next {_s}", 2.0),
        (f"Next {_n}", 2.0), (f"next wk {_s}", 0.5),
    ]

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_SURFACES: dict[int, list[tuple[str, float]]] = {}
for _i, _m in enumerate(MONTHS, start=1):
    _short = _m[:3]
    forms = [(_m, 5.0), (_short, 3.0), (_short.lower(), 1.5), (_m.lower(), 2.0)]
    if _m == "September":
        forms.append(("Sept", 2.0))
    MONTH_SURFACES[_i] = forms

# --- fillers -----------------------------------------------------------------

HONORIFICS = ["Sir", "Ma'am", "Maam", "Mr", "Mr.", "Ms", "Ms.", "Mrs", "Prof", "Prof.",
              "Dr", "Dr.", "Engr", "Engr.", "Atty", "Coach", "Tita", "Kuya"]

FIRST_NAMES = [
    "Jefferson", "Jeff", "Kyle", "Maria", "Jose", "Anna", "Miguel", "Sofia", "Liam",
    "Noah", "Olivia", "Emma", "Ava", "Ethan", "Grace", "Rico", "Bea", "Carlo", "Dina",
    "Elmer", "Fatima", "Gabby", "Hannah", "Ivan", "Joy", "Kenji", "Lala", "Marco",
    "Nina", "Oscar", "Paolo", "Queenie", "Rosa", "Sam", "Tina", "Ubet", "Vince",
    "Wendy", "Xander", "Yuri", "Zeke", "Boss", "Mom", "Dad", "Ate", "Nanay",
]

SUBJECT_PREFIXES = [
    "CCC", "MATH", "ENG", "PHYS", "CHEM", "BIO", "HIST", "PSYCH", "ECON", "ACCT",
    "CS", "IT", "STAT", "PE", "NSTP", "GE", "FIL", "SOC", "PHILO", "ARTS", "RIZAL",
]

ACTIVITIES = [
    "swimming", "skating", "ballet class", "gym", "badminton", "basketball", "jogging",
    "grocery", "laundry", "haircut", "dentist", "checkup", "therapy", "tutoring",
    "guitar lesson", "piano", "choir practice", "band rehearsal", "study group",
    "thesis defense", "lab", "consultation", "review session", "meeting", "standup",
    "1on1", "sync", "retro", "sprint planning", "interview", "dinner", "lunch",
    "coffee", "movie night", "church", "mass", "family day", "shift", "duty",
]

EVENT_NOUNS = [
    "Meeting", "Class", "Lecture", "Laboratory", "Lab", "Seminar", "Workshop",
    "Practice", "Rehearsal", "Session", "Review", "Exam", "Quiz", "Recitation",
    "Tutorial", "Clinic", "Training", "Orientation", "Assembly",
]

LOCATIONS = [
    "Rm 201", "Room 305", "rm201", "AVR", "Gym", "Library", "Lab 3", "Bldg C",
    "Zoom", "Google Meet", "online", "Starbucks", "the cafe", "Field", "Court 2",
    "CS Building", "Annex", "3rd floor", "Main Hall",
]

# Tokens that LOOK temporal but are not, in context. High-value hard negatives.
LOOKALIKE_TEMPLATES = [
    "My friends are to be wed",
    "March was fun",
    "Sat down for coffee",
    "I may go later",
    "We wed in June actually no scratch that",
    "She said she may",
    "The march went on for hours",
    "He sat there quietly",
    "August is a nice name",
    "My sister May is coming over",
    "Sun was too bright",
    "I have to go",
    "nothing much today honestly",
    "Fri is short for Frida",
    "wed my best friend someday",
]

NO_TEMPORAL_TEMPLATES = [
    "I have to go",
    "ok thanks",
    "sounds good",
    "let me know",
    "idk yet",
    "will confirm later",
    "cancelled",
    "nvm",
    "sure thing",
    "who is coming",
]


def invert(table: dict[str, list[tuple[str, float]]]) -> dict[str, str]:
    """canonical -> surfaces  becomes  surface(lowercased) -> canonical.

    Later entries do not clobber earlier ones, so higher-priority canonicals
    should be inserted first. Collisions are reported by lexicon_collisions().
    """
    out: dict[str, str] = {}
    for canon, surfaces in table.items():
        for s, _w in surfaces:
            k = s.lower()
            if k not in out:
                out[k] = canon
    return out


def lexicon_collisions(table: dict[str, list[tuple[str, float]]]) -> dict[str, list[str]]:
    """Surfaces that map to more than one canonical value -- genuine ambiguity."""
    seen: dict[str, list[str]] = {}
    for canon, surfaces in table.items():
        for s, _w in surfaces:
            seen.setdefault(s.lower(), []).append(canon)
    return {k: v for k, v in seen.items() if len(v) > 1}


DAY_CODE_LOOKUP = invert(DAY_CODES)
TIME_LOOKUP = invert(TIMES)
REL_DATE_LOOKUP = invert(REL_DATES)
