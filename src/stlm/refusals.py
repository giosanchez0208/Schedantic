"""Compositional generator for strings the system must REFUSE rather than guess.

Two statuses live here, and they are different failures:

  unresolvable    -- a real event, but nothing in the text pins a date or time.
                     "lets hoop one of these days when ur not busy"
  unrepresentable -- the text is perfectly clear to a human, and the L2 schema
                     genuinely cannot hold it. "Vitamins every day but not when
                     I travel" is a rule, just not one RFC 5545 can express.

Both matter more than their 7% of gold suggests. TARGET.md defines a silent
catastrophic error as a confident wrong answer with no flag, and these are
exactly the strings that produce one: every single element looks parseable, so a
greedy parser emits a plausible event and never says it was unsure. Refusing is
the correct output, which means the model has to be TAUGHT to refuse, which
means the classes need training signal. The generator previously emitted zero of
either -- 2 of the 4 statuses had no data at all.

Frames are derived from the 28 human-written examples in gold, not invented. The
families below are theirs: conditional recurrence, external trigger, drifting
natural cycle, multi-day span, institution-specific period, vague future window.
Nobody would guess "transect counts every spring low tide, so it Shifts like 50
min a day" from an armchair.

Those 28 stay the EVALUATION set. They are never trained on, or there is nothing
left to measure with. Same rule as the 56 human negatives in negatives.py.

Deriving them the first time went wrong in a way worth recording: several frames
were the human sentence with ONE slot swapped, and the slot pool still held the
human's own filler, so six eval strings were reachable verbatim. Derive the
SHAPE, never the sentence. test_refusal_frames asserts the overlap stays zero.
"""

from __future__ import annotations

import random
import re

# --- slot vocabularies -------------------------------------------------------

ACTIVITY = ["gym", "Morning jog", "pickup ball", "vitamins", "the transect counts",
            "yoga", "sea glass hunting", "the inventory count", "choir practice",
            "stretches", "the reading group", "lap swim", "range practice"]
EVENT = ["the sendoff", "the roof inspection", "the Reenactment", "the colloquium",
         "the fun run", "the alumni mixer", "the plant swap", "the panel",
         "the fundraiser", "the block party", "the site visit", "the recital",
         "the swap meet", "the potluck"]
EVENT_TITLED = ["Flu Shot table", "Blood Drive", "Book Fair", "Career Expo",
                "Mobile Library", "The Parish Council", "The Barangay Office",
                "The Alumni Board", "Wellness Fair", "The Co-op"]
PLACE = ["the rec center", "CS Bldg", "the convention center", "the clinic",
         "the community hall", "the pier", "the annex", "the field house",
         "the parish hall", "the old armory", "the boat house"]
PERSON = ["Bex", "Tasha", "Dez", "Gus", "Mia", "Delaney", "Ledger", "Nadine",
          "Rome", "Elmer"]
VAGUE_PERIOD = ["this Quarter", "this sem", "this term", "next quarter",
                "in the coming months", "in the back half of the year"]
VAGUE_EVENT = ["the holiday rush dies down", "the audit wraps", "finals settle down",
               "the renovation finishes", "the rainy season", "the busy season",
               "the transfer window closes", "the semester rush ends"]
INST_PERIOD = ["Homecoming week", "Spring Break", "Intrams", "Recollection week",
               "Founders Week", "reading week", "Sportsfest", "orientation week"]
CONDITION = ["im not on duty", "the pager goes", "my shift allows",
             "the ward is quiet", "the truck is free", "im not on call",
             "the studio is open", "im off rotation"]
NEG_CONDITION = ["it doesnt rain", "theres no typhoon signal", "the court isnt booked",
                 "the tide isnt out", "nobody calls in sick"]
EXCUSE = ["I travel", "I forget", "im on nights", "were short staffed",
          "the kids have something", "im out of town"]
OTHER_EVENT = ["bible study", "the retreat", "exam week", "the parish fiesta",
               "inventory season", "the conference"]
EXTERNAL = ["a big consignment drop", "a new ep", "a restock", "a shipment",
            "a grant cycle", "a new build"]
NATURAL = ["the swell drops under 3 ft", "the tide goes below a foot",
           "the wind dies down", "the visibility clears", "the river runs low"]
CYCLE = ["spring low tide", "king tide", "new moon", "lunar low",
         "neap tide"]
TURNOUT = ["we can get 8 people", "we hit 4 players", "enough people show",
           "we have a quorum", "we can fill a van"]
APPROX_FREQ = ["2-3x a wEek", "maybe twice a month", "a few times a term",
               "once or twice a week", "roughly every other week"]
