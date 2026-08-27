"""Turning L1 rows into tensors, and building the training pool.

Training is on SYNTHETIC data only. The 407 human strings are the measuring
stick, not the training set -- 407 examples cannot train a tagger, and spending
them on training would leave nothing to find out whether it worked. Dev is what
gets watched during training; test is opened once, at the end.
"""

from __future__ import annotations

import random

import torch

from .ir import L1
from .tagging import PAD, BOS, EOS, STATUS2ID, encode

IGNORE = -100  # torch's cross-entropy sentinel for "no label here"


def encode_example(l1: L1, max_len: int = 192
                   ) -> tuple[list[int], list[int], int]:
    """L1 -> (input ids, tag ids, status id), unpadded, with BOS/EOS.

    BOS and EOS get IGNORE tags: there is nothing at those positions to label,
    and letting them contribute would teach the tagger to spend capacity on the
    two constant tokens in every sequence.
    """
    raw, tags = encode(l1)
    room = max_len - 2
    if len(raw) > room:
        raw, tags = raw[:room], tags[:room]
    ids = [BOS] + list(raw) + [EOS]
    lab = [IGNORE] + tags + [IGNORE]
    return ids, lab, STATUS2ID[l1.status]


def collate(batch: list[tuple[list[int], list[int], int]]
            ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Pad to the longest item in THIS batch, not to max_len.

    Most lines are ~40 bytes and the window is 192, so padding to the window
    would spend about four fifths of every forward pass on padding.
    """
    width = max(len(ids) for ids, _, _ in batch)
    x = torch.full((len(batch), width), PAD, dtype=torch.long)
    y = torch.full((len(batch), width), IGNORE, dtype=torch.long)
    s = torch.zeros(len(batch), dtype=torch.long)
    for i, (ids, lab, st) in enumerate(batch):
        x[i, :len(ids)] = torch.tensor(ids, dtype=torch.long)
        y[i, :len(lab)] = torch.tensor(lab, dtype=torch.long)
        s[i] = st
    return x, y, s


def build_pool(n_balanced: int, n_realistic: int, seed: int = 1337,
               max_len: int = 192) -> list[tuple[list[int], list[int], int]]:
    """Both profiles, mixed and shuffled.

    Balanced exists for class coverage -- it is the only place the model sees
    SatSun, or a count bound, or 127 different weekday combinations. Realistic
    exists so the priors are not wrong. Training on either alone gets one of
    those two things and misses the other, so it trains on both.
    """
    from .generate import generate

    rows = (generate(n_balanced, seed=seed, profile="balanced")
            + generate(n_realistic, seed=seed + 1, profile="realistic"))
    pool = [encode_example(L1.from_json(r["l1"]), max_len) for r in rows]
    random.Random(seed).shuffle(pool)
    return pool


def batches(pool: list, batch_size: int, rng: random.Random, shuffle: bool = True):
    """Length-bucketed batches, so a batch is mostly one width.

    Sorting by length inside a large chunk and batching within it keeps padding
    near zero without making batch composition deterministic across epochs.
    """
    idx = list(range(len(pool)))
    if shuffle:
        rng.shuffle(idx)
    chunk = batch_size * 32
    for c0 in range(0, len(idx), chunk):
        block = sorted(idx[c0:c0 + chunk], key=lambda i: len(pool[i][0]))
        groups = [block[b0:b0 + batch_size]
                  for b0 in range(0, len(block), batch_size)]
        if shuffle:
            rng.shuffle(groups)
        for g in groups:
            yield collate([pool[i] for i in g])
