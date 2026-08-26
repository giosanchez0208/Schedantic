"""M0 fixtures + M2 converter + M3 scorer tests.

Run:  uv run --with python-dateutil --with icalendar python tests/test_core.py
"""

from __future__ import annotations

import datetime as dt
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stlm.convert import (DEFAULT_POLICY, Policy, l2_to_jcal, occurrence_set,
                          occurrences, resolve_date)
from stlm.generate import generate
from stlm.ir import L1, L2, DateTimeSpec, L2Event, RRule
from stlm.score import rrule_equivalence, span_prf, l2_exact_match

# Fixed reference time for every test. 2026-08-26 is a Wednesday.
REF = dt.datetime(2026, 8, 26, 9, 0, 0)
assert REF.weekday() == 2, "REF must be a Wednesday for these fixtures"

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def ev(**kw) -> L2Event:
    kw.setdefault("dtstart", DateTimeSpec())
    return L2Event(**kw)


# --- M0: the six worked examples, hand-mapped -------------------------------

FIXTURES = {
    "MWF 8-12NN CCC100 with Sir Jefferson": L2(
        id="f1",
        events=[ev(summary="CCC100 with Sir Jefferson",
                   dtstart=DateTimeSpec(date="REL:NEXT_OCCURRENCE", time="08:00"),
                   dtend=DateTimeSpec(time="12:00"),
                   rrule=RRule(freq="WEEKLY", byday=["MO", "WE", "FR"]),
                   attendees=["Sir Jefferson"])],
        flags=["ampm_inferred"]),
    "TTh 5pm Meeting with Boss": L2(
        id="f2",
        events=[ev(summary="Meeting with Boss",
                   dtstart=DateTimeSpec(date="REL:NEXT_OCCURRENCE", time="17:00"),
                   rrule=RRule(freq="WEEKLY", byday=["TU", "TH"]),
                   attendees=["Boss"])],
        flags=["missing_end_time"]),
    "MW 8am": L2(
        id="f3",
        events=[ev(dtstart=DateTimeSpec(date="REL:NEXT_OCCURRENCE", time="08:00"),
                   rrule=RRule(freq="WEEKLY", byday=["MO", "WE"]))],
        flags=["missing_end_time", "missing_summary"]),
    "every other Tuesday until December": L2(
        id="f4",
        events=[ev(dtstart=DateTimeSpec(date="REL:NEXT_OCCURRENCE"),
                   rrule=RRule(freq="WEEKLY", interval=2, byday=["TU"],
                               until="REL:MONTH_12"))],
        flags=["bounded_until", "missing_summary", "all_day"]),
    "Tomorrow go swimming with kyle": L2(
        id="f5",
        events=[ev(summary="go swimming with kyle",
                   dtstart=DateTimeSpec(date="REL:TOMORROW"),
                   attendees=["kyle"])],
        flags=["relative_date", "all_day"]),
    "Ballet Class This Monday": L2(
        id="f6",
        events=[ev(summary="Ballet Class", dtstart=DateTimeSpec(date="REL:THIS_MO"))],
        flags=["relative_date", "all_day"]),
    "Monday 12pm, Wednesday 5pm Laboratory with Sir Jeff": L2(
        id="f7",
        events=[
            ev(summary="Laboratory with Sir Jeff",
               dtstart=DateTimeSpec(date="REL:NEXT_OCCURRENCE", time="12:00"),
               rrule=RRule(freq="WEEKLY", byday=["MO"]), attendees=["Sir Jeff"]),
            ev(summary="Laboratory with Sir Jeff",
               dtstart=DateTimeSpec(date="REL:NEXT_OCCURRENCE", time="17:00"),
               rrule=RRule(freq="WEEKLY", byday=["WE"]), attendees=["Sir Jeff"]),
        ],
        flags=["multi_event", "missing_end_time"]),
}


def test_fixtures_valid():
    print("\n[M0] fixture validity")
    for text, l2 in FIXTURES.items():
        errs = l2.validate()
        check(f"L2 valid: {text[:40]!r}", not errs, str(errs))


