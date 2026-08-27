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


# A short letter run straight after digits belongs WITH those digits: "8am" is
# one token, "15th" is one token. Splitting them let the decoder label the two
# halves differently, which is how "walk the dog 8am" came out as DATE "8" plus
# TSTART "am". Letter-then-digit still splits, because "Mon12pm" has to.
_GLUED_SUFFIX = {"am", "pm", "nn", "mn", "a", "p", "h", "st", "nd", "rd", "th",
                 "hrs", "hr", "min", "mins", "m", "s"}


def chunks(text: str) -> list[tuple[int, int]]:
    """Character-space chunks a span boundary is allowed to fall on.

    A maximal run of letters, or of digits, or a single other character -- with
    the exception above, which keeps a unit suffix attached to its number. The
    letter/digit split is what lets "Mon12pm" separate without a space; 8 of the
    1188 gold spans need exactly that, and 99.3% of the rest land on whitespace.
    """
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isalpha():
            j = i
            while j < len(text) and text[j].isalpha():
                j += 1
        elif ch.isdigit():
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            k = j
            while k < len(text) and text[k].isalpha():
                k += 1
            if k > j and text[j:k].lower() in _GLUED_SUFFIX:
                j = k
        else:
            j = i + 1
        out.append((i, j))
        i = j
    return out


def decode_chunked(text: str, probs) -> list[Span]:
    """Decode per CHUNK instead of per byte, using the full probability matrix.

    Byte-level argmax has nothing forcing a span to be contiguous. In
    distribution the model learns coherence anyway; off distribution it falls
    apart into alternating labels inside one word -- "every other sunday"
    decoding as RECUR/SUMMARY/RECUR/SUMMARY letter by letter. That is not a
    training-time problem, it is a missing constraint at decode time.

    So every byte of a chunk votes, the chunk takes one label, and the B-vs-I
    call is left to the model: it is the only part of the decision the model is
    actually good at, and forcing adjacent same-type chunks to merge would fuse
    "Mon" and "Wed" into one span.

    probs: (n_bytes, N_LABELS), rows summing to 1.
    """
    c2b = char_to_byte_offsets(text)
    n = len(probs)
    chosen: list[tuple[int, int, str, bool]] = []

    for c0, c1 in chunks(text):
        b0, b1 = c2b[c0], min(c2b[c1], n)
        if b1 <= b0 or not text[c0:c1].strip():
            continue
        score: dict[str, float] = {}
        for lab, idx in LABEL2ID.items():
            typ = "O" if lab == "O" else lab.split("-", 1)[1]
            score[typ] = score.get(typ, 0.0) + sum(
                float(probs[k][idx]) for k in range(b0, b1))
        best = max(score, key=score.get)
        if best == "O":
            continue
        b_id, i_id = LABEL2ID[f"B-{best}"], LABEL2ID[f"I-{best}"]
        opens = float(probs[b0][b_id]) >= float(probs[b0][i_id])
        chosen.append((c0, c1, best, opens))

    spans: list[Span] = []
    for c0, c1, typ, opens in chosen:
        merge = (spans and not opens and spans[-1].type == typ
                 and not text[spans[-1].end:c0].strip())
        if merge:
            spans[-1] = Span(i=spans[-1].i, type=typ, start=spans[-1].start,
                             end=c1, text=text[spans[-1].start:c1])
        else:
            spans.append(Span(i=len(spans), type=typ, start=c0, end=c1,
                              text=text[c0:c1]))
    return spans
