"""Grammar probe suite: which PART of the grammar is the model failing?

  uv run python scripts/probe_grammar.py
  uv run python scripts/probe_grammar.py --show-fails
  uv run python scripts/probe_grammar.py --ckpt checkpoints/tagger_v1.pt
  uv run python scripts/probe_grammar.py --rules          # baseline instead

Aggregate scores say "SUMMARY F1 is 0.589" and leave you guessing. This says
"time-of-day is 0.4 and bounded counts are 1.0", which is something you can act
on. Every probe is one targeted assertion about one construction, grouped so a
weak area shows up as a low row rather than as a vague feeling.

WHAT THIS IS NOT. These probes are written by the model, so they are a
DIAGNOSTIC, not gold and not a score to report. Two consequences, both
deliberate:

  - They must never be trained on. Fixing the generator so these pass is fine;
    pasting these strings into the generator is not, for the same reason the
    refusal frames could not quote the eval set.
  - A category at 1.00 means "the construction works on the phrasings I thought
    to write", never "this construction is solved".

The real measurements stay dev and test.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REF = dt.datetime(2026, 8, 27, 9, 0, 0)          # a Thursday

# Each probe: (text, expectations). Expectation keys:
#   status   expected L1 status
#   span     (TYPE, substring) -- a span of TYPE whose text contains substring
#   nospan   (TYPE, substring) -- no such span
#   type_of  (substring, TYPE) -- whichever span covers substring has this type
#   time     L2 dtstart.time on the first event
#   byday    L2 rrule byday on the first event
#   events   number of events
PROBES: list[tuple[str, str, dict]] = [

    # --- time of day, bare --------------------------------------------------
    ("tod_bare", "gym in the morning", {"type_of": ("morning", "TSTART")}),
    ("tod_bare", "swim at noon", {"type_of": ("noon", "TSTART")}),
    ("tod_bare", "dinner in the evening", {"type_of": ("evening", "TSTART")}),
    ("tod_bare", "study tonight", {"type_of": ("tonight", "TSTART")}),
    ("tod_bare", "walk the dog at dawn", {"type_of": ("dawn", "TSTART")}),
    ("tod_bare", "meeting this afternoon", {"type_of": ("afternoon", "TSTART")}),
    ("tod_bare", "Tea time, noon", {"type_of": ("noon", "TSTART"),
                                    "status": "ok"}),
    ("tod_bare", "band practice at night", {"type_of": ("night", "TSTART")}),

    # --- time of day, modified ("this noon", "later") -----------------------
    ("tod_modified", "lunch this noon", {"type_of": ("noon", "TSTART")}),
    ("tod_modified", "call mom later today", {"status": "ok"}),
    ("tod_modified", "gym later", {"status": "ok"}),
    ("tod_modified", "groceries tomorrow morning",
     {"type_of": ("morning", "TSTART"), "type_of2": ("tomorrow", "DATE")}),
    ("tod_modified", "run early morning", {"type_of": ("morning", "TSTART")}),
    ("tod_modified", "shift late night", {"type_of": ("night", "TSTART")}),
    ("tod_modified", "mass sunday morning", {"type_of": ("morning", "TSTART")}),
    ("tod_modified", "review session tomorrow evening",
     {"type_of": ("evening", "TSTART")}),

    # --- explicit clock times ------------------------------------------------
    ("clock", "gym 8am", {"span": ("TSTART", "8am"), "time": "08:00"}),
    ("clock", "gym 8:30am", {"time": "08:30"}),
    ("clock", "standup at 0800", {"time": "08:00"}),
    ("clock", "lunch 12nn", {"time": "12:00"}),
    ("clock", "call at 5 pm", {"time": "17:00"}),
    ("clock", "class 13:00", {"time": "13:00"}),
    ("clock", "dinner at 7.30pm", {"time": "19:30"}),
    ("clock", "shift starts 2200", {"time": "22:00"}),

    # --- bare hour, no meridiem ---------------------------------------------
    ("clock_ambiguous", "gym at 6", {"span": ("TSTART", "6")}),
    ("clock_ambiguous", "MW 8 lecture", {"span": ("TSTART", "8")}),
    ("clock_ambiguous", "meet at 3", {"span": ("TSTART", "3")}),
    ("clock_ambiguous", "practice 11", {"span": ("TSTART", "11")}),

    # --- time ranges ----------------------------------------------------------
    ("range", "gym 8-10", {"span": ("TSTART", "8"), "span2": ("TEND", "10")}),
    ("range", "class 9 to 11", {"span2": ("TEND", "11")}),
    ("range", "lab 8-12nn", {"span2": ("TEND", "12nn")}),
    ("range", "shift from 2 til 4", {"span2": ("TEND", "4")}),
    ("range", "seminar 9:30 - 11:00", {"span2": ("TEND", "11:00")}),
    ("range", "duty 10am until 2pm", {"span2": ("TEND", "2pm")}),

    # --- duration -------------------------------------------------------------
    ("duration", "gym 6pm for 90 mins", {"span": ("DURATION", "90")}),
    ("duration", "meeting at 3 for 2 hrs", {"span": ("DURATION", "2 hrs")}),
    ("duration", "yoga 7am for 45 minutes", {"span": ("DURATION", "45")}),
    ("duration", "call 9am 30min", {"span": ("DURATION", "30min")}),

    # --- bounds ---------------------------------------------------------------
    ("bound_until", "gym mwf til december", {"span": ("BOUND", "til december")}),
    ("bound_until", "class every tue until dec", {"span": ("BOUND", "until dec")}),
    ("bound_until", "shift daily till the end of may", {"span": ("BOUND", "till")}),
    ("bound_count", "gym mwf x12", {"span": ("BOUND", "x12")}),
    ("bound_count", "therapy every tue for 8 weeks", {"span": ("BOUND", "8 weeks")}),
    ("bound_count", "class tth 6 sessions", {"span": ("BOUND", "6 sessions")}),

    # --- single weekday (guide: bare single weekday is DATE) -----------------
    ("weekday_single", "dentist monday", {"type_of": ("monday", "DATE")}),
    ("weekday_single", "THURS lunch", {"type_of": ("THURS", "DATE")}),
    ("weekday_single", "haircut sat", {"type_of": ("sat", "DATE")}),
    ("weekday_single", "vet appointment on friday", {"type_of": ("friday", "DATE")}),

    # --- weekday codes --------------------------------------------------------
    ("weekday_code", "gym MWF 8am", {"byday": ["MO", "WE", "FR"]}),
    ("weekday_code", "class TTh 5pm", {"byday": ["TU", "TH"]}),
    ("weekday_code", "lab TR 7", {"byday": ["TU", "TH"]}),
    ("weekday_code", "work MTWThF 9am", {"byday": ["MO", "TU", "WE", "TH", "FR"]}),
    ("weekday_code", "duty MW 8", {"byday": ["MO", "WE"]}),
    ("weekday_code", "shifts M-SAT 6am",
     {"byday": ["MO", "TU", "WE", "TH", "FR", "SA"]}),

    # --- weekday lists spelled out -------------------------------------------
    ("weekday_list", "gym Mon Wed Fri 6am", {"byday": ["MO", "WE", "FR"]}),
    ("weekday_list", "market sat and sun", {"byday": ["SA", "SU"]}),
    ("weekday_list", "class tues/thurs 3pm", {"byday": ["TU", "TH"]}),
    ("weekday_list", "run tuesdays and thursdays", {"byday": ["TU", "TH"]}),

    # --- explicit recurrence --------------------------------------------------
    ("recur_explicit", "standup every weekday 9am",
     {"byday": ["MO", "TU", "WE", "TH", "FR"]}),
    ("recur_explicit", "gym daily 6am", {"span": ("RECUR", "daily")}),
    ("recur_explicit", "meeting weekly", {"span": ("RECUR", "weekly")}),
    ("recur_explicit", "standup biweekly", {"span": ("RECUR", "biweekly")}),
    ("recur_explicit", "therapy every other tuesday", {"byday": ["TU"]}),
    ("recur_explicit", "class every tue 5pm", {"byday": ["TU"]}),
    ("recur_explicit", "yoga every day 7am", {"span": ("RECUR", "every day")}),

    # --- ordinal recurrence ---------------------------------------------------
    ("recur_ordinal", "rent every 1st", {"span": ("RECUR", "every 1st")}),
    ("recur_ordinal", "choir every 3rd sun 4pm", {"span": ("RECUR", "every 3rd sun")}),
    ("recur_ordinal", "meeting every 2nd monday", {"span": ("RECUR", "every 2nd")}),

    # --- negated recurrence ---------------------------------------------------
    ("negation", "gym daily except sunday", {"span": ("RECUR", "except sunday")}),
    ("negation", "class MTWThF but not friday", {"span": ("RECUR", "not friday")}),
    ("negation", "work M-F no wednesday", {"span": ("RECUR", "no wednesday")}),
    ("negation", "pilates every day except friday", {"span": ("RECUR", "except friday")}),

    # --- relative dates -------------------------------------------------------
    ("rel_date", "gym tmrw 6pm", {"span": ("DATE", "tmrw")}),
    ("rel_date", "call mom today", {"span": ("DATE", "today")}),
    ("rel_date", "defense next monday", {"span": ("DATE", "next monday")}),
    ("rel_date", "quiz this friday", {"span": ("DATE", "this friday")}),
    ("rel_date", "trip day after tomorrow", {"span": ("DATE", "tomorrow")}),
    ("rel_date", "meeting next week", {"span": ("DATE", "next week")}),

    # --- absolute dates -------------------------------------------------------
    ("abs_date", "defense sept 3 at 2pm", {"span": ("DATE", "sept 3")}),
    ("abs_date", "checkup oct 4 2pm", {"span": ("DATE", "oct 4")}),
    ("abs_date", "party december 25", {"span": ("DATE", "december 25")}),
    ("abs_date", "exam on jan 15", {"span": ("DATE", "jan 15")}),

    # --- ordinal day-of-month -------------------------------------------------
    ("ordinal_date", "dentist on the 15th", {"span": ("DATE", "15th")}),
    ("ordinal_date", "the 21st is the deadline", {"span": ("DATE", "21st")}),
    ("ordinal_date", "booster on the 8th", {"span": ("DATE", "8th")}),

    # --- named dates ----------------------------------------------------------
    ("named_date", "dinner christmas eve", {"span": ("DATE", "christmas eve")}),
    ("named_date", "mass holy thursday", {"span": ("DATE", "holy thursday")}),
    ("named_date", "party halloween 8pm", {"span": ("DATE", "halloween")}),
    ("named_date", "visit all souls day", {"span": ("DATE", "all souls")}),

    # --- person ---------------------------------------------------------------
    ("person", "lunch with mom saturday", {"span": ("PERSON", "mom")}),
    ("person", "class MWF 8 with Sir Jefferson",
     {"span": ("PERSON", "Sir Jefferson")}),
    ("person", "checkup w/ Dr. Cruz on the 15th", {"span": ("PERSON", "Dr. Cruz")}),
    ("person", "call ate bea friday 4pm", {"span": ("PERSON", "ate bea")}),
    ("person", "sync with the team 10am", {"span": ("PERSON", "team")}),

    # --- multi event ----------------------------------------------------------
    ("multi_event", "Lecture MW 9, Lab F 2", {"events": 2}),
    ("multi_event", "Lab Mon12pm Wed5pm", {"events": 2}),
    ("multi_event", "MWF 8am gym and TTh 6pm run", {"events": 2}),
    ("multi_event", "Tue map, Fri module", {"events": 2}),
    ("multi_event", "gym mwf 6am", {"events": 1}),
    ("multi_event", "Mon Wed Fri 9am gym", {"events": 1}),
    ("multi_event", "gym tmrw, 7pm start", {"events": 1}),

    # --- title is a verb phrase ----------------------------------------------
    ("verb_phrase", "walk the dog 8am", {"type_of": ("walk", "SUMMARY")}),
    ("verb_phrase", "feed the cat 7pm", {"type_of": ("cat", "SUMMARY")}),
    ("verb_phrase", "pay the electric bill friday", {"type_of": ("pay", "SUMMARY")}),
    ("verb_phrase", "pick up the package tmrw", {"type_of": ("package", "SUMMARY")}),
    ("verb_phrase", "renew the license on the 15th", {"type_of": ("renew", "SUMMARY")}),
    ("verb_phrase", "water the plants every morning", {"type_of": ("plants", "SUMMARY")}),

    # --- venue belongs in the summary ----------------------------------------
    ("venue", "mass at the chapel 6am", {"type_of": ("chapel", "SUMMARY")}),
    ("venue", "class MWF 8 in room 201", {"type_of": ("room", "SUMMARY")}),
    ("venue", "lab @ CS Bldg tth 9", {"type_of": ("Bldg", "SUMMARY")}),
    ("venue", "meeting on zoom 3pm", {"type_of": ("zoom", "SUMMARY")}),

    # --- trailing chatter stays in the summary -------------------------------
    ("chatter", "gym tmrw 6pm bro dont forget your towel",
     {"type_of": ("towel", "SUMMARY")}),
    ("chatter", "class monday 8 please arrive early",
     {"type_of": ("early", "SUMMARY")}),
    ("chatter", "standup 9am sharp no excuses", {"type_of": ("excuses", "SUMMARY")}),

    # --- casing and typos -----------------------------------------------------
    ("casing_typo", "gYm tMrW 6pM", {"status": "ok"}),
    ("casing_typo", "GYM MWF 8AM", {"byday": ["MO", "WE", "FR"]}),
    ("casing_typo", "dentst tmrw 3pm", {"status": "ok"}),
    ("casing_typo", "clas mwf 8-10", {"byday": ["MO", "WE", "FR"]}),
    ("casing_typo", "eVry 2 wks haircut", {"status": "ok"}),

    # --- negatives: day word that is not a day -------------------------------
    ("neg_daylookalike", "Ms. Sunday in Accounts Payable signed it",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "the pallet Sat in the alley for 2 hrs",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "April is the only good part of that run",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "they got wed at city hall last week",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "students will march in order of department",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "a june bug got into the tank room",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "the senate was supposedly this august body",
     {"status": "no_temporal"}),
    ("neg_daylookalike", "damn the sun was brutal at the court earlier",
     {"status": "no_temporal"}),

    # --- negatives: numbers that are not times -------------------------------
    ("neg_number", "500g flour, 2 eggs, 300ml milk", {"status": "no_temporal"}),
    ("neg_number", "our flight number is PR 431", {"status": "no_temporal"}),
    ("neg_number", "battery health at 87 percent after 2 years",
     {"status": "no_temporal"}),
    ("neg_number", "the recipe says bake at 180 for 40 minutes",
     {"status": "no_temporal"}),
    ("neg_number", "he scored 24 points in the fourth quarter",
     {"status": "no_temporal"}),
    ("neg_number", "chicken breast is 220 per kilo at the market",
     {"status": "no_temporal"}),
    ("neg_number", "i rated it 7 out of 10", {"status": "no_temporal"}),
    ("neg_number", "rolled 4d6 drop lowest and got a 7", {"status": "no_temporal"}),

    # --- negatives: questions and chatter ------------------------------------
    ("neg_question", "when does the permit office open, 8 or 9?",
     {"status": "no_temporal"}),
    ("neg_question", "what time is low tide tmrw i forgot to check",
     {"status": "no_temporal"}),
    ("neg_question", "whens bex free to look at the mirrors",
     {"status": "no_temporal"}),
    ("neg_chat", "ok thanks", {"status": "no_temporal"}),
    ("neg_chat", "okok im dead thats so him", {"status": "no_temporal"}),
    ("neg_chat", "lmao ok thats fair, i yield", {"status": "no_temporal"}),
    ("neg_chat", "my back hurts so bad today", {"status": "no_temporal"}),
    ("neg_chat", "traffic is insane right now", {"status": "no_temporal"}),

    # --- negatives: cancellation creates nothing -----------------------------
    ("neg_cancel", "no session this week, dev has a work thing",
     {"status": "no_temporal"}),
    ("neg_cancel", "the saturday lecture series is suspended",
     {"status": "no_temporal"}),
    ("neg_cancel", "scratch tuesday, mia cant cover", {"status": "no_temporal"}),
    ("neg_cancel", "no classes tomorrow due to the storm",
     {"status": "no_temporal"}),

    # --- refusals: real event, nothing to pin it to --------------------------
    ("refuse_unresolvable", "lets hoop one of these days when ur not busy",
     {"status": "unresolvable"}),
    ("refuse_unresolvable", "coffee sometime after the busy season",
     {"status": "unresolvable"}),
    ("refuse_unresolvable", "the panel at the convention center",
     {"status": "unresolvable"}),
    ("refuse_unresolvable", "well run the one shot whenever schedules line up",
     {"status": "unresolvable"}),

    # --- refusals: the schema cannot hold it ---------------------------------
    ("refuse_unrepresentable", "vitamins every day but not when i travel",
     {"status": "unrepresentable"}),
    ("refuse_unrepresentable", "jog every day that it doesnt rain",
     {"status": "unrepresentable"}),
    ("refuse_unrepresentable", "oct 21-23 conference at the center",
     {"status": "unrepresentable"}),
    ("refuse_unrepresentable", "gym when im not on duty, usually 2-3x a week",
     {"status": "unrepresentable"}),
]


def covering(spans, needle: str):
    """The span whose text contains needle, if any."""
    for s in spans:
        if needle.lower() in s.text.lower():
            return s
    return None


def check(r, exp: dict) -> tuple[bool, str]:
    if "status" in exp and r.status != exp["status"]:
        return False, f"status={r.status} want {exp['status']}"
    for key in ("span", "span2"):
        if key in exp:
            typ, sub = exp[key]
            if not any(s.type == typ and sub.lower() in s.text.lower()
                       for s in r.spans):
                got = [(s.type, s.text) for s in r.spans]
                return False, f"no {typ} covering {sub!r}; got {got}"
    for key in ("type_of", "type_of2"):
        if key in exp:
            sub, typ = exp[key]
            s = covering(r.spans, sub)
            if s is None:
                return False, f"{sub!r} untagged"
            if s.type != typ:
                return False, f"{sub!r} tagged {s.type}, want {typ}"
    if "time" in exp:
        t = r.l2.events[0].dtstart.time if (r.l2 and r.l2.events) else None
        if t != exp["time"]:
            return False, f"time={t} want {exp['time']}"
    if "byday" in exp:
        rr = r.l2.events[0].rrule if (r.l2 and r.l2.events) else None
        got = rr.byday if rr else None
        if got != exp["byday"]:
            return False, f"byday={got} want {exp['byday']}"
    if "events" in exp:
        n = len(r.l2.events) if r.l2 else 0
        if n != exp["events"]:
            return False, f"events={n} want {exp['events']}"
    return True, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(ROOT / "checkpoints" / "tagger.pt"))
    ap.add_argument("--rules", action="store_true")
    ap.add_argument("--show-fails", action="store_true")
    ap.add_argument("--only", default=None, help="one category")
    args = ap.parse_args()

    if args.rules:
        from stlm.ir import L1
        from stlm.normalize import l1_to_l2
        from stlm.infer import Run
        from stlm.segment import spans_and_groups

        def go(text):
            spans, groups = spans_and_groups(text)
            st = "ok" if spans else "no_temporal"
            r = Run(text=text, n_bytes=len(text.encode()), status=st,
                    status_probs={st: 1.0}, spans=spans, groups=groups)
            r.l1 = L1(id="p", text=text, spans=spans, event_groups=groups, status=st)
            r.l2 = l1_to_l2(r.l1)[0]
            return r
        label = "rule baseline"
    else:
        from stlm.infer import load, run as infer_run
        model, meta = load(args.ckpt)
        label = pathlib.Path(args.ckpt).name
        def go(text):
            return infer_run(model, text, ref=REF)

    probes = [p for p in PROBES if not args.only or p[0] == args.only]
    per = collections.OrderedDict()
    fails = []
    for cat, text, exp in probes:
        r = go(text)
        ok, why = check(r, exp)
        per.setdefault(cat, [0, 0])
        per[cat][1] += 1
        if ok:
            per[cat][0] += 1
        else:
            fails.append((cat, text, why))

    print(f"=== grammar probe: {label} ===  {len(probes)} probes\n")
    print(f"  {'category':<24}{'pass':>6}{'n':>5}   score")
    worst = []
    for cat, (good, n) in per.items():
        s = good / n
        bar = "#" * int(round(s * 20)) + "." * (20 - int(round(s * 20)))
        flag = "  <-- WEAK" if s < 0.6 else ""
        print(f"  {cat:<24}{good:>6}{n:>5}   {bar} {s:.2f}{flag}")
        worst.append((s, cat))
    tot = sum(v[0] for v in per.values())
    print(f"\n  {'OVERALL':<24}{tot:>6}{len(probes):>5}   {tot/len(probes):.3f}")

    print("\n  weakest areas:")
    for s, cat in sorted(worst)[:5]:
        print(f"    {s:.2f}  {cat}")

    if args.show_fails:
        print("\n=== failures ===")
        for cat, text, why in fails:
            print(f"  [{cat}] {text!r}\n      {why}")


if __name__ == "__main__":
    main()