RECUR = ["every day", "daily", "every Tue", "every other sat", "every sun",
         "weekly", "every wed"]
DAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
HOLIDAY = ["thanksgiving", "New Yrs", "Christmas", "All Souls Day", "Easter",
           "Undas", "Holy Week"]
MONTH = ["Oct", "Sept", "Nov", "March", "June", "Jan", "Aug"]
ROLE = ["The Response Team", "The Duty Roster", "The On Call Pool",
        "Dispatch", "The Relief Crew"]
TRIGGER = ["the pager goes", "the hotline rings", "dispatch calls",
           "the alert comes in"]


def _fill(rng: random.Random, template: str) -> str:
    out = template
    for _ in range(6):
        if "{" not in out:
            break
        for name, pool in _POOLS.items():
            token = "{" + name + "}"
            while token in out:
                out = out.replace(token, str(rng.choice(pool)), 1)
    return out


# --- frames ------------------------------------------------------------------
# (status, family, template, weight)

FRAMES: list[tuple[str, str, str, float]] = [
    # ---- unresolvable: a real event with nothing to pin it to ----------------
    ("unresolvable", "no-temporal-info", "{ACTIVITY} @ {PLACE}", 2.0),
    ("unresolvable", "no-temporal-info", "{EVENT} at {PLACE}", 2.0),
    ("unresolvable", "no-temporal-info", "lets {ACTIVITY} one of these days when ur not busy", 2.0),
    ("unresolvable", "no-temporal-info", "coffee w/ {PERSON} at some point, no rush", 1.5),

    ("unresolvable", "vague-window", "coffee w/ {PERSON} sometime after {VAGUE_EVENT}", 2.5),
    ("unresolvable", "vague-window", "{EVENT} at some point {VAGUE_PERIOD}", 2.5),
    ("unresolvable", "vague-window", "were doing {EVENT} at some point before {PERSON} leaves", 2.0),
    ("unresolvable", "vague-window", "{EVENT_TITLED} will push thru Sometime after {VAGUE_EVENT}, details TBA", 2.0),
    ("unresolvable", "vague-window", "{ACTIVITY} sometime {VAGUE_PERIOD}, ill confirm later", 1.5),

    ("unresolvable", "institution-period", "{EVENT_TITLED} at {PLACE} is up all of {INST_PERIOD}", 2.5),
    ("unresolvable", "institution-period", "{EVENT} runs during {INST_PERIOD}", 2.0),

    ("unresolvable", "count-no-frequency", "{ACTIVITY} {N} sessions total", 2.0),
    ("unresolvable", "count-no-frequency", "{N} sessions of {ACTIVITY}, thats the package", 1.5),

    ("unresolvable", "announced-later", "{EVENT_TITLED} will announce the {EVENT} date once {NEG_CONDITION}", 2.5),
    ("unresolvable", "announced-later", "we'll run {EVENT} whenever everyone's schedules line up again", 2.0),
    ("unresolvable", "announced-later", "{EVENT_TITLED} will schedule {EVENT} at some point {VAGUE_PERIOD}, tenants notified 48 hrs prior", 1.5),

    # ---- unrepresentable: clear to a human, not expressible in L2 ------------
    ("unrepresentable", "conditional-recurrence", "{ACTIVITY} when {CONDITION}, usually {APPROX_FREQ}", 3.0),
    ("unrepresentable", "conditional-recurrence", "{ACTIVITY} every day that {NEG_CONDITION}", 2.5),
    ("unrepresentable", "conditional-recurrence", "{EVENT} runs {RECUR} but only if {TURNOUT}, otherwise we bail", 2.5),
    ("unrepresentable", "conditional-recurrence", "{ACTIVITY} whenever {TURNOUT}, mostly {DAY}s", 2.5),
    ("unrepresentable", "conditional-recurrence", "{ACTIVITY} {RECUR} that {NEG_CONDITION}, otherwise indoors", 1.5),

    ("unrepresentable", "conditional-exclusion", "{ACTIVITY} {RECUR} but not when {EXCUSE}", 3.0),
    ("unrepresentable", "conditional-exclusion", "My {ACTIVITY} {RECUR} except when {EXCUSE}", 2.5),
    ("unrepresentable", "conditional-exclusion", "{ACTIVITY} {RECUR} but not during {OTHER_EVENT}", 2.5),

    ("unrepresentable", "external-trigger", "{ACTIVITY} every time {EXTERNAL} lands, whenever that is", 2.5),
    ("unrepresentable", "external-trigger", "{ROLE} puts you On Call for a rotation, you go when {TRIGGER}, no set times", 2.0),
    ("unrepresentable", "external-trigger", "{ACTIVITY} happen whenever {NATURAL}, could be any morning", 2.0),
    ("unrepresentable", "external-trigger", "{ACTIVITY} every time {EXTERNAL} drops, which moves when the studio shifts the slot", 1.5),

    ("unrepresentable", "drifting-cycle", "{ACTIVITY} every {CYCLE}, so it Shifts like {MIN} min a day", 2.0),
    ("unrepresentable", "drifting-cycle", "{ACTIVITY} follows the {CYCLE}, drifts a bit each time", 1.5),

    ("unrepresentable", "date-range", "{MONTH} {D1}-{D2} {EVENT} at {PLACE}", 2.5),
    ("unrepresentable", "date-range", "{EVENT_TITLED} {MONTH} {D1}-{D2}, block the whole stretch", 1.5),

    ("unrepresentable", "week-long-span", "{EVENT_TITLED} at {PLACE} runs the whole week before {HOLIDAY}", 2.5),
    ("unrepresentable", "week-long-span", "{EVENT_TITLED} at {PLACE} the whole week after {HOLIDAY}", 2.5),

    ("unrepresentable", "institution-offset", "{EVENT} the week before {INST_PERIOD}", 2.0),
    ("unrepresentable", "institution-offset", "{EVENT} sometime during {INST_PERIOD}, exact day TBA", 1.5),
]