def test_jcal_emission():
    print("\n[M2] jCal emission")
    for text, l2 in FIXTURES.items():
        jc = l2_to_jcal(l2, REF, tzid="Asia/Manila")
        ok = (isinstance(jc, list) and len(jc) == 3 and jc[0] == "vcalendar"
              and len(jc[2]) == len(l2.events))
        check(f"jCal shape: {text[:36]!r}", ok, repr(jc)[:120])
    jc = l2_to_jcal(FIXTURES["MWF 8-12NN CCC100 with Sir Jefferson"], REF)
    vevent = jc[2][0]
    props = {p[0]: p for p in vevent[1]}
    check("rrule is a recur-typed object", props["rrule"][2] == "recur",
          str(props.get("rrule")))
    check("rrule keys lowercase per RFC 7265",
          all(k.islower() for k in props["rrule"][3]), str(props["rrule"][3]))
    check("byday preserved", props["rrule"][3].get("byday") == ["MO", "WE", "FR"],
          str(props["rrule"][3]))
    check("dtstart is 08:00 on a MWF day",
          props["dtstart"][3].endswith("T08:00:00"), props["dtstart"][3])


def test_date_resolution():
    print("\n[M2] symbolic date resolution (REF = Wed 2026-08-26)")
    cases = [
        ("REL:TODAY", dt.date(2026, 8, 26)),
        ("REL:TOMORROW", dt.date(2026, 8, 27)),
        ("REL:DAY_AFTER_TOMORROW", dt.date(2026, 8, 28)),
        ("REL:THIS_MO", dt.date(2026, 8, 31)),   # next Monday forward
        ("REL:THIS_FR", dt.date(2026, 8, 28)),
        ("ABS:2026-09-03", dt.date(2026, 9, 3)),
        ("REL:MONTH_12", dt.date(2026, 12, 1)),  # "until December" -> next December
        ("REL:MONTH_3", dt.date(2027, 3, 1)),    # March already passed -> next year
    ]
    for sym, want in cases:
        got = resolve_date(sym, REF)
        check(f"{sym} -> {want}", got == want, f"got {got}")

    # "next Monday" issued on a Wednesday is GENUINELY AMBIGUOUS in English:
    # the coming Monday (Aug 31) or the Monday of next week (Sep 7)? Parsers
    # disagree. We do not assert one reading is correct -- we assert the policy
    # knob actually controls it, and record the choice. See OQ-13.
    coming = resolve_date("REL:NEXT_MO", REF, policy=Policy(next_weekday_min_offset=1))
    weekafter = resolve_date("REL:NEXT_MO", REF, policy=Policy(next_weekday_min_offset=7))
    check("NEXT_MO, policy=coming-occurrence -> Aug 31", coming == dt.date(2026, 8, 31), str(coming))
    check("NEXT_MO, policy=next-week -> Sep 7", weekafter == dt.date(2026, 9, 7), str(weekafter))
    check("the two policies genuinely differ", coming != weekafter, "policy knob is inert")

    # "this Wednesday" issued ON a Wednesday: the documented ambiguity.
    inc = resolve_date("REL:THIS_WE", REF, policy=Policy(this_weekday_includes_today=True))
    exc = resolve_date("REL:THIS_WE", REF, policy=Policy(this_weekday_includes_today=False))
    check("THIS_WE on a Wednesday, policy=include -> today", inc == dt.date(2026, 8, 26), str(inc))
    check("THIS_WE on a Wednesday, policy=exclude -> +7", exc == dt.date(2026, 9, 2), str(exc))

    nxt = resolve_date("REL:NEXT_OCCURRENCE", REF,
                       RRule(freq="WEEKLY", byday=["MO", "WE", "FR"]))
    check("NEXT_OCCURRENCE of MWF from Wed -> that Wed", nxt == dt.date(2026, 8, 26), str(nxt))


