"""Metrics. The measuring instrument for every later stage -- build it early,
test it against known-equivalent pairs, then leave it alone.

Scoring happens at three levels, deliberately kept separate so errors localise:
  L1  span precision/recall/F1 per slot type  -> is EXTRACTION working?
  L2  exact match on the normalized event     -> are NORMALIZATION + DEFAULTS working?
  L3  occurrence-set equivalence + date accuracy against a FIXED reference time.

RRULE equality is never tested as a string. "BYDAY=MO,WE" and "BYDAY=WE,MO" are
the same rule; COUNT=10 and the matching UNTIL are the same rule. Only the
expanded occurrence set is a defensible test.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .convert import DEFAULT_POLICY, Policy, occurrence_set
from .ir import L1, L2

TEMPORAL_SLOTS = ("RECUR", "TSTART", "TEND", "DATE", "BOUND", "DURATION")


def _span_keys(l1: L1) -> set:
    return {(s.type, s.start, s.end) for s in l1.spans}


def span_prf(gold: list[L1], pred: list[L1]) -> dict:
    """Exact-boundary, exact-type span P/R/F1, overall and per slot type."""
    assert len(gold) == len(pred)
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    for g, p in zip(gold, pred):
        gk, pk = _span_keys(g), _span_keys(p)
        for k in pk & gk:
            tp[k[0]] += 1
        for k in pk - gk:
            fp[k[0]] += 1
        for k in gk - pk:
            fn[k[0]] += 1

    def prf(t, f_p, f_n):
        p = t / (t + f_p) if (t + f_p) else 0.0
        r = t / (t + f_n) if (t + f_n) else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        return {"p": round(p, 4), "r": round(r, 4), "f1": round(f, 4),
                "tp": t, "fp": f_p, "fn": f_n}

    types = set(tp) | set(fp) | set(fn)
    per = {t: prf(tp[t], fp[t], fn[t]) for t in sorted(types)}
    micro = prf(sum(tp.values()), sum(fp.values()), sum(fn.values()))
    temporal = prf(
        sum(tp[t] for t in TEMPORAL_SLOTS),
        sum(fp[t] for t in TEMPORAL_SLOTS),
        sum(fn[t] for t in TEMPORAL_SLOTS),
    )
    return {"micro": micro, "temporal_only": temporal, "per_type": per}


def _norm_event(e: dict) -> tuple:
    rr = e.get("rrule")
    rrk = None
    if rr:
        rrk = (
            rr.get("freq"), rr.get("interval", 1),
            tuple(sorted(rr.get("byday") or [])),
            tuple(sorted(rr.get("bymonthday") or [])),
            rr.get("until"), rr.get("count"),
        )
    ds = e.get("dtstart") or {}
    de = e.get("dtend") or {}
    return (
        (e.get("summary") or "").strip().lower(),
        ds.get("date"), ds.get("time"), de.get("time"),
        e.get("duration_minutes"), rrk,
        tuple(sorted(a.lower() for a in (e.get("attendees") or []))),
        (e.get("location") or "").strip().lower() or None,
    )


def l2_exact_match(gold: list[L2], pred: list[L2], ignore_summary: bool = False) -> dict:
    """Whole-event exact match, plus a temporal-only variant.

    ignore_summary reflects the asymmetric error cost: a wrong SUMMARY is
    cosmetic, a wrong DTSTART is a missed class. Report both.
    """
    n = len(gold)
    full = temporal = status_ok = 0
    for g, p in zip(gold, pred):
        if g.status == p.status:
            status_ok += 1
        gk = [_norm_event(e) for e in g.to_json()["events"]]
        pk = [_norm_event(e) for e in p.to_json()["events"]]
        if sorted(gk) == sorted(pk) and g.status == p.status:
            full += 1
        gt = sorted(k[1:6] for k in gk)
        pt = sorted(k[1:6] for k in pk)
        if gt == pt and g.status == p.status:
            temporal += 1
    return {
        "n": n,
        "exact_match": round(full / n, 4) if n else 0.0,
        "temporal_exact_match": round(temporal / n, 4) if n else 0.0,
        "status_accuracy": round(status_ok / n, 4) if n else 0.0,
    }


def rrule_equivalence(gold: list[L2], pred: list[L2], ref: dt.datetime,
                      horizon_days: int = 180, policy: Policy = DEFAULT_POLICY) -> dict:
    """Compare EXPANDED occurrence sets, not rule strings."""
    exact = 0
    jacc = []
    errors = 0
    for g, p in zip(gold, pred):
        try:
            gs = occurrence_set(g, ref, horizon_days, policy)
            ps = occurrence_set(p, ref, horizon_days, policy)
        except Exception:
            errors += 1
            jacc.append(0.0)
            continue
        if gs == ps:
            exact += 1
        union = gs | ps
        jacc.append(len(gs & ps) / len(union) if union else 1.0)
    n = len(gold)
    return {
        "n": n,
        "occurrence_set_exact": round(exact / n, 4) if n else 0.0,
        "mean_jaccard": round(sum(jacc) / len(jacc), 4) if jacc else 0.0,
        "expansion_errors": errors,
    }


def silent_catastrophic_rate(gold: list[L2], pred: list[L2]) -> dict:
    """A temporal slot is wrong AND no ambiguity flag was raised.

    This is the metric that matters to a user: the model was confidently wrong
    about a time or a weekday, so they miss the class and were never warned.
    """
    AMBIG = {"ampm_ambiguous", "ampm_inferred", "missing_end_time", "missing_date"}
    bad = 0
    for g, p in zip(gold, pred):
        gk = sorted(_norm_event(e)[1:6] for e in g.to_json()["events"])
        pk = sorted(_norm_event(e)[1:6] for e in p.to_json()["events"])
        if gk != pk and not (set(p.flags) & AMBIG):
            bad += 1
    n = len(gold)
    return {"n": n, "silent_catastrophic_rate": round(bad / n, 4) if n else 0.0, "count": bad}


def report(gold_l1, pred_l1, gold_l2, pred_l2, ref: dt.datetime) -> dict:
    return {
        "L1_spans": span_prf(gold_l1, pred_l1),
        "L2_match": l2_exact_match(gold_l2, pred_l2),
        "L3_rrule": rrule_equivalence(gold_l2, pred_l2, ref),
        "risk": silent_catastrophic_rate(gold_l2, pred_l2),
    }
