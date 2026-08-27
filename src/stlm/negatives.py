"""Compositional generator for NOT-A-SCHEDULE strings.

The problem this exists to solve: positives are correct by construction -- sample
a meaning, verbalize it, the label falls out -- but "not a schedule" is not a
structure you can sample. It is the COMPLEMENT of one. So the old generator fell
back to a list of 25 hand-written strings, and 20,000 generated rows contained
24 distinct negatives. Scaling changed nothing.

The fix is to sample the REASON a string is not a schedule, then verbalize that.
Each frame guarantees the non-temporal reading structurally, the same way
sampling BYDAY=[MO,WE,FR] guarantees the recurrence label.

Frames are derived from the 56 human-written negatives in corpus/human_raw.jsonl,
not invented. Nobody would guess "THE SENATE WAS SUPPOSEDLY THIS AUGUST BODY" or
"Defoe's Friday and the colonial gaze" from an armchair; those came from people.
The human negatives stay the EVALUATION set -- they are never trained on, or
there is nothing left to measure with.
"""

from __future__ import annotations

import random

# --- slot vocabularies -------------------------------------------------------

# Words that are simultaneously a weekday/month and something else. This is the
# whole difficulty of Q1 in one list.
DAY_AS_NAME = ["May", "June", "April", "August", "Sunday", "Monday", "Wednesday"]
DAY_AS_VERB = [("sat", "sits"), ("wed", "weds"), ("march", "marches"),
               ("may", "may"), ("fell", "falls")]
DAY_WORD = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
            "Sunday", "Mon", "Tues", "Wed", "Thurs", "Fri", "Sat", "Sun"]
MONTH_WORD = ["January", "March", "April", "May", "June", "August", "October"]

SURNAME_TITLE = ["Ms.", "Mr.", "Mrs.", "Dr.", "Atty.", "Engr.", "Prof."]
DEPARTMENT = ["Accounts Payable", "HR", "Admissions", "the registrar's office",
              "Procurement", "Legal", "the front desk", "Facilities",
              "the dean's office", "Payroll", "Logistics"]
PLACE = ["the flower stall", "the bakery", "the alley", "the corner unit",
         "the loading bay", "the stockroom", "the pantry", "the annex",
         "the side gate", "the parking deck", "the courtyard", "the pier",
         "the back office", "the supply closet", "the tide pool"]
PERSON = ["Nadine", "Rome", "Mia", "Dez", "Priya", "Bex", "Rook", "Gus",
          "Delaney", "Tasha", "Ledger", "Chum", "Kobe", "Elmer", "Bing"]
THING = ["the corner spot", "the late shift", "the new arrivals", "the deposit",
         "the whole batch", "the returns pile", "the spare key", "the intake form",
         "the seating chart", "the last pallet", "the good scissors"]
ITEM_PL = ["the vintage mirrors", "the ceramic planters", "the reclaimed beams",
           "these linen runners", "the brass hooks", "the seed trays",
           "the display cases", "the rattan stools"]
ITEM_SG = ["chicken breast", "unit 12", "the loose tea", "the corner unit",
           "that walnut sideboard", "the last crate", "the wall clock"]
CARRIABLE = ["the roast pig", "the extra chairs", "a tray of pastries",
             "the projector", "two crates of stock", "the folding tables",
             "the good scissors", "a box of receipts"]
UNIT = ["each", "per kilo", "a month", "a piece", "per box", "a set", "apiece"]
REASON = ["the court is flooded", "she's out sick", "the venue double-booked",
          "the shipment slipped", "power's out in the block", "nobody confirmed",
          "the permit didn't clear", "he's got a work thing",
          "the R/V is in dry dock", "we're short two people"]
CANCEL = ["cancelled", "called off", "postponed indefinitely", "suspended",
          "scratched", "off", "not happening", "pushed back"]
ACK = ["Received, thanks", "got it", "Noted on this", "Copy that", "Acknowledged",
       "sure thing", "sounds good", "will do", "okok", "yep understood"]
ACK_TAIL = ["no notes from me", "I'll loop in the others", "thanks for the heads up",
            "I'll defer to the group on this one", "just ping me",
            "nothing further from my side", "appreciate it"]
SUBJECT = ["the pallet", "the panel", "the crate", "the delivery", "the shipment",
           "the committee", "the paperwork", "the box of samples", "the trolley"]
DURATION_PAST = ["for 2 hrs", "for three hours", "for most of the morning",
                 "for 45 minutes", "for a whole shift", "for 20 minutes"]
FIELD = ["history", "linguistics", "the colonial gaze", "norse mythology",
         "medieval trade", "comparative religion", "maritime law"]
NUMS = ["1066", "1453", "1215", "1789", "4D6", "100 kilos", "34 ppt", "20 arms"]


def _fill(rng: random.Random, template: str) -> str:
    """Replace {SLOT} placeholders until none remain."""
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
# (id, template, weight). Every one is non-schedulable BY CONSTRUCTION.

