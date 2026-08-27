"""Model -> L1 -> L2 -> jCal, keeping every intermediate stage.

The stages are kept rather than collapsed because this pipeline's whole design
argument is that the layers are separable: the model makes three judgements, and
deterministic code does everything after. When an output is wrong it should be
obvious WHICH layer was wrong, and that is only possible if each one's output
survives to be looked at.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import torch

from .convert import DEFAULT_POLICY, Policy, l2_to_jcal, occurrence_set
from .ir import L1, L2, Span
from .normalize import l1_to_l2
from .segment import groups_for_spans
from .tagging import BOS, EOS, ID2LABEL, ID2STATUS, decode, decode_chunked


@dataclass
class Run:
    """Every stage of one string's trip through the pipeline."""
    text: str
    n_bytes: int
    status: str
    status_probs: dict[str, float]
    byte_labels: list[str] = field(default_factory=list)
    byte_conf: list[float] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    span_conf: list[float] = field(default_factory=list)
    groups: list[list[int]] = field(default_factory=list)
    l1: L1 | None = None
    l2: L2 | None = None
    unknown_flags: set[str] = field(default_factory=set)
    jcal: list | None = None
    occurrences: list[str] = field(default_factory=list)
    error: str | None = None


@torch.no_grad()
def run(model, text: str, ref: dt.datetime | None = None,
        policy: Policy = DEFAULT_POLICY, horizon_days: int = 28,
        max_len: int = 192, device: str = "cpu",
        chunked: bool = True) -> Run:
    model.eval()
    ref = ref or dt.datetime.now().replace(second=0, microsecond=0)

    raw = text.encode("utf-8")[:max_len - 2]
    ids = torch.tensor([[BOS] + list(raw) + [EOS]], dtype=torch.long, device=device)

    tag_logits, status_logits = model(ids)
    tag_prob = tag_logits.softmax(-1)[0, 1:1 + len(raw)]
    st_prob = status_logits.softmax(-1)[0]

    status = ID2STATUS[int(st_prob.argmax())]
    probs = {ID2STATUS[i]: float(st_prob[i]) for i in range(len(st_prob))}

    tag_ids = [int(i) for i in tag_prob.argmax(-1)]
    conf = [float(c) for c in tag_prob.max(-1).values]
    labels = [ID2LABEL.get(i, "O") for i in tag_ids]

    r = Run(text=text, n_bytes=len(raw), status=status, status_probs=probs,
            byte_labels=labels, byte_conf=conf)

    # Chunk-level decoding by default; byte argmax has no contiguity constraint
    # and shatters spans mid-word on unfamiliar text. chunked=False keeps the
    # raw behaviour so the difference stays measurable.
    r.spans = (decode_chunked(text, tag_prob.tolist()) if chunked
               else decode(text, tag_ids))
    # Mean confidence over the bytes a span covers, so a span the model was
    # unsure about is visibly unsure rather than blending into the rest.
    c2b = [0]
    for ch in text:
        c2b.append(c2b[-1] + len(ch.encode("utf-8")))
    for s in r.spans:
        b0, b1 = c2b[s.start], min(c2b[s.end], len(conf))
        window = conf[b0:b1]
        r.span_conf.append(sum(window) / len(window) if window else 0.0)

    r.groups = groups_for_spans(text, r.spans) if status == "ok" else []
    # groups_for_spans returns indices into the span list it was given; L1 wants
    # indices into l1.spans, and decode() already numbered them in order.
    r.l1 = L1(id="live", text=text, spans=r.spans, event_groups=r.groups,
              status=status, flags=[])

    if status != "ok":
        r.l2 = L2(id="live", events=[], status=status, flags=[])
        return r

    try:
        r.l2, trace = l1_to_l2(r.l1, policy)
        r.unknown_flags = set(trace.flags)
    except Exception as exc:                                # pragma: no cover
        r.error = f"L1->L2 failed: {exc}"
        return r

    if not r.l2.events:
        return r

    try:
        r.jcal = l2_to_jcal(r.l2, ref, policy=policy)
        r.occurrences = sorted(occurrence_set(r.l2, ref, horizon_days=horizon_days,
                                             policy=policy))
    except Exception as exc:                                # pragma: no cover
        r.error = f"L2->jCal failed: {exc}"
    return r


def load(path: str, device: str = "cpu"):
    """Load a checkpoint written by scripts/train.py."""
    from .model import ByteTagger, Config

    ck = torch.load(path, map_location=device, weights_only=False)
    model = ByteTagger(Config(**ck["config"]))
    model.load_state_dict(ck["state_dict"])
    model.to(device).eval()
    return model, ck.get("meta", {})