def test_rrule_equivalence_not_string_equality():
    print("\n[M3] RRULE equivalence is semantic, not textual")
    base = L2(id="a", events=[ev(dtstart=DateTimeSpec(date="ABS:2026-08-31", time="08:00"),
                                 rrule=RRule(freq="WEEKLY", byday=["MO", "WE"]))])
    reordered = L2(id="b", events=[ev(dtstart=DateTimeSpec(date="ABS:2026-08-31", time="08:00"),
                                      rrule=RRule(freq="WEEKLY", byday=["WE", "MO"]))])
    r = rrule_equivalence([base], [reordered], REF)
    check("BYDAY order does not change the occurrence set",
          r["occurrence_set_exact"] == 1.0, str(r))

    # COUNT=4 vs the UNTIL that produces exactly those 4 occurrences.
    counted = L2(id="c", events=[ev(dtstart=DateTimeSpec(date="ABS:2026-08-31", time="08:00"),
                                    rrule=RRule(freq="WEEKLY", byday=["MO"], count=4))])
    occ = occurrences(counted.events[0], REF, horizon_days=365)
    last = occ[-1].date()
    untiled = L2(id="d", events=[ev(dtstart=DateTimeSpec(date="ABS:2026-08-31", time="08:00"),
                                    rrule=RRule(freq="WEEKLY", byday=["MO"],
                                                until=f"ABS:{last.isoformat()}"))])
    r2 = rrule_equivalence([counted], [untiled], REF, horizon_days=365)
    check("COUNT=4 equals the equivalent UNTIL",
          r2["occurrence_set_exact"] == 1.0, f"{r2} last={last} occ={len(occ)}")

    # And a genuinely different rule must NOT compare equal.
    different = L2(id="e", events=[ev(dtstart=DateTimeSpec(date="ABS:2026-08-31", time="08:00"),
                                      rrule=RRule(freq="WEEKLY", byday=["TU"]))])
    r3 = rrule_equivalence([base], [different], REF)
    check("different BYDAY is NOT equivalent", r3["occurrence_set_exact"] == 0.0, str(r3))


def test_rfc5545_cross_product():
    print("\n[spec 5] BYDAY x time cannot be paired in one rule")
    two = FIXTURES["Monday 12pm, Wednesday 5pm Laboratory with Sir Jeff"]
    s = occurrence_set(two, REF, horizon_days=21)
    times = sorted({x[11:16] for x in s})
    days = sorted({dt.datetime.fromisoformat(x).weekday() for x in s})
    check("two VEVENTs yield exactly two distinct times", times == ["12:00", "17:00"], str(times))
    check("occurring only on Mon(0) and Wed(2)", days == [0, 2], str(days))
    per_day = {}
    for x in s:
        d = dt.datetime.fromisoformat(x)
        per_day.setdefault(d.weekday(), set()).add(x[11:16])
    check("Monday only ever at 12:00", per_day[0] == {"12:00"}, str(per_day.get(0)))
    check("Wednesday only ever at 17:00", per_day[2] == {"17:00"}, str(per_day.get(2)))


def test_scorer_sanity():
    print("\n[M3] scorer sanity")
    l1a = L1.from_json({"id": "x", "text": "MWF 8am",
                        "spans": [{"i": 0, "type": "RECUR", "start": 0, "end": 3, "text": "MWF"},
                                  {"i": 1, "type": "TSTART", "start": 4, "end": 7, "text": "8am"}],
                        "event_groups": [[0, 1]], "status": "ok"})
    perfect = span_prf([l1a], [l1a])
    check("identical spans -> F1 1.0", perfect["micro"]["f1"] == 1.0, str(perfect["micro"]))
    l1b = L1.from_json({"id": "x", "text": "MWF 8am",
                        "spans": [{"i": 0, "type": "RECUR", "start": 0, "end": 3, "text": "MWF"}],
                        "event_groups": [[0]], "status": "ok"})
    partial = span_prf([l1a], [l1b])
    check("missing span -> recall 0.5", partial["micro"]["r"] == 0.5, str(partial["micro"]))
    m = l2_exact_match([FIXTURES["MW 8am"]], [FIXTURES["MW 8am"]])
    check("identical L2 -> exact match 1.0", m["exact_match"] == 1.0, str(m))


def test_generator_integrity():
    print("\n[M7] generator integrity over 3000 samples")
    rows = generate(3000, seed=99)
    bad1 = bad2 = 0
    for r in rows:
        if L1.from_json(r["l1"]).validate():
            bad1 += 1
        if L2.from_json(r["l2"]).validate():
            bad2 += 1
    check("all L1 valid (offsets + no overlap)", bad1 == 0, f"{bad1} invalid")
    check("all L2 valid", bad2 == 0, f"{bad2} invalid")
    resolvable = 0
    for r in rows[:600]:
        try:
            occurrence_set(L2.from_json(r["l2"]), REF, horizon_days=60)
            resolvable += 1
        except Exception:
            pass
    check("generated L2 all resolvable to occurrences", resolvable == 600,
          f"{resolvable}/600")


if __name__ == "__main__":
    test_fixtures_valid()
    test_jcal_emission()
    test_date_resolution()
    test_rrule_equivalence_not_string_equality()
    test_rfc5545_cross_product()
    test_scorer_sanity()
    test_generator_integrity()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("ALL TESTS PASSED")
