"""L1 spans <-> per-byte BIO tags. The interface between the IR and the model.

The model sees bytes, because that was the first design decision in the project:
vocabulary is 256 plus a few specials, there is no tokenizer, and nothing has to
be robust to a subword split landing in the middle of "8am".

L1 spans carry CHARACTER offsets, which are not byte offsets the moment anyone
types an em dash. Two gold rows already contain one. So the mapping is computed,
never assumed -- getting this wrong would silently shift every label after the
first non-ASCII character in a line, and the model would learn the shift.

Tagging is BIO over 8 span types: 17 labels. B- opens a span, I- continues it,
O is outside. That distinction is load-bearing here in a way it is not in most
taggers: `Mon Wed` as one RECUR span and `Mon`+`Wed` as two are different
labellings that produce different events, and only the B/I split tells them
apart.
"""

from __future__ import annotations

from .ir import SPAN_TYPES, STATUSES, L1, Span

# --- label vocabulary --------------------------------------------------------

LABELS: tuple[str, ...] = ("O",) + tuple(
    f"{p}-{t}" for t in SPAN_TYPES for p in ("B", "I"))
LABEL2ID: dict[str, int] = {lab: i for i, lab in enumerate(LABELS)}
ID2LABEL: dict[int, str] = {i: lab for lab, i in LABEL2ID.items()}
N_LABELS = len(LABELS)

STATUS2ID: dict[str, int] = {s: i for i, s in enumerate(STATUSES)}
ID2STATUS: dict[int, str] = {i: s for s, i in STATUS2ID.items()}
N_STATUSES = len(STATUSES)

# Byte vocabulary: 0-255 are bytes, then the specials. PAD must be ignored by
# the loss; the model never predicts it.
PAD, BOS, EOS = 256, 257, 258
VOCAB = 259


def char_to_byte_offsets(text: str) -> list[int]:
    """Index i -> byte offset where character i starts. Length len(text)+1."""
    out, n = [0], 0
    for ch in text:
        n += len(ch.encode("utf-8"))
        out.append(n)
    return out


def encode(l1: L1) -> tuple[bytes, list[int]]:
    """L1 -> (utf-8 bytes, one label id per byte).

    Overlapping spans would make this ill-defined; L1.validate() already forbids
    them, and a later span silently wins here if one ever slipped through.
    """
    raw = l1.text.encode("utf-8")
    tags = [LABEL2ID["O"]] * len(raw)
    c2b = char_to_byte_offsets(l1.text)

    for s in l1.spans:
        if s.start >= len(c2b) or s.end >= len(c2b):
            continue  # span points outside the text; validate() reports it
        b0, b1 = c2b[s.start], c2b[s.end]
        if b1 <= b0:
            continue
        tags[b0] = LABEL2ID[f"B-{s.type}"]
        for k in range(b0 + 1, b1):
            tags[k] = LABEL2ID[f"I-{s.type}"]
    return raw, tags


def decode(text: str, tags: list[int]) -> list[Span]:
    """Per-byte label ids -> character-offset spans.

    Tolerant of the label sequences a model actually emits, which are not always
    well-formed BIO: a bare I- with no B- before it opens a span rather than
    being dropped, because throwing away a confidently-tagged region for a
    formatting reason loses more than it protects.
    """
    raw = text.encode("utf-8")
    c2b = char_to_byte_offsets(text)
    b2c: dict[int, int] = {b: c for c, b in enumerate(c2b)}

    runs: list[tuple[str, int, int]] = []
    cur_type: str | None = None
    cur_start = 0

    for i in range(min(len(tags), len(raw))):
        lab = ID2LABEL.get(tags[i], "O")
        if lab == "O":
            if cur_type is not None:
                runs.append((cur_type, cur_start, i))
                cur_type = None
            continue
        pre, typ = lab.split("-", 1)
        if cur_type is None:
            cur_type, cur_start = typ, i
        elif pre == "B" or typ != cur_type:
            runs.append((cur_type, cur_start, i))
            cur_type, cur_start = typ, i
    if cur_type is not None:
        runs.append((cur_type, cur_start, min(len(tags), len(raw))))

    spans: list[Span] = []
    for typ, b0, b1 in runs:
        # Snap to character boundaries. A model can put a boundary mid-codepoint;
        # the IR cannot represent that, so widen outward to the nearest real one.
        while b0 > 0 and b0 not in b2c:
            b0 -= 1
        while b1 < len(raw) and b1 not in b2c:
            b1 += 1
        c0, c1 = b2c.get(b0), b2c.get(b1, len(text))
        if c0 is None or c1 <= c0:
            continue
        frag = text[c0:c1]
        if not frag.strip():
            continue
        # Trim whitespace the model included at either edge, keeping offsets true.
        lead = len(frag) - len(frag.lstrip())
        trail = len(frag) - len(frag.rstrip())
        spans.append(Span(i=len(spans), type=typ, start=c0 + lead,
                          end=c1 - trail, text=text[c0 + lead:c1 - trail]))
    return spans


def round_trip_ok(l1: L1) -> bool:
    """encode then decode reproduces the span set. Used by the tests."""
    raw, tags = encode(l1)
    got = decode(l1.text, tags)
    want = [(s.type, s.start, s.end) for s in l1.spans
            if l1.text[s.start:s.end].strip()]
    return [(s.type, s.start, s.end) for s in got] == want
