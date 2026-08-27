"""Meaning-first synthetic generator.

Pipeline, per RESEARCH.md section C/D and IR_SPEC_v0:
  1. Sample an axis CELL, then sample a meaning representation (L2) inside it.
     The label is correct BY CONSTRUCTION -- it is never inferred from text.
  2. Verbalize the L2 into a list of (text, span_type) CHUNKS.
  3. Apply label-invariant surface noise to the chunks.
  4. Assemble. Offsets fall out of the assembly, so L1 spans are exact.

Label-CHANGING variation (different times, days, recurrence) happens only in
step 1, by editing the MR and re-verbalizing. Surface text is never perturbed
in a way that could change the label.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field

from . import daysets as ds
from . import negatives as neg
from . import refusals as ref
from . import lexicon as lx
from .ir import L1, L2, DateTimeSpec, L2Event, RRule, Span

# --- axes --------------------------------------------------------------------

AXES = {
    "recurrence_class": [
        "none", "weekly_single", "weekly_multi", "daily",
        "interval", "bounded_until", "bounded_count", "negated",
    ],
    "time_spec": ["none", "start_only", "start_end", "duration", "ambiguous"],
    "date_spec": ["none", "rel_simple", "rel_weekday", "absolute", "month_only"],
    "slot_order": ["temporal_leading", "temporal_trailing", "temporal_split"],
    "register": ["institutional", "informal", "shorthand"],
    "casing": ["lower", "title", "upper", "mixed"],
    "event_count": ["1", "2"],
    "has_person": ["yes", "no"],
    "has_location": ["yes", "no"],
}

# Cells that are semantically impossible, so gap analysis does not flag them.
def cell_is_valid(cell: dict) -> bool:
    if cell["recurrence_class"] == "none" and cell["event_count"] == "2":
        return True  # two one-off events in one string is legal
    if cell["recurrence_class"] != "none" and cell["date_spec"] == "absolute":
        return False  # an absolute date pins a single day; use bounded_* instead
    if cell["time_spec"] == "none" and cell["date_spec"] == "none":
        return False  # nothing temporal at all -> that is the no_temporal class
    if cell["time_spec"] == "duration" and cell["recurrence_class"] == "negated":
        return False
    return True


KEY_PAIRS = [
    ("recurrence_class", "register"),
    ("recurrence_class", "time_spec"),
    ("recurrence_class", "casing"),
    ("time_spec", "register"),
    ("date_spec", "register"),
    ("event_count", "recurrence_class"),
]

# ---------------------------------------------------------------------------
# Two sampling profiles, because COVERAGE and REALISM are different jobs.
#
#   balanced  -- uniform over axis values. Guarantees every rare class (INTERVAL,
#                COUNT, UNTIL, negation) is represented often enough to learn.
#                RESEARCH.md explicitly calls for this. Its marginal distribution
#                is NOT realistic and is not meant to be.
#   realistic -- sampled from AXIS_PRIOR below, meant to approximate how often
#                each construction actually occurs.
#
# !! AXIS_PRIOR IS A GUESS. !! It is the author's prior, not a measurement. It
# gets recalibrated from corpus/harvested.jsonl and then from the human gold
# corpus. Until then, every number derived from the realistic pool inherits this
# guess and must be reported as such.
# ---------------------------------------------------------------------------

# Rev 2, partially recalibrated against corpus/harvested.jsonl (610 real strings,
# 305 of them target-like). Values marked [H] are anchored to a measured harvest
# rate; the rest are still guesses. The harvest is itself biased -- parser test
# suites over-represent absolute dates because that is what they test, and forum
# posts under-represent named attendees -- so [H] means "evidence-informed", not
# "measured on the target distribution". The human 500 replaces all of this.
AXIS_PRIOR: dict[str, list[tuple[str, float]]] = {
    "recurrence_class": [
        ("none", 35.0), ("weekly_multi", 23.0), ("weekly_single", 21.0),
        ("daily", 8.0), ("interval", 6.0),
        ("bounded_until", 4.0),   # [H] harvest 2.6%
        ("bounded_count", 1.5),   # [H] harvest 0.0% target-like, 0.5% overall
        ("negated", 1.5),         # [H] harvest 0.33%
    ],
    "time_spec": [
        ("start_only", 35.0), ("start_end", 25.0), ("none", 14.0),
        ("ambiguous", 25.0),      # [H] harvest 25.9% bare hour, no meridiem
        ("duration", 1.0),        # [H] harvest 0.98%
    ],
    "date_spec": [
        ("none", 52.0), ("rel_simple", 16.0), ("rel_weekday", 14.0),
        ("absolute", 12.0),       # [H] harvest 24.6% month+day, discounted for bias
        ("month_only", 6.0),      # [H] harvest 28.5% month name, heavily discounted
    ],
    "slot_order": [
        ("temporal_leading", 55.0), ("temporal_trailing", 35.0), ("temporal_split", 10.0),
    ],
    "register": [("informal", 45.0), ("shorthand", 35.0), ("institutional", 20.0)],
    # [H] harvest: 40.7% title-ish, 35.4% all-lower, 21.0% mixed, 1.0% all-upper.
    # Kept upper slightly above the harvest rate: forum/test-suite text is not
    # phone-typed, and all-caps is a real mobile pattern the harvest cannot see.
    "casing": [("lower", 36.0), ("title", 36.0), ("mixed", 22.0), ("upper", 6.0)],
    "event_count": [("1", 85.0), ("2", 15.0)],  # [H] harvest 17.7% multi-sep
    "has_person": [("no", 70.0), ("yes", 30.0)],
    "has_location": [("no", 82.0), ("yes", 18.0)],  # [H] harvest 3.6% marker, but
    # the harvest register would not carry attendees or rooms; the user's own six
    # examples all do. Deliberately NOT recalibrated down. See OQ-2 / OQ-3.
}


# --- weighted choice ---------------------------------------------------------


def wchoice(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    items = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return rng.choices(items, weights=weights, k=1)[0]


# --- chunks ------------------------------------------------------------------


@dataclass
class Chunk:
    text: str
    span_type: str | None = None
    events: list[int] = field(default_factory=list)
    noisable: bool = True


def assemble(chunks: list[Chunk]) -> tuple[str, list[Span], list[list[int]]]:
    """Concatenate chunks and derive exact span offsets and event groups."""
    parts: list[str] = []
    spans: list[Span] = []
    pos = 0
    i = 0
    groups: dict[int, list[int]] = {}
    for c in chunks:
        if not c.text:
            continue
        start = pos
        parts.append(c.text)
        pos += len(c.text)
        if c.span_type:
            spans.append(Span(i=i, type=c.span_type, start=start, end=pos, text=c.text))
            for ev in c.events:
                groups.setdefault(ev, []).append(i)
            i += 1
    text = "".join(parts)
    event_groups = [sorted(groups[k]) for k in sorted(groups)]
    return text, spans, event_groups


# --- noise -------------------------------------------------------------------

_KEYBOARD = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr", "f": "drtgvc",
    "g": "ftyhbv", "h": "gyujnb", "i": "ujko", "j": "huikmn", "k": "jiolm", "l": "kop",
    "m": "njk", "n": "bhjm", "o": "iklp", "p": "ol", "q": "wa", "r": "edft",
    "s": "awedxz", "t": "rfgy", "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc",
    "y": "tghu", "z": "asx", "0": "9", "1": "2", "2": "13", "3": "24", "4": "35",
    "5": "46", "6": "57", "7": "68", "8": "79", "9": "80",
}


def typo(rng: random.Random, s: str) -> str:
    if len(s) < 2:
        return s
    op = rng.choice(["adjacent", "swap", "drop", "double"])
    i = rng.randrange(len(s))
    ch = s[i].lower()
    if op == "adjacent" and ch in _KEYBOARD:
        rep = rng.choice(_KEYBOARD[ch])
        return s[:i] + (rep.upper() if s[i].isupper() else rep) + s[i + 1 :]
    if op == "swap" and i < len(s) - 1:
        return s[:i] + s[i + 1] + s[i] + s[i + 2 :]
    if op == "drop":
        return s[:i] + s[i + 1 :]
    if op == "double":
        return s[:i] + s[i] + s[i:]
    return s


def apply_casing(rng: random.Random, s: str, mode: str) -> str:
    if mode == "lower":
        return s.lower()
    if mode == "upper":
        return s.upper()
    if mode == "title":
        return s
    # mixed: randomly recase word-initial letters
    out = []
    for w in s.split(" "):
        if w and rng.random() < 0.4:
            out.append(w.lower() if w[:1].isupper() else w.capitalize())
        else:
            out.append(w)
    return " ".join(out)


# Asymmetric error cost (RESEARCH.md): a mangled SUMMARY is cosmetic, a mangled
# time or weekday is a missed class. So temporal spans get much less typo noise
# than free-text spans -- the model still sees noise there, just not enough to
# swamp the signal on the slots that actually matter.
_TYPO_SCALE = {
    "TSTART": 0.35, "TEND": 0.35, "RECUR": 0.4, "DATE": 0.5, "BOUND": 0.5,
    "DURATION": 0.5, "SUMMARY": 1.0, "PERSON": 1.0, None: 0.2,
}


def _can_join(prev: str, nxt: str) -> bool:
    """Is deleting the space between these two safe/realistic?

    Real shorthand collapses across a letter/digit boundary ("mwf8-12nn") but
    almost never across two letters ("at the cafelater today"), which just reads
    as a different word and injects noise the label cannot justify.
    """
    if not prev or not nxt:
        return True
    a, b = prev[-1], nxt[0]
    if a.isalpha() and b.isalpha():
        return False
    if a.isdigit() and b.isdigit():
        return False
    return True


def noise_chunks(rng: random.Random, chunks: list[Chunk], cell: dict, p_typo: float) -> list[Chunk]:
    """Label-invariant surface noise. Never changes which canonical value a chunk means."""
    out = []
    for c in chunks:
        t = c.text
        if c.noisable and t.strip():
            t = apply_casing(rng, t, cell["casing"])
            if rng.random() < p_typo * _TYPO_SCALE.get(c.span_type, 1.0):
                t = typo(rng, t)
        out.append(Chunk(t, c.span_type, c.events, c.noisable))

    # Boundary noise: collapse or duplicate separator whitespace, but only where
    # the collapse produces something a human would actually type.
    p_collapse = {"institutional": 0.0, "informal": 0.18, "shorthand": 0.40}[cell["register"]]
    for i, c in enumerate(out):
        if c.span_type is not None or c.text != " ":
            continue
        prev = next((out[j].text for j in range(i - 1, -1, -1) if out[j].text), "")
        nxt = next((out[j].text for j in range(i + 1, len(out)) if out[j].text), "")
        if rng.random() < p_collapse and _can_join(prev, nxt):
            c.text = ""
        elif rng.random() < 0.05:
            c.text = "  "

    # A typo can leave a LABELLED chunk with edge whitespace ("Lab 3" -> "lab ").
    # The caller's final strip() would then desync that span from the text, so
    # normalise here: labelled chunks carry no edge whitespace, and any that
    # existed becomes a separate unlabelled filler chunk.
    cleaned: list[Chunk] = []
    for c in out:
        if c.span_type is None or c.text == c.text.strip():
            cleaned.append(c)
            continue
        core = c.text.strip()
        if not core:
            cleaned.append(Chunk(c.text, None))
            continue
        lead_ws = c.text[: len(c.text) - len(c.text.lstrip())]
        trail_ws = c.text[len(c.text.rstrip()) :]
        if lead_ws:
            cleaned.append(Chunk(lead_ws, None))
        cleaned.append(Chunk(core, c.span_type, c.events, c.noisable))
        if trail_ws:
            cleaned.append(Chunk(trail_ws, None))
    return cleaned


# --- MR sampling + verbalization --------------------------------------------

BYDAY_SETS_MULTI = ["MO,WE,FR", "TU,TH", "MO,WE", "TU,TH,SA", "MO,TU,WE,TH,FR", "SA,SU"]
BYDAY_SETS_SINGLE = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
COMMON_TIMES = [
    "07:00", "07:30", "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
    "11:00", "11:30", "12:00", "13:00", "13:30", "14:00", "15:00", "15:30",
    "16:00", "17:00", "17:30", "18:00", "19:00", "20:00",
]


def _summary_text(rng: random.Random, cell: dict) -> str:
    r = rng.random()
    if cell["register"] == "institutional" or r < 0.4:
        code = f"{rng.choice(lx.SUBJECT_PREFIXES)}{rng.randrange(100, 500)}"
        if rng.random() < 0.35:
            return f"{code} {rng.choice(lx.EVENT_NOUNS)}"
        return code
    if r < 0.7:
        return rng.choice(lx.ACTIVITIES)
    return rng.choice(lx.EVENT_NOUNS)


def _person_text(rng: random.Random) -> str:
    name = rng.choice(lx.FIRST_NAMES)
    if rng.random() < 0.55:
        return f"{rng.choice(lx.HONORIFICS)} {name}"
    return name


def _time_pair(rng: random.Random, cell: dict) -> tuple[str, str | None]:
    start = rng.choice(COMMON_TIMES)
    if cell["time_spec"] != "start_end":
        return start, None
    sh = int(start[:2])
    dur = rng.choice([1, 1, 1, 2, 2, 3, 4])
    eh = min(sh + dur, 23)
    end = f"{eh:02d}:{start[3:]}"
    return start, end


def _render_time(rng: random.Random, canon: str, cell: dict, force_bare: bool) -> str:
    surfaces = lx.TIMES.get(canon)
    if not surfaces:
        return canon
    if force_bare:
        h24 = int(canon[:2])
        h12 = h24 % 12 or 12
        if canon.endswith(":00"):
            return str(h12)
        return f"{h12}:{canon[3:]}"
    if cell["register"] == "institutional":
        pref = [s for s in surfaces if ":" in s[0] or s[0].isdigit()]
        if pref:
            return wchoice(rng, pref)
    return wchoice(rng, surfaces)


def _make_rrule(rng: random.Random, cell: dict) -> tuple[RRule | None, list[str]]:
    rc = cell["recurrence_class"]
    flags: list[str] = []
    if rc == "none":
        return None, flags
    if rc == "weekly_single":
        return RRule(freq="WEEKLY", byday=ds.sample(rng)), flags
    if rc == "weekly_multi":
        return RRule(freq="WEEKLY", byday=ds.sample(rng, multi_only=True)), flags
    if rc == "daily":
        return RRule(freq="DAILY"), flags
    if rc == "interval":
        return RRule(
            freq="WEEKLY", interval=rng.choice([2, 2, 2, 3]),
            byday=ds.sample(rng),
        ), flags
    if rc == "bounded_until":
        m = rng.randrange(1, 13)
        flags.append("bounded_until")
        return RRule(
            freq="WEEKLY", byday=ds.sample(rng, multi_only=True),
            until=f"REL:MONTH_{m}",  # symbolic: "the next <month>", never a fixed year
        ), flags
    if rc == "bounded_count":
        flags.append("bounded_count")
        return RRule(
            freq="WEEKLY", byday=ds.sample(rng),
            count=rng.choice([4, 5, 6, 8, 10, 12]),
        ), flags
    if rc == "negated":
        excluded = rng.choice(["FR", "WE", "MO"])
        keep = [d for d in ["MO", "TU", "WE", "TH", "FR"] if d != excluded]
        flags.append("negated_recurrence")
        return RRule(freq="WEEKLY", byday=keep), flags
    return None, flags


def _render_recur(rng: random.Random, rr: RRule, cell: dict) -> str:
    rc = cell["recurrence_class"]
    if rc == "daily":
        return wchoice(rng, [("daily", 4.0), ("every day", 4.0), ("everyday", 2.0), ("M-F", 1.0)])
    if rc == "negated":
        base = wchoice(rng, [("every day", 3.0), ("daily", 2.0), ("M-F", 1.0)])
        excluded = [d for d in ["MO", "TU", "WE", "TH", "FR"] if d not in rr.byday]
        name = lx._DAY_NAMES.get(excluded[0], "Friday") if excluded else "Friday"
        neg = wchoice(rng, lx.NEGATION).format(name)
        return f"{base} {neg}"
    # Render the set compositionally. The old lookup only knew 13 sets and fell
    # back to emitting the raw "MO,WE" key as surface text for anything else.
    day_txt = ds.render(rr.byday, rng)
    if rc == "interval":
        iv = wchoice(rng, lx.INTERVAL_PHRASES.get(rr.interval, [("every other", 1.0)]))
        return f"{iv} {day_txt}"
    prefix = wchoice(rng, lx.RECUR_PREFIXES) if cell["register"] != "institutional" else ""
    return f"{prefix}{day_txt}"


def _render_until(rng: random.Random, until: str) -> str:
    month = int(until[len("REL:MONTH_") :]) if until.startswith("REL:MONTH_") else int(until.split("-")[1])
    mtxt = wchoice(rng, lx.MONTH_SURFACES[month])
    return wchoice(rng, lx.BOUND_UNTIL).format(mtxt)


def _render_count(rng: random.Random, count: int) -> str:
    return wchoice(rng, lx.BOUND_COUNT).format(count)


def sample_cell(rng: random.Random, profile: str = "balanced") -> dict:
    for _ in range(200):
        if profile == "realistic":
            cell = {k: wchoice(rng, AXIS_PRIOR[k]) for k in AXES}
        else:
            cell = {k: rng.choice(v) for k, v in AXES.items()}
        if cell_is_valid(cell):
            return cell
    # Fall back to a known-valid cell rather than looping forever.
    return {
        "recurrence_class": "weekly_multi", "time_spec": "start_end", "date_spec": "none",
        "slot_order": "temporal_leading", "register": "informal", "casing": "lower",
        "event_count": "1", "has_person": "no", "has_location": "no",
    }


def generate_one(rng: random.Random, idx: int, cell: dict | None = None,
                 profile: str = "balanced") -> tuple[L1, L2, dict]:
    cell = cell or sample_cell(rng, profile)
    flags: list[str] = []
    n_events = int(cell["event_count"])

    # --- meaning first -------------------------------------------------------
    rr, rflags = _make_rrule(rng, cell)
    flags += rflags
    summary = _summary_text(rng, cell)
    person = _person_text(rng) if cell["has_person"] == "yes" else None
    location = rng.choice(lx.LOCATIONS) if cell["has_location"] == "yes" else None

    ambiguous = cell["time_spec"] == "ambiguous"
    has_time = cell["time_spec"] != "none"
    tstart, tend = (None, None)
    duration = None
    if has_time:
        tstart, tend = _time_pair(rng, cell)
        if cell["time_spec"] == "duration":
            duration = rng.choice([30, 45, 60, 90, 120, 180])
            flags.append("duration_given")
    if ambiguous:
        # Bare hour, no meridiem. Policy: resolve toward the plausible daytime
        # reading -- 7..12 stay as written, 1..6 become PM. This mirrors
        # chrono-node's PM-guessing refiner. The POLICY lives here in code, and
        # the model never learns date/time arithmetic. See OQ-5.
        h12 = rng.randrange(1, 13)
        h24 = h12 if 7 <= h12 <= 12 else h12 + 12
        tstart = f"{h24:02d}:00"
        tend = None
        flags += ["ampm_ambiguous", "ampm_inferred"]

    date_sym = None
    if cell["date_spec"] == "rel_simple":
        date_sym = rng.choice(["REL:TODAY", "REL:TOMORROW", "REL:DAY_AFTER_TOMORROW"])
        flags.append("relative_date")
    elif cell["date_spec"] == "rel_weekday":
        d = rng.choice(["MO", "TU", "WE", "TH", "FR", "SA", "SU"])
        date_sym = rng.choice([f"REL:THIS_{d}", f"REL:NEXT_{d}"])
        flags.append("relative_date")
    elif cell["date_spec"] == "absolute":
        date_sym = f"ABS:2026-{rng.randrange(1,13):02d}-{rng.randrange(1,29):02d}"
    elif cell["date_spec"] == "month_only":
        date_sym = f"ABS:2026-{rng.randrange(1,13):02d}-01"

    # "every MWF starting next week" is real but uncommon. Without this gate it
    # fires on every (recurrence x relative-date) cell intersection, which pushes
    # it to ~20% of the corpus -- far above any plausible real rate.
    if (rr is not None and date_sym and date_sym.startswith("REL:")
            and date_sym != "REL:NEXT_OCCURRENCE" and rng.random() > 0.22):
        date_sym = None
        flags = [f for f in flags if f != "relative_date"]

    if rr is not None and date_sym is None:
        date_sym = "REL:NEXT_OCCURRENCE"
    if not has_time:
        flags.append("all_day")
    if cell["time_spec"] == "start_only":
        flags.append("missing_end_time")
    if date_sym is None and rr is None:
        date_sym = "REL:TODAY"
        flags.append("missing_date")
    if n_events > 1:
        flags.append("multi_event")

    # --- build L2 ------------------------------------------------------------
    events: list[L2Event] = []
    per_event_times: list[str] = []
    for e in range(n_events):
        if n_events > 1 and rr is not None:
            # RFC 5545 cannot pair weekday->time in one RRULE, so split.
            # The split surface form ("mon 12, wed 5") carries no interval or
            # bound, so the per-event rule must not claim one either -- otherwise
            # the label asserts something the text never says and the example is
            # unlearnable.
            days = rr.byday or ["MO"]
            d = days[e % len(days)]
            e_rr = RRule(freq=rr.freq, interval=1, byday=[d])
        else:
            e_rr = rr
        e_time = tstart
        if n_events > 1 and has_time and e:
            base = COMMON_TIMES.index(tstart) if tstart in COMMON_TIMES else 0
            e_time = COMMON_TIMES[(base + 5 * e) % len(COMMON_TIMES)]
        per_event_times.append(e_time)
        full_summary = summary + (f" with {person}" if person else "")
        events.append(
            L2Event(
                summary=full_summary or None,
                dtstart=DateTimeSpec(date=date_sym, time=e_time),
                dtend=DateTimeSpec(time=tend) if tend and n_events == 1 else None,
                duration_minutes=duration,
                rrule=e_rr,
                attendees=[person] if person else [],
            )
        )

    # --- verbalize -----------------------------------------------------------
    force_bare = ambiguous
    temporal: list[Chunk] = []
    if n_events > 1 and rr is not None:
        for e in range(n_events):
            days = rr.byday or ["MO"]
            d = days[e % len(days)]
            temporal.append(Chunk(ds.render([d], rng), "RECUR", [e]))
            if has_time:
                temporal.append(Chunk(" ", None))
                temporal.append(
                    Chunk(_render_time(rng, per_event_times[e], cell, force_bare), "TSTART", [e])
                )
            if e < n_events - 1:
                temporal.append(Chunk(", " if rng.random() < 0.6 else " ", None))
    else:
        if rr is not None:
            temporal.append(Chunk(_render_recur(rng, rr, cell), "RECUR", [0]))
        if date_sym and date_sym.startswith("REL:") and date_sym != "REL:NEXT_OCCURRENCE":
            surfaces = lx.REL_DATES.get(date_sym)
            if surfaces:
                if rr is not None:
                    # A recurrence plus a relative anchor only reads coherently as
                    # "every X starting <date>". This is exactly the OQ-6 pattern,
                    # so emit it deliberately and flag it rather than gluing a bare
                    # date onto a recurrence and producing nonsense.
                    lead = wchoice(rng, [("starting ", 5.0), ("start ", 2.0),
                                         ("from ", 2.0), ("beginning ", 1.0)])
                    temporal.append(Chunk(" ", None))
                    temporal.append(Chunk(lead, None))
                    temporal.append(Chunk(wchoice(rng, surfaces), "DATE", [0]))
                    flags.append("recur_with_anchor")
                else:
                    if temporal:
                        temporal.append(Chunk(" ", None))
                    temporal.append(Chunk(wchoice(rng, surfaces), "DATE", [0]))
        if has_time:
            if temporal:
                temporal.append(Chunk(" ", None))
            temporal.append(Chunk(_render_time(rng, tstart, cell, force_bare), "TSTART", [0]))
            if tend:
                sep = wchoice(rng, lx.RANGE_SEPS)
                temporal.append(Chunk(sep if sep.strip() != sep else f" {sep} ", None))
                temporal.append(Chunk(_render_time(rng, tend, cell, force_bare), "TEND", [0]))
            if duration:
                temporal.append(Chunk(" ", None))
                unit = "mins" if duration < 120 else "hrs"
                val = duration if duration < 120 else duration // 60
                temporal.append(Chunk(f"for {val} {unit}", "DURATION", [0]))
        if rr is not None and rr.until:
            temporal.append(Chunk(" ", None))
            temporal.append(Chunk(_render_until(rng, rr.until), "BOUND", [0]))
        if rr is not None and rr.count:
            temporal.append(Chunk(" ", None))
            temporal.append(Chunk(_render_count(rng, rr.count), "BOUND", [0]))

    all_ev = list(range(n_events))
    content: list[Chunk] = [Chunk(summary, "SUMMARY", all_ev)]
    if person:
        content.append(Chunk(" with ", None))
        content.append(Chunk(person, "PERSON", all_ev))
    if location:
        content.append(Chunk(" @ " if rng.random() < 0.5 else " at ", None))
        content.append(Chunk(location, "SUMMARY", all_ev))

    order = cell["slot_order"]
    if order == "temporal_leading":
        chunks = temporal + [Chunk(" ", None)] + content
    elif order == "temporal_trailing":
        chunks = content + [Chunk(" ", None)] + temporal
    else:
        mid = max(1, len(temporal) // 2)
        chunks = temporal[:mid] + [Chunk(" ", None)] + content + [Chunk(" ", None)] + temporal[mid:]

    p_typo = {"institutional": 0.02, "informal": 0.12, "shorthand": 0.18}[cell["register"]]
    chunks = noise_chunks(rng, chunks, cell, p_typo)
    raw, spans, groups = assemble(chunks)
    # Stripping leading whitespace shifts every offset; do it explicitly rather
    # than letting str.strip() silently desync the spans from the text.
    lead = len(raw) - len(raw.lstrip())
    if lead:
        spans = [Span(s.i, s.type, s.start - lead, s.end - lead, s.text) for s in spans]
    text = raw.strip()

    if not summary:
        flags.append("missing_summary")
    flags = sorted(set(f for f in flags if f))

    l1 = L1(id=f"syn{idx:06d}", text=text, spans=spans, event_groups=groups,
            status="ok", flags=flags)
    l2 = L2(id=f"syn{idx:06d}", events=events, status="ok", flags=flags)
    return l1, l2, cell


def generate_negative(rng: random.Random, idx: int) -> tuple[L1, L2, dict]:
    """A NOT-A-SCHEDULE example, sampled compositionally from negatives.py.

    Was a pick from 25 hand-written strings, which gave 24 distinct negatives no
    matter how many rows were generated. Now the FRAME is sampled -- the reason
    the string is not a schedule -- and filled from slot vocabularies, the same
    meaning-first discipline used for positives.
    """
    text, frame, flags = neg.sample(rng)
    casing = rng.choice(["lower", "title", "mixed", "upper"])
    text = apply_casing(rng, text, casing)
    if rng.random() < 0.10:
        text = typo(rng, text)

    cell = {k: "n/a" for k in AXES}
    cell["recurrence_class"] = "none"
    cell["register"] = "informal"
    cell["casing"] = casing
    cell["negative_frame"] = frame

    # Non-temporal text is still the title -- see OQ-14. A rejected string keeps
    # its words so a UI can show what it declined to schedule.
    spans = [Span(i=0, type="SUMMARY", start=0, end=len(text), text=text)]
    l1 = L1(id=f"neg{idx:06d}", text=text, spans=spans, event_groups=[],
            status="no_temporal", flags=sorted(flags))
    l2 = L2(id=f"neg{idx:06d}", events=[], status="no_temporal", flags=sorted(flags))
    return l1, l2, cell


def generate_refusal(rng: random.Random, idx: int) -> tuple[L1, L2, dict]:
    """A string the system must REFUSE rather than guess, from refusals.py.

    Covers the two statuses the generator used to emit zero of. Without these,
    2 of the 4 classes Q1 is scored on have no training signal at all, and the
    model can only ever learn to answer schedulable-or-not.

    Same L1 shape as a negative: the words are still the title, so a UI can show
    what it declined to schedule. What differs is the status, and the status is
    correct by construction because the FRAME decided it.
    """
    text, status, family, flags = ref.sample(rng)
    casing = rng.choice(["lower", "title", "mixed", "upper"])
    text = apply_casing(rng, text, casing)
    if rng.random() < 0.10:
        text = typo(rng, text)

    cell = {k: "n/a" for k in AXES}
    cell["register"] = "informal"
    cell["casing"] = casing
    cell["refusal_family"] = family

    spans = [Span(i=0, type="SUMMARY", start=0, end=len(text), text=text)]
    l1 = L1(id=f"ref{idx:06d}", text=text, spans=spans, event_groups=[],
            status=status, flags=sorted(flags))
    l2 = L2(id=f"ref{idx:06d}", events=[], status=status, flags=sorted(flags))
    return l1, l2, cell


# Negatives follow the same balanced-vs-realistic split as the axes. The measured
# rate in the human corpus is 13.6% (42 no_temporal of 309). Training Q1 wants
# more than that; calibration wants the real figure.
NEGATIVE_FRAC = {"balanced": 0.25, "realistic": 0.136}

# Refusals, same reasoning. The measured rate is 6.9% (28 of 407 gold rows);
# balanced roughly doubles it so the two rarest classes are learnable.
REFUSAL_FRAC = {"balanced": 0.14, "realistic": 0.069}


def generate(n: int, seed: int = 1337, negative_frac: float | None = None,
             profile: str = "balanced",
             refusal_frac: float | None = None) -> list[dict]:
    """profile: "balanced" (uniform axes, for class coverage) or
    "realistic" (AXIS_PRIOR, for distribution calibration). See AXIS_PRIOR."""
    rng = random.Random(seed)
    rows = []
    if negative_frac is None:
        negative_frac = NEGATIVE_FRAC.get(profile, 0.136)
    if refusal_frac is None:
        refusal_frac = REFUSAL_FRAC.get(profile, 0.069)
    n_neg = int(n * negative_frac)
    n_ref = int(n * refusal_frac)
    for i in range(n - n_neg - n_ref):
        l1, l2, cell = generate_one(rng, i, profile=profile)
        rows.append({"l1": l1.to_json(), "l2": l2.to_json(), "cell": cell,
                     "source": "synthetic", "profile": profile})
    for i in range(n_neg):
        l1, l2, cell = generate_negative(rng, i)
        rows.append({"l1": l1.to_json(), "l2": l2.to_json(), "cell": cell,
                     "source": "synthetic", "profile": profile})
    for i in range(n_ref):
        l1, l2, cell = generate_refusal(rng, i)
        rows.append({"l1": l1.to_json(), "l2": l2.to_json(), "cell": cell,
                     "source": "synthetic", "profile": profile})
    rng.shuffle(rows)
    return rows