FRAMES: list[tuple[str, str, float]] = [
    # A weekday/month word used as somebody's given name.
    ("day-as-given-name", "{DAY_AS_NAME} from {PLACE} said {THING} is gone", 3.0),
    ("day-as-given-name", "{DAY_AS_NAME} is bringing {CARRIABLE}, we wont order anymore", 2.0),
    ("day-as-given-name", "ask {DAY_AS_NAME} about {THING} before you reorder", 2.0),
    ("day-as-given-name", "{DAY_AS_NAME} took over {THING} last term", 1.5),

    # ...or as a surname behind a title.
    ("day-as-surname", "Please direct all invoices to {TITLE} {DAY_AS_NAME} in {DEPARTMENT}", 2.5),
    ("day-as-surname", "{TITLE} {DAY_AS_NAME} in {DEPARTMENT} signed off on it already", 2.0),
    ("day-as-surname", "forward the file to {TITLE} {DAY_AS_NAME}, shes handling {THING}", 1.5),

    # A weekday word that is really a verb.
    ("day-as-verb", "{SUBJECT} {VERB} in {PLACE} {DURATION_PAST} before anyone noticed", 3.0),
    ("day-as-verb", "{SUBJECT} {VERB} there {DURATION_PAST} and nobody flagged it", 2.0),
    ("day-as-verb", "they got wed at city hall last week, {N} witnesses only", 1.5),
    ("day-as-verb", "{VERB_CAP} over there fast, we are already late", 1.5),

    # "august body", "a may-be" -- the word as an adjective or common noun.
    ("day-as-modifier", "the senate was supposedly this august body but they were all on the take", 1.0),
    ("day-as-modifier", "you may collect {THING} at window {N} once processing clears", 2.0),
    ("day-as-modifier", "she may drop by {PLACE}, no promises", 1.5),

    # Meta-discussion: the day word is the SUBJECT of the sentence.
    ("day-as-topic", "thursday is literally thor's day, {N} of the 7 are norse gods", 1.5),
    ("day-as-topic", "the lecture covers Defoe's Friday and {FIELD}, {N} sessions on it", 1.5),
    ("day-as-topic", "{MONTH_WORD} is a nice name honestly, better than mine", 1.5),

    # Cancellation: mentions a day, creates nothing.
    ("cancellation", "{CANCEL_CAP} the {DAY_WORD} {THING}, {REASON}", 3.0),
    ("cancellation", "no session {DAY_WORD}, {REASON}", 2.5),
    ("cancellation", "scratch {DAY_WORD}, {PERSON} cant cover", 2.5),
    ("cancellation", "the {DAY_WORD} lecture series is {CANCEL} for the rest of the term", 2.0),
    ("cancellation", "no classes tomorrow, {REASON}", 2.0),
    ("cancellation", "{THING} is {CANCEL} until further notice", 2.0),

    # A question ABOUT when, not a statement scheduling anything.
    ("question-when", "when does {PLACE} open, {N} or {N2}?", 3.0),
    ("question-when", "whens {PERSON} free to look at {THING}?", 2.5),
    ("question-when", "what time is {THING} again, {N} or {N2}?", 2.5),
    ("question-when", "wait when was that, {NUMS} right?", 1.5),
    ("question-when", "does anyone know when {PLACE} closes", 2.0),

    # Numbers that are not times.
    ("number-not-time", "{ITEM_PL} are {N3} {UNIT} and I only have {N} left", 3.0),
    ("number-not-time", "{ITEM_SG} is {N3} {UNIT}, {N3} over what I wanted", 2.0),
    ("number-not-time", "counted {N3} {THING} on one pass, {N} of them damaged", 2.0),
    ("number-not-time", "rolled {NUMS} drop lowest and still got a {N} in con, tragic", 1.0),
    ("number-not-time", "every history exam I ever took wanted {NUMS} and {NUMS}, nothing else", 1.0),

    # Pure acknowledgement, no temporal lookalike at all.
    ("acknowledgement", "{ACK}, {ACK_TAIL}", 3.0),
    ("acknowledgement", "{ACK}", 2.0),
    ("acknowledgement", "{ACK} {PERSON}, {ACK_TAIL}", 1.5),
]

_POOLS: dict[str, list] = {
    "DAY_AS_NAME": DAY_AS_NAME,
    "DAY_WORD": DAY_WORD,
    "MONTH_WORD": MONTH_WORD,
    "TITLE": SURNAME_TITLE,
    "DEPARTMENT": DEPARTMENT,
    "PLACE": PLACE,
    "PERSON": PERSON,
    "THING": THING,
    "ITEM_PL": ITEM_PL,
    "ITEM_SG": ITEM_SG,
    "CARRIABLE": CARRIABLE,
    "UNIT": UNIT,
    "REASON": REASON,
    "CANCEL": CANCEL,
    "CANCEL_CAP": [c.capitalize() for c in CANCEL],
    "ACK": ACK,
    "ACK_TAIL": ACK_TAIL,
    "SUBJECT": SUBJECT,
    "DURATION_PAST": DURATION_PAST,
    "FIELD": FIELD,
    "NUMS": NUMS,
    "VERB": [v[0] for v in DAY_AS_VERB],
    "VERB_CAP": [v[0].upper() for v in DAY_AS_VERB],
    "N": [str(n) for n in range(2, 13)],
    "N2": [str(n) for n in range(2, 13)],
    "N3": [str(n) for n in (24, 40, 100, 220, 240, 400, 1800, 12, 34, 68)],
}

# Frames whose output contains no day/month/number lookalike at all. Everything
# else gets temporal_lookalike, which is the flag that says "this LOOKS
# schedulable to a dumb parser and is not".
_NO_LOOKALIKE = {"acknowledgement"}


def sample(rng: random.Random) -> tuple[str, str, set[str]]:
    """Return (text, frame_id, flags). Label is no_temporal by construction."""
    ids = [f[0] for f in FRAMES]
    tmpl = [f[1] for f in FRAMES]
    wts = [f[2] for f in FRAMES]
    i = rng.choices(range(len(FRAMES)), weights=wts, k=1)[0]
    text = _fill(rng, tmpl[i])
    flags = set() if ids[i] in _NO_LOOKALIKE else {"temporal_lookalike"}
    return text, ids[i], flags


def frame_ids() -> list[str]:
    return sorted({f[0] for f in FRAMES})
