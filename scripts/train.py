"""Train the byte tagger. This is M6.

  uv run python scripts/train.py                    # defaults, CPU-friendly
  uv run python scripts/train.py --epochs 8 --n 60000

Trains on synthetic only and watches dev, which is the split's whole purpose.
Test is not touched here and should not be until the thing is finished.

Scored every epoch against the same three questions as the rule baseline, using
the same scorer, so the numbers are directly comparable to TARGET.md rather than
being loss values nobody can interpret.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import random
import sys
import time

import torch
import torch.nn as nn

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stlm.data import IGNORE, batches, build_pool, encode_example
from stlm.infer import run as infer_run
from stlm.ir import L1, read_jsonl
from stlm.model import ByteTagger, Config
from stlm.normalize import l1_to_l2
from stlm.score import l2_exact_match, rrule_equivalence, span_prf

REF = dt.datetime(2026, 8, 27, 9, 0, 0)


def load_split(name: str) -> list[L1]:
    splits = json.loads((ROOT / "corpus" / "splits.json").read_text(encoding="utf-8"))
    want = set(splits[f"{name}_ids"])
    return [L1.from_json(r) for r in read_jsonl(ROOT / "corpus" / "gold_l1.jsonl")
            if r["id"] in want]


def evaluate(model, gold: list[L1], device: str) -> dict:
    """The three questions, scored exactly as eval_baseline.py scores them."""
    runs = [infer_run(model, g.text, ref=REF, device=device) for g in gold]

    pred_l1 = [r.l1 for r in runs]
    gold_sched = [g.status == "ok" for g in gold]
    pred_sched = [r.status == "ok" for r in runs]
    non = [i for i, s in enumerate(gold_sched) if not s]
    m = {
        "status_acc": sum(a == b.status for a, b in
                          zip((g.status for g in gold), runs)) / len(gold),
        "false_schedule": (sum(1 for i in non if pred_sched[i]) / len(non)
                           if non else 0.0),
    }
    spans = span_prf(gold, pred_l1)
    m["summary_f1"] = spans["per_type"].get("SUMMARY", {}).get("f1", 0.0)
    m["span_micro_f1"] = spans["micro"]["f1"]
    m["temporal_f1"] = spans["temporal_only"]["f1"]

    ok = [i for i, g in enumerate(gold) if g.status == "ok"]
    gl2 = [l1_to_l2(gold[i])[0] for i in ok]
    pl2 = [runs[i].l2 or l1_to_l2(runs[i].l1)[0] for i in ok]
    ex = l2_exact_match(gl2, pl2)
    rr = rrule_equivalence(gl2, pl2, REF)
    m["event_count"] = sum(
        1 for i in ok
        if len(gold[i].event_groups) == len(runs[i].l2.events if runs[i].l2 else [])
    ) / max(1, len(ok))
    m["temporal_exact"] = ex["temporal_exact_match"]
    m["whole_event_exact"] = ex["exact_match"]
    m["rrule_equiv"] = rr["occurrence_set_exact"]
    return m


def fmt(m: dict) -> str:
    return (f"status {m['status_acc']:.3f}  false-sched {m['false_schedule']:.3f}  "
            f"SUMMARY-F1 {m['summary_f1']:.3f}  count {m['event_count']:.3f}  "
            f"temporal {m['temporal_exact']:.3f}  rrule {m['rrule_equiv']:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=48000, help="balanced examples")
    ap.add_argument("--n-realistic", type=int, default=24000)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--status-weight", type=float, default=0.5)
    ap.add_argument("--d-model", type=int, default=256)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--out", default=str(ROOT / "checkpoints" / "tagger.pt"))
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    dev_gold = load_split("dev")

    print(f"device={args.device}  threads={torch.get_num_threads()}")
    print(f"building pool: {args.n} balanced + {args.n_realistic} realistic ...")
    pool = build_pool(args.n, args.n_realistic, seed=args.seed)
    # A held-out slice of SYNTHETIC data, which measures fit to the generator.
    # It is not a substitute for dev: a model can ace this and still fail on
    # anything a human wrote, which is precisely what happened to the rules.
    cut = int(len(pool) * 0.98)
    train_pool, syn_val = pool[:cut], pool[cut:]
    print(f"  {len(train_pool)} train / {len(syn_val)} synthetic-val")

    cfg = Config(d_model=args.d_model, n_layers=args.layers)
    model = ByteTagger(cfg).to(args.device)
    print(f"model: {model.n_params()/1e6:.2f}M params, {cfg.n_layers} layers, "
          f"d={cfg.d_model}")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01,
                            betas=(0.9, 0.98))
    tag_loss = nn.CrossEntropyLoss(ignore_index=IGNORE)
    st_loss = nn.CrossEntropyLoss()

    steps_per_epoch = math.ceil(len(train_pool) / args.batch_size)
    total = steps_per_epoch * args.epochs

    def lr_at(step: int) -> float:
        if step < args.warmup:
            return args.lr * step / max(1, args.warmup)
        p = (step - args.warmup) / max(1, total - args.warmup)
        return args.lr * 0.5 * (1 + math.cos(math.pi * min(1.0, p)))

    print(f"\nbaseline to beat (rules on dev): status 0.793  false-sched 1.000  "
          f"SUMMARY-F1 0.659  temporal 0.857\n")

    step = 0
    best = -1.0
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        model.train()
        t0, run_loss, seen = time.time(), 0.0, 0
        for x, y, s in batches(train_pool, args.batch_size, rng):
            x, y, s = x.to(args.device), y.to(args.device), s.to(args.device)
            for g in opt.param_groups:
                g["lr"] = lr_at(step)
            tl, sl = model(x)
            loss = (tag_loss(tl.reshape(-1, tl.size(-1)), y.reshape(-1))
                    + args.status_weight * st_loss(sl, s))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            run_loss += float(loss.detach()) * x.size(0)
            seen += x.size(0)
            step += 1
            if step % 200 == 0:
                print(f"  epoch {epoch} step {step}/{total} "
                      f"loss {run_loss/seen:.4f} lr {lr_at(step):.2e}", flush=True)

        # synthetic-val token accuracy: cheap, catches a broken training loop
        model.eval()
        corr = tot = st_corr = st_tot = 0
        with torch.no_grad():
            for x, y, s in batches(syn_val, args.batch_size, rng, shuffle=False):
                x, y, s = x.to(args.device), y.to(args.device), s.to(args.device)
                tl, sl = model(x)
                mask = y.ne(IGNORE)
                corr += int((tl.argmax(-1).eq(y) & mask).sum())
                tot += int(mask.sum())
                st_corr += int(sl.argmax(-1).eq(s).sum())
                st_tot += int(s.numel())

        m = evaluate(model, dev_gold, args.device)
        # One number to select on. Equal weight to the three questions, because
        # TARGET.md gates them independently and a model that aces two and fails
        # the third does not ship.
        sel = (m["status_acc"] + m["summary_f1"] + m["temporal_exact"]) / 3
        print(f"epoch {epoch}  loss {run_loss/seen:.4f}  "
              f"syn-tok {corr/max(1,tot):.4f} syn-status {st_corr/max(1,st_tot):.4f}  "
              f"[{time.time()-t0:.0f}s]")
        print(f"          DEV  {fmt(m)}   sel={sel:.4f}")

        if sel > best:
            best = sel
            torch.save({"state_dict": model.state_dict(), "config": cfg.to_json(),
                        "meta": {"epoch": epoch, "dev": m, "sel": sel,
                                 "args": vars(args)}}, out)
            print(f"          saved -> {out}")

    print(f"\nbest selection score {best:.4f}; checkpoint at {out}")


if __name__ == "__main__":
    main()
