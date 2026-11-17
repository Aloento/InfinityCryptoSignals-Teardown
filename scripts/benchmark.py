#!/usr/bin/env python
"""
Null model: is the direction call worth anything?

For every real signal we keep the timestamp, the pair, the entry price, the
flip schedule and the TP geometry, and only randomise the DIRECTION (mirroring
the ladder around the entry price so the trade is a pure mirror image).

If the real stream is not clearly better than the mirrored streams, the
direction call carries no information — the PnL is just the geometry.

  python scripts/benchmark.py --channel 1622365719 --seeds 10
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as bt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
OUT = os.path.join(PROJ, "out")


def mirror(sig, rng, flip_prob=0.5):
    s = sig.copy()
    flip = rng.random(len(s)) < flip_prob
    newdir = np.where(flip, np.where(s["dir"] == "L", "S", "L"), s["dir"])
    for c in [f"tp{i}" for i in range(1, 7)] + ["sl"]:
        s[c] = np.where(flip, 2 * s["entry"] - s[c], s[c])
    s["dir"] = newdir
    return s


def summarise(tr):
    f = tr[tr["status"] == "filled"]
    return {
        "n": int(len(f)),
        "win_%": round(100 * (f["ret"] > 0).mean(), 3),
        "avg_%": round(100 * f["ret"].mean(), 5),
        "median_%": round(100 * f["ret"].median(), 5),
        "pf": round(f.loc[f["ret"] > 0, "ret"].sum() / abs(f.loc[f["ret"] < 0, "ret"].sum()), 3),
        "avg_tps": round(f["tps"].mean(), 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="1622365719")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--interval", default="1m")
    a = ap.parse_args()

    sig = pd.read_parquet(os.path.join(OUT, f"signals_{a.channel}.parquet"))
    cfg = bt.Cfg(entry="market", interval=a.interval, use_leverage=False,
                 fee_taker=0.0, fee_maker=0.0, slip_bps=0.0)

    rows = []
    for seed in range(a.seeds):
        rng = np.random.default_rng(seed)
        s = mirror(sig, rng)
        tr, _ = bt.run(a.channel, cfg, f"null_{seed}", sig=s)
        r = summarise(tr)
        r["seed"] = seed
        rows.append(r)
        print(f"seed {seed}: {r}", flush=True)

    d = pd.DataFrame(rows)
    base = pd.read_parquet(os.path.join(OUT, f"trades_{a.channel}_hl_nofee.parquet"))
    real = summarise(base)
    print("\nREAL (zero cost):", real)
    print("NULL mean avg_%:", round(d["avg_%"].mean(), 5), "std:", round(d["avg_%"].std(), 5),
          "range:", round(d["avg_%"].min(), 5), "..", round(d["avg_%"].max(), 5))
    pct = float((d["avg_%"] < real["avg_%"]).mean())
    print(f"real beats {pct*100:.0f}% of mirrored streams "
          f"(50% = no information, >80% = real edge)")

    d.to_csv(os.path.join(OUT, f"null_{a.channel}.csv"), index=False)
    with open(os.path.join(OUT, f"null_{a.channel}.json"), "w", encoding="utf-8") as f:
        json.dump({"real": real, "null": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
