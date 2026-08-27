"""Type a string, watch it become a calendar entry. Every stage shown.

  uv run python scripts/inspect_pipeline.py                 # interactive
  uv run python scripts/inspect_pipeline.py "gym mwf 8-10"  # one shot
  uv run python scripts/inspect_pipeline.py --rules "..."   # rule baseline instead

The point is not the jCal at the bottom. It is being able to see WHICH layer got
something wrong -- the model's status call, the model's spans, the grouping, the
normalizer's defaulting, or the date resolution -- because they are separate
layers and a single wrong answer at the end never tells you which one moved.
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import asdict as _asdict
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.convert import DEFAULT_POLICY, resolve_date

# Windows consoles default to cp1252, which cannot encode a box-drawing
# character. Ask for UTF-8; if the terminal refuses, fall back to ASCII glyphs
# rather than dying on the first line of output.
UNICODE_OK = True
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        UNICODE_OK = False
if UNICODE_OK:
    try:
        "─█·".encode(sys.stdout.encoding or "utf-8")
    except Exception:
        UNICODE_OK = False

GLYPH = {"h": "─", "full": "█", "dot": "·"} if UNICODE_OK else \
        {"h": "-", "full": "#", "dot": "."}

_COLOR = sys.stdout.isatty() and "--no-color" not in sys.argv
C = {"dim": "\033[2m", "b": "\033[1m", "r": "\033[0m", "red": "\033[31m",
     "grn": "\033[32m", "yel": "\033[33m", "blu": "\033[36m", "mag": "\033[35m"}
if not _COLOR:
    C = {k: "" for k in C}
TYPE_COLOR = {
    "SUMMARY": C["grn"], "RECUR": C["mag"], "TSTART": C["blu"], "TEND": C["blu"],
    "DATE": C["yel"], "BOUND": C["red"], "PERSON": C["b"], "DURATION": C["yel"],
}
STATUS_COLOR = {"ok": C["grn"], "no_temporal": C["dim"],
                "unresolvable": C["yel"], "unrepresentable": C["red"]}


def rule(title: str, width: int = 74) -> str:
    h = GLYPH["h"]
    return f"\n{C['dim']}{h * 3} {title} {h * max(0, width - len(title) - 5)}{C['r']}"


def bar(p: float, width: int = 18) -> str:
    n = int(round(p * width))
    return GLYPH["full"] * n + GLYPH["dot"] * (width - n)


def show_spans(text: str, spans, conf=None) -> None:
    """The string with each tagged region underlined in its type's colour."""
    if not spans:
        print(f"  {C['dim']}(no spans){C['r']}")
        return
    line, under, cur = "", "", 0
    for s in sorted(spans, key=lambda x: x.start):
        if s.start > cur:
            gap = text[cur:s.start]
            line += f"{C['dim']}{gap}{C['r']}"
            under += " " * len(gap)
        col = TYPE_COLOR.get(s.type, "")
        frag = text[s.start:s.end]
        line += f"{col}{frag}{C['r']}"
        under += col + GLYPH["h"] * len(frag) + C["r"]
        cur = s.end
    if cur < len(text):
        line += f"{C['dim']}{text[cur:]}{C['r']}"
    print(f"  {line}\n  {under}")
    print()
    for n, s in enumerate(sorted(spans, key=lambda x: x.start)):
        col = TYPE_COLOR.get(s.type, "")
        c = f"  {C['dim']}conf {conf[n]:.2f}{C['r']}" if conf and n < len(conf) else ""
        print(f"    [{s.i}] {col}{s.type:<9}{C['r']} {s.text!r}{c}")


