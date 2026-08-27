"""The byte-level tagger. Two heads, one for each judgement the model owns.

Everything structural stays in code. segment.py already decides how many events
a line holds (244/244 on dev), normalize.py builds L2, convert.py emits jCal --
all deterministic, all tested. Asking a model to relearn those would trade a
rule that is right for a rule that is usually right.

What the model owns is the part a lookup table structurally cannot do:

  Q1  is this a schedule at all, and if not, which kind of not
  Q2/Q3  where in the string is the title, and where is the temporal information

Head 1 is 4-way status over a pooled representation. Head 2 is per-byte BIO.
They share the trunk on purpose: whether "Sat" is a weekday is the same question
as whether the sentence is about scheduling, and separating them would make each
head relearn it.

Small by design. p95 of the corpus is 67 bytes and the longest human string is
112, so a 192-byte window is generous and the whole thing fits in a few million
parameters -- which is the point of a *tiny* language model.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import torch
import torch.nn as nn

from .tagging import N_LABELS, N_STATUSES, PAD, VOCAB


@dataclass
class Config:
    vocab: int = VOCAB
    d_model: int = 256
    n_layers: int = 4
    n_heads: int = 4
    d_ff: int = 640
    max_len: int = 192
    dropout: float = 0.1
    n_labels: int = N_LABELS
    n_statuses: int = N_STATUSES

    def to_json(self) -> dict:
        return asdict(self)


class ByteTagger(nn.Module):
    def __init__(self, cfg: Config | None = None):
        super().__init__()
        self.cfg = cfg or Config()
        c = self.cfg
        self.tok = nn.Embedding(c.vocab, c.d_model, padding_idx=PAD)
        self.pos = nn.Embedding(c.max_len, c.d_model)
        self.drop = nn.Dropout(c.dropout)
        layer = nn.TransformerEncoderLayer(  # norm_first disables nested tensor; fine
            d_model=c.d_model, nhead=c.n_heads, dim_feedforward=c.d_ff,
            dropout=c.dropout, activation="gelu", batch_first=True,
            norm_first=True)
        self.enc = nn.TransformerEncoder(layer, num_layers=c.n_layers)
        self.norm = nn.LayerNorm(c.d_model)
        self.tag_head = nn.Linear(c.d_model, c.n_labels)
        self.status_head = nn.Linear(c.d_model, c.n_statuses)
        self.apply(self._init)

    @staticmethod
    def _init(m: nn.Module) -> None:
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, std=0.02)

    def forward(self, ids: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """ids: (B, T) with BOS ... EOS, PAD-filled. Returns (tag_logits, status_logits).

        tag_logits is (B, T, n_labels) over the SAME positions as ids, so the
        caller strips BOS/EOS itself rather than this silently reindexing.
        """
        b, t = ids.shape
        pos = torch.arange(t, device=ids.device).unsqueeze(0).expand(b, t)
        h = self.drop(self.tok(ids) + self.pos(pos))
        pad_mask = ids.eq(PAD)
        h = self.enc(h, src_key_padding_mask=pad_mask)
        h = self.norm(h)
        # Status reads position 0 (BOS), which attends over the whole line and
        # is never masked. Mean-pooling would dilute it with padding.
        return self.tag_head(h), self.status_head(h[:, 0])

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())