_POOLS: dict[str, list] = {
    "ACTIVITY": ACTIVITY,
    "EVENT": EVENT,
    "EVENT_TITLED": EVENT_TITLED,
    "PLACE": PLACE,
    "PERSON": PERSON,
    "VAGUE_PERIOD": VAGUE_PERIOD,
    "VAGUE_EVENT": VAGUE_EVENT,
    "INST_PERIOD": INST_PERIOD,
    "CONDITION": CONDITION,
    "NEG_CONDITION": NEG_CONDITION,
    "EXCUSE": EXCUSE,
    "OTHER_EVENT": OTHER_EVENT,
    "EXTERNAL": EXTERNAL,
    "NATURAL": NATURAL,
    "CYCLE": CYCLE,
    "TURNOUT": TURNOUT,
    "APPROX_FREQ": APPROX_FREQ,
    "RECUR": RECUR,
    "DAY": DAY,
    "HOLIDAY": HOLIDAY,
    "MONTH": MONTH,
    "ROLE": ROLE,
    "TRIGGER": TRIGGER,
    "N": [str(n) for n in (4, 5, 6, 8, 10, 12)],
    "MIN": [str(n) for n in (30, 45, 50, 55)],
    "D1": [str(n) for n in range(1, 26)],
    "D2": [str(n) for n in range(2, 29)],
}

# Families whose surface names a real holiday from holidays.py. The anchor
# resolves; it is the WEEK-LONG SPAN around it that L2 cannot hold, so the flag
# is still correct and the refusal is still correct.
_NAMED_DATE = {"week-long-span"}
# A count with no frequency really is a count, so it keeps the flag it earns.
_BOUNDED_COUNT = {"count-no-frequency"}


_RANGE_RE = re.compile(r"\b(\d{1,2})-(\d{1,2})\b")


def _fix_range(rng: random.Random, text: str) -> str:
    """Make "Oct 21-3" into "Oct 21-23".

    The two day slots are drawn independently, so roughly half of them come out
    backwards. A malformed range is a DIFFERENT kind of unparseable than a
    multi-day event, and training on it would teach the refusal for the wrong
    reason.
    """
    def repair(m: re.Match) -> str:
        a = int(m.group(1))
        return f"{a}-{a + rng.randint(1, 4)}"

    return _RANGE_RE.sub(repair, text, count=1)


def sample(rng: random.Random) -> tuple[str, str, str, set[str]]:
    """Return (text, status, family, flags). Status is correct by construction."""
    weights = [f[3] for f in FRAMES]
    i = rng.choices(range(len(FRAMES)), weights=weights, k=1)[0]
    status, family, template, _ = FRAMES[i]
    text = _fill(rng, template)
    if family == "date-range":
        text = _fix_range(rng, text)
    flags: set[str] = set()
    if family in _NAMED_DATE:
        flags.add("named_date")
    if family in _BOUNDED_COUNT:
        flags.add("bounded_count")
    return text, status, family, flags


def family_ids() -> list[str]:
    return sorted({f[1] for f in FRAMES})


def statuses() -> list[str]:
    return sorted({f[0] for f in FRAMES})
