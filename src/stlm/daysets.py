"""Render ANY weekday set into the surface forms people actually write.

The corpus covers 32 of ~119 plausible weekday sets, and the generator was worse
-- 13. Ten weekday pairs and triples (TU,WE / WE,TH / TH,FR / MO,TU,WE ...) never
appear anywhere, so the model would have no way to learn them.

The fix is not more hand-written table entries. It is a renderer that can express
an arbitrary set in every style, so the generator can sample the whole space and
the surface form falls out. This is the meaning-first rule applied to day codes:
sample the SET, then verbalize it.

Round-tripping matters. Every form produced here must parse back to the same set
via normalize._daycodes, and that is asserted in the tests -- otherwise the
generator emits labels its own parser cannot read.
"""

from __future__ import annotations

import random

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

# Single-letter codes. Thursday and Sunday are the collision points: T is
# Tuesday, so Thursday needs Th or R; S is Saturday, so Sunday needs Su or U.
LETTER = {"MO": "M", "TU": "T", "WE": "W", "TH": "Th", "FR": "F", "SA": "S", "SU": "Su"}
LETTER_R = {"MO": "M", "TU": "T", "WE": "W", "TH": "R", "FR": "F", "SA": "S", "SU": "U"}
ABBR3 = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri",
         "SA": "Sat", "SU": "Sun"}
FULL = {"MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday",
        "FR": "Friday", "SA": "Saturday", "SU": "Sunday"}

# Sets with an idiomatic name that beats any compositional rendering.
IDIOM = {
    "MO,TU,WE,TH,FR": ["M-F", "Mon-Fri", "weekdays", "MTWThF", "MTWRF"],
    "SA,SU": ["weekends", "Sat Sun", "Sat/Sun", "SatSun", "S-Su"],
    "MO,TU,WE,TH,FR,SA,SU": ["daily", "every day", "everyday", "M-Su"],
}


def _order(byday: list[str]) -> list[str]:
    return [d for d in WEEKDAYS if d in set(byday)]


def render(byday: list[str], rng: random.Random, style: str | None = None) -> str:
    """Render a weekday set, guaranteeing the result parses back to that set.

    Some style/set pairs are genuinely ambiguous: {MO,FR} as "M-F" collides with
    the Monday-through-Friday range, and {TU,SU} under the R/U convention renders
    as "TU" which reads as Tuesday alone. Rather than enumerate those collisions,
    render then parse back, and fall back to an unambiguous style on mismatch.
    """
    surf = _render_raw(byday, rng, style)
    if surf and _roundtrips(surf, byday):
        return surf
    for fallback in ("abbr3_space", "abbr3_slash", "spaced", "letters", "full"):
        surf = _render_raw(byday, rng, fallback)
        if surf and _roundtrips(surf, byday):
            return surf
    return " ".join(FULL[d] for d in _order(byday))


def _roundtrips(surface: str, byday: list[str]) -> bool:
    from .normalize import _daycodes
    return sorted(_daycodes(surface)) == sorted(_order(byday))


def _render_raw(byday: list[str], rng: random.Random, style: str | None = None) -> str:
    days = _order(byday)
    if not days:
        return ""
    key = ",".join(days)

    if key in IDIOM and rng.random() < 0.6:
        return rng.choice(IDIOM[key])

    styles = ["letters", "letters_r", "slashed", "dashed", "spaced",
              "abbr3", "abbr3_slash", "abbr3_space"]
    if len(days) <= 2:
        styles += ["full", "full_and"]
    style = style or rng.choice(styles)

    if style == "letters":
        return "".join(LETTER[d] for d in days)
    if style == "letters_r":
        return "".join(LETTER_R[d] for d in days)
    if style == "slashed":
        return "/".join(LETTER[d] for d in days)
    if style == "dashed":
        return "-".join(LETTER[d] for d in days)
    if style == "spaced":
        return " ".join(LETTER[d] for d in days)
    if style == "abbr3":
        return "".join(ABBR3[d] for d in days)
    if style == "abbr3_slash":
        return "/".join(ABBR3[d] for d in days)
    if style == "abbr3_space":
        return " ".join(ABBR3[d] for d in days)
    if style == "full":
        return " ".join(FULL[d] for d in days)
    if style == "full_and":
        return " and ".join(FULL[d] for d in days)
    return "".join(LETTER[d] for d in days)


# --- the sampling space ------------------------------------------------------

def _combos(n: int) -> list[list[str]]:
    import itertools
    return [list(c) for c in itertools.combinations(WEEKDAYS, n)]


def plausible_sets() -> list[tuple[list[str], float]]:
    """Every weekday set worth generating, with a sampling weight.

    Weights are shaped, not uniform: MWF and TTh really are far more common than
    TU,SA, and a uniform sample would build a generator whose day distribution is
    nothing like a real timetable. But every set gets nonzero weight, because a
    set that is never generated is a set the model cannot learn.
    """
    common = {
        "MO,WE,FR": 40.0, "TU,TH": 35.0, "MO,WE": 14.0, "TU,TH,SA": 4.0,
        "MO,TU,WE,TH,FR": 12.0, "SA,SU": 8.0, "MO,TU,WE,TH,FR,SA,SU": 6.0,
        "MO,TH": 5.0, "TU,FR": 4.0, "WE,FR": 4.0, "MO,FR": 3.0,
        "MO,WE,TH": 2.5, "TU,WE,TH": 2.5, "MO,TU,TH": 2.0,
    }
    out: list[tuple[list[str], float]] = []
    for n in range(1, 8):
        for c in _combos(n):
            key = ",".join(c)
            if n == 1:
                w = 9.0 if key in ("MO", "TU", "WE", "TH", "FR") else 5.0
            else:
                # Unlisted multi-day sets stay reachable but rare. Without this
                # floor, 10 weekday pairs would never be generated at all.
                w = common.get(key, 0.8 if n <= 3 else 0.35)
            out.append((c, w))
    return out


PLAUSIBLE = plausible_sets()


def sample(rng: random.Random, multi_only: bool = False) -> list[str]:
    pool = [(d, w) for d, w in PLAUSIBLE if not multi_only or len(d) > 1]
    days = [d for d, _ in pool]
    weights = [w for _, w in pool]
    return rng.choices(days, weights=weights, k=1)[0]