def show(r, ref: dt.datetime, source: str) -> None:
    print(rule(f"1. INPUT  ({source})"))
    print(f"  {r.text!r}")
    print(f"  {C['dim']}{r.n_bytes} bytes  ·  reference time "
          f"{ref:%Y-%m-%d %H:%M} ({ref:%A}){C['r']}")

    print(rule("2. Q1 — IS IT A SCHEDULE?"))
    for st, p in sorted(r.status_probs.items(), key=lambda kv: -kv[1]):
        mark = "->" if st == r.status else "  "
        col = STATUS_COLOR.get(st, "") if st == r.status else C["dim"]
        print(f"  {mark} {col}{st:<16}{C['r']} {C['dim']}{bar(p)}{C['r']} {p:5.1%}")
    if r.status != "ok":
        print(f"\n  {STATUS_COLOR.get(r.status,'')}{C['b']}REFUSED: {r.status}{C['r']}")
        print(f"  {C['dim']}Nothing is scheduled. The text is kept as the title so a "
              f"UI can show\n  what it declined to act on.{C['r']}")

    print(rule("3. Q2/Q3 — WHERE IS THE TITLE, WHERE IS THE TIME?"))
    show_spans(r.text, r.spans, r.span_conf)

    if r.status != "ok":
        print(rule("DONE — refused, no calendar entry"))
        return

    print(rule("4. HOW MANY EVENTS?  (deterministic, segment.py)"))
    if not r.groups:
        print(f"  {C['dim']}(no groups){C['r']}")
    for n, g in enumerate(r.groups, 1):
        members = [s for s in r.spans if s.i in g]
        desc = "  ".join(f"{TYPE_COLOR.get(s.type,'')}{s.type}{C['r']}={s.text!r}"
                         for s in sorted(members, key=lambda x: x.start))
        print(f"  event {n}: {desc}")
    if len(r.groups) > 1:
        print(f"  {C['dim']}RFC 5545 cannot bind different weekdays to different "
              f"times in one rule,\n  so this becomes {len(r.groups)} VEVENTs.{C['r']}")

    print(rule("5. L2 — NORMALIZED MEANING  (symbolic, no real dates yet)"))
    if r.error:
        print(f"  {C['red']}{r.error}{C['r']}")
        return
    if not r.l2 or not r.l2.events:
        print(f"  {C['dim']}(no events){C['r']}")
        return
    for n, ev in enumerate(r.l2.events, 1):
        print(f"  event {n}")
        print(f"    summary   {ev.summary!r}")
        print(f"    dtstart   date={ev.dtstart.date}  time={ev.dtstart.time}")
        if ev.dtend:
            print(f"    dtend     date={ev.dtend.date}  time={ev.dtend.time}")
        if ev.duration_minutes:
            print(f"    duration  {ev.duration_minutes} min")
        if ev.rrule:
            rr = {k: v for k, v in _asdict(ev.rrule).items() if v not in (None, [], 1)}
            print(f"    rrule     {rr}")
        if ev.attendees:
            print(f"    attendees {ev.attendees}")
        if ev.exclude:
            print(f"    exclude   {ev.exclude}")
    if r.l2.flags:
        print(f"\n  flags     {C['yel']}{' '.join(r.l2.flags)}{C['r']}")
    if r.unknown_flags:
        print(f"  {C['dim']}trace-only {' '.join(sorted(r.unknown_flags))}{C['r']}")

    print(rule("6. RESOLUTION — symbols become real dates"))
    for n, ev in enumerate(r.l2.events, 1):
        sym = ev.dtstart.date
        try:
            got = resolve_date(sym, ref, ev.rrule, DEFAULT_POLICY) if sym else None
        except Exception as exc:
            got = f"<{exc}>"
        print(f"  event {n}: {C['dim']}{sym}{C['r']} -> {C['b']}{got}{C['r']}")
        if ev.rrule and ev.rrule.until:
            try:
                u = resolve_date(ev.rrule.until, ref, None, DEFAULT_POLICY)
            except Exception as exc:
                u = f"<{exc}>"
            print(f"           until {C['dim']}{ev.rrule.until}{C['r']} -> {u}")

    print(rule("7. OCCURRENCES  (next 28 days)"))
    if not r.occurrences:
        print(f"  {C['dim']}(none in window){C['r']}")
    for o in r.occurrences[:12]:
        when = dt.datetime.fromisoformat(o)
        print(f"  {when:%a %Y-%m-%d %H:%M}")
    if len(r.occurrences) > 12:
        print(f"  {C['dim']}... and {len(r.occurrences)-12} more{C['r']}")

    print(rule("8. jCal  (RFC 7265)"))
    print(json.dumps(r.jcal, indent=2)[:2000])


def rules_run(text: str, ref: dt.datetime):
    """Same Run shape, produced by the rule baseline, for side-by-side use."""
    from stlm.convert import l2_to_jcal, occurrence_set
    from stlm.infer import Run
    from stlm.ir import L1
    from stlm.normalize import l1_to_l2
    from stlm.segment import spans_and_groups

    spans, groups = spans_and_groups(text)
    status = "ok" if spans else "no_temporal"
    r = Run(text=text, n_bytes=len(text.encode()), status=status,
            status_probs={status: 1.0}, spans=spans, groups=groups)
    r.l1 = L1(id="live", text=text, spans=spans, event_groups=groups, status=status)
    r.l2, tr = l1_to_l2(r.l1)
    r.unknown_flags = set(tr.flags)
    if r.l2.events:
        r.jcal = l2_to_jcal(r.l2, ref)
        r.occurrences = sorted(occurrence_set(r.l2, ref, horizon_days=28))
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="string to inspect; omit for a prompt")
    ap.add_argument("--ckpt", default=str(ROOT / "checkpoints" / "tagger.pt"))
    ap.add_argument("--rules", action="store_true", help="use the rule baseline")
    ap.add_argument("--both", action="store_true", help="model and rules, in turn")
    ap.add_argument("--ref", default=None, help="reference time, ISO (default: now)")
    args = ap.parse_args()

    ref = dt.datetime.fromisoformat(args.ref) if args.ref else \
        dt.datetime.now().replace(second=0, microsecond=0)

    model = None
    if not args.rules:
        ck = pathlib.Path(args.ckpt)
        if not ck.exists():
            print(f"{C['yel']}no checkpoint at {ck} -- falling back to the rule "
                  f"baseline.\nTrain one with: uv run python scripts/train.py{C['r']}")
            args.rules = True
        else:
            from stlm.infer import load
            model, meta = load(str(ck))
            d = meta.get("dev", {})
            print(f"{C['dim']}loaded {ck.name}  epoch {meta.get('epoch','?')}  "
                  f"dev status {d.get('status_acc',0):.3f} / SUMMARY-F1 "
                  f"{d.get('summary_f1',0):.3f} / temporal {d.get('temporal_exact',0):.3f}"
                  f"{C['r']}")

    def once(text: str) -> None:
        if not text.strip():
            return
        from stlm.infer import run as infer_run
        if args.rules:
            show(rules_run(text, ref), ref, "rule baseline")
        elif args.both:
            show(infer_run(model, text, ref=ref), ref, "model")
            show(rules_run(text, ref), ref, "rule baseline")
        else:
            show(infer_run(model, text, ref=ref), ref, "model")
        print()

    if args.text:
        once(" ".join(args.text))
        return

    print(f"{C['b']}Schedantic pipeline inspector{C['r']}  "
          f"{C['dim']}(blank line or Ctrl-C to quit){C['r']}")
    while True:
        try:
            line = input(f"\n{C['b']}> {C['r']}")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line.strip():
            return
        try:
            once(line)
        except Exception as exc:
            print(f"  {C['red']}pipeline raised: {type(exc).__name__}: {exc}{C['r']}")


if __name__ == "__main__":
    main()
