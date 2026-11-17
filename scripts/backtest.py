#!/usr/bin/env python
"""
Simulate every signal as a trade and score the stream.

Rules reconstructed from the channel grammar:
  * entry      : market at the next candle open ("enter as soonest possible")
                 or limit at the advertised entry price, valid N hours
  * scale out  : 1/6 of size at TP1..TP6 (Target7 "🚀" = runner, no fixed level)
  * hard exit  : the next signal for the same pair (their real stop: opposite signal)
  * advertised stop loss is ±50% and never binds -> we measure it, then ignore it
  * liquidation: optional, isolated margin, maintenance margin `mmr`, checked on 1m lows/highs

Outputs out/trades_<channel>_<mode>.parquet and a summary on stdout.
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prices import Klines  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
OUT = os.path.join(PROJ, "out")

# tie-break priority inside one candle: flip at open happens before anything else
P_FLIP, P_LIQ, P_TP = 0, 1, 2


def sim_one(row, k, cfg, flip_ms):
    t = k["t"].to_numpy()
    o = k["o"].to_numpy()
    h = k["h"].to_numpy()
    l = k["l"].to_numpy()
    c = k["c"].to_numpy()
    if len(t) < 2:
        return None

    d = 1 if row.dir == "L" else -1
    if cfg.lev_override:
        lev = float(cfg.lev_override)
    elif cfg.use_leverage and not np.isnan(row.leverage):
        lev = float(row.leverage)
    else:
        lev = 1.0
    t0 = int(row.dt.timestamp() * 1000)

    i0 = int(np.searchsorted(t, t0, side="left"))
    if i0 >= len(t) - 1:
        return None

    # ---------------- entry ----------------
    if cfg.entry == "market":
        fill_i = i0
        fill = float(o[i0]) * (1 + d * cfg.slip_bps / 1e4)
    else:
        raw = float(row.entry)
        horizon = int(t0 + cfg.limit_hours * 3600_000)
        j_end = int(np.searchsorted(t, horizon, side="right"))
        j_end = min(max(j_end, i0 + 1), len(t))
        seg_l, seg_h = l[i0:j_end], h[i0:j_end]
        if d == 1:
            hit = np.nonzero(seg_l <= raw)[0]
        else:
            hit = np.nonzero(seg_h >= raw)[0]
        if len(hit) == 0:
            return {"status": "unfilled", "fill_dt": None, "ret": np.nan,
                    "hold_h": np.nan, "tps": 0, "reason": "no_fill", "mae": np.nan,
                    "mfe": np.nan, "fill": np.nan}
        fill_i = i0 + int(hit[0])
        fill = raw

    # a quoted entry that has nothing to do with the market is not executable
    if cfg.max_quote_gap and abs(fill / float(row.entry) - 1.0) > cfg.max_quote_gap:
        return {"status": "badquote", "fill": fill, "fill_dt": None, "exit_dt": None,
                "ret": np.nan, "ret_lev": np.nan, "hold_h": np.nan, "tps": 0,
                "reason": "badquote", "mae": np.nan, "mfe": np.nan, "liq": False}

    # ---------------- window ----------------
    end_i = len(t) - 1
    if flip_ms is not None and flip_ms > t0:
        j = int(np.searchsorted(t, flip_ms, side="left"))
        if j > fill_i:
            end_i = min(j, len(t) - 1)
    max_end = int(t[fill_i] + cfg.max_hold_days * 86_400_000)
    end_i = min(end_i, int(np.searchsorted(t, max_end, side="right")) - 1, len(t) - 1)
    if end_i <= fill_i:
        end_i = min(fill_i + 1, len(t) - 1)

    seg_h, seg_l, seg_o = h[fill_i:end_i + 1], l[fill_i:end_i + 1], o[fill_i:end_i + 1]
    n = len(seg_h)

    # ---------------- levels ----------------
    tps = []
    for i in range(1, 7):
        v = getattr(row, f"tp{i}", np.nan)
        if v is not None and not (isinstance(v, float) and np.isnan(v)) and v > 0:
            tps.append(float(v))

    if lev > 1:
        if d == 1:
            liq = fill * (1 - 1 / lev + cfg.mmr)
            liq_hit = np.nonzero(seg_l <= liq)[0]
        else:
            liq = fill * (1 + 1 / lev - cfg.mmr)
            liq_hit = np.nonzero(seg_h >= liq)[0]
        liq_i = int(liq_hit[0]) if len(liq_hit) else None
    else:
        liq, liq_i = None, None

    flip_price = float(seg_o[-1]) * (1 - d * cfg.slip_bps / 1e4)
    flip_i = n - 1

    # ---------------- per-part exits ----------------
    if cfg.no_partial or not tps:
        gross = d * (flip_price / fill - 1.0)
        r_un = gross - 2 * cfg.fee_taker
        r_mg = max(gross * lev - 2 * cfg.fee_taker * lev, -1.0)
        if liq_i is not None and liq_i <= flip_i:
            r_un = -1.0 / max(lev, 1e-9)
            r_mg = -1.0
        if d == 1:
            mae = float(np.min(seg_l) / fill - 1.0)
            mfe = float(np.max(seg_h) / fill - 1.0)
        else:
            mae = float(-np.max(seg_h) / fill + 1.0)
            mfe = float(-np.min(seg_l) / fill + 1.0)
        return {"status": "filled", "fill": fill,
                "fill_dt": pd.Timestamp(t[fill_i], unit="ms", tz="UTC"),
                "exit_dt": pd.Timestamp(t[end_i], unit="ms", tz="UTC"),
                "ret": r_un, "ret_lev": r_mg,
                "hold_h": (t[end_i] - t[fill_i]) / 3600_000, "tps": 0,
                "reason": "flip", "mae": mae, "mfe": mfe,
                "liq": bool(liq_i is not None and liq_i <= flip_i)}

    w = 1.0 / len(tps)
    frac = cfg.partial_frac  # 1.0 = each part full size of its share

    ret_unlev = 0.0
    ret_margin = 0.0
    n_tp = 0
    reasons = []

    for p in tps:
        if d == 1:      # long: target above -> high must reach it
            hit = np.nonzero(seg_h >= p)[0]
        else:           # short: target below -> low must reach it
            hit = np.nonzero(seg_l <= p)[0]
        tp_i = int(hit[0]) if len(hit) else None

        cands = [(flip_i, P_FLIP, flip_price, "flip")]
        if liq_i is not None:
            cands.append((liq_i, P_LIQ, liq, "liq"))
        if tp_i is not None:
            cands.append((tp_i, P_TP, p, "tp"))
        idx, _, px, why = min(cands, key=lambda x: (x[0], x[1]))

        if why == "liq":
            r_un = -1.0 / max(lev, 1e-9)          # margin wiped (approx, in notional terms)
            r_mg = -1.0
        else:
            gross = d * (px / fill - 1.0)
            if why == "tp":
                fee = cfg.fee_taker + cfg.fee_maker
                n_tp += 1
            else:
                fee = 2 * cfg.fee_taker
            r_un = gross - fee
            r_mg = max(gross * lev - fee * lev, -1.0)   # liquidation caps the loss
        reasons.append(why)
        ret_unlev += w * r_un
        ret_margin += w * r_mg

    # ---------------- excursions ----------------
    if d == 1:
        mae = float(np.min(seg_l) / fill - 1.0)
        mfe = float(np.max(seg_h) / fill - 1.0)
    else:
        mae = float(-np.max(seg_h) / fill + 1.0)
        mfe = float(-np.min(seg_l) / fill + 1.0)

    exit_idx = end_i
    main_reason = max(set(reasons), key=reasons.count) if reasons else "flip"

    return {
        "status": "filled",
        "fill": fill,
        "fill_dt": pd.Timestamp(t[fill_i], unit="ms", tz="UTC"),
        "exit_dt": pd.Timestamp(t[exit_idx], unit="ms", tz="UTC"),
        "ret": ret_unlev,
        "ret_lev": ret_margin,
        "hold_h": (t[exit_idx] - t[fill_i]) / 3600_000,
        "tps": n_tp,
        "reason": main_reason,
        "mae": mae,
        "mfe": mfe,
        "liq": bool(liq_i is not None and "liq" in reasons),
    }


def run(channel, cfg, tag, sig=None):
    if sig is None:
        sig = pd.read_parquet(os.path.join(OUT, f"signals_{channel}.parquet"))
    else:
        sig = sig.copy()
    sig = sig[(sig["pair"] != "") & sig["entry"].notna() & sig["dir"].notna()].copy()
    sig = sig.sort_values(["pair", "dt"]).reset_index(drop=True)

    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    sig["next_dt"] = sig.groupby("pair")["dt"].shift(-1)
    ks = Klines()

    rows = []
    missing = {}
    for r in sig.itertuples(index=False):
        next_ms = int(r.next_dt.timestamp() * 1000) if not pd.isna(r.next_dt) else now_ms
        next_ms = int(min(next_ms, now_ms))
        start = int(r.dt.timestamp() * 1000) - 60_000
        end = int(min(next_ms, now_ms)) + 3 * 60_000
        end = min(end, start + int(cfg.max_hold_days * 86_400_000) + 60_000)
        k = ks.get(r.pair, start, end, cfg.interval)
        if len(k) < 2:
            missing[r.pair] = missing.get(r.pair, 0) + 1
            rows.append({"id": r.id, "pair": r.pair, "dir": r.dir, "dt": r.dt, "status": "nodata",
                         "ret": np.nan, "ret_lev": np.nan, "hold_h": np.nan, "tps": 0,
                         "reason": "nodata", "mae": np.nan, "mfe": np.nan, "fill": np.nan,
                         "leverage": r.leverage, "entry_sig": r.entry, "sl": r.sl,
                         "tp1": r.tp1, "tp6": r.tp6, "fill_dt": None, "exit_dt": None, "liq": False})
            continue
        res = sim_one(r, k, cfg, next_ms)
        if res is None:
            continue
        res.update({"id": r.id, "pair": r.pair, "dir": r.dir, "dt": r.dt,
                    "leverage": r.leverage, "entry_sig": r.entry, "sl": r.sl,
                    "tp1": r.tp1, "tp6": r.tp6})
        rows.append(res)

    tr = pd.DataFrame(rows)
    tr["channel"] = channel
    tr["mode"] = cfg.entry
    tr.to_parquet(os.path.join(OUT, f"trades_{channel}_{tag}.parquet"), index=False)

    f = tr[tr["status"] == "filled"].copy()
    summ = {
        "channel": channel, "mode": tag, "interval": cfg.interval,
        "signals": int(len(tr)), "filled": int(len(f)),
        "unfilled": int((tr["status"] == "unfilled").sum()),
        "nodata": int((tr["status"] == "nodata").sum()),
        "badquote": int((tr["status"] == "badquote").sum()),
        "win_rate_%": round(100 * (f["ret"] > 0).mean(), 2) if len(f) else None,
        "avg_ret_%": round(100 * f["ret"].mean(), 4) if len(f) else None,
        "median_ret_%": round(100 * f["ret"].median(), 4) if len(f) else None,
        "avg_ret_lev_%": round(100 * f["ret_lev"].mean(), 3) if len(f) else None,
        "pf": round(f.loc[f["ret"] > 0, "ret"].sum() / abs(f.loc[f["ret"] < 0, "ret"].sum()), 3)
              if len(f) and (f["ret"] < 0).any() else None,
        "liq_rate_%": round(100 * f["liq"].mean(), 2) if len(f) else None,
        "avg_hold_h": round(f["hold_h"].mean(), 1) if len(f) else None,
        "avg_tps": round(f["tps"].mean(), 2) if len(f) else None,
    }
    print(json.dumps(summ, ensure_ascii=False, indent=2))
    if missing:
        top = sorted(missing.items(), key=lambda x: -x[1])[:10]
        print("no-data symbols:", top)
    return tr, summ


class Cfg:
    def __init__(self, entry="market", interval="1m", use_leverage=False, slip_bps=1.0,
                 fee_taker=0.0005, fee_maker=0.0002, limit_hours=24, max_hold_days=90,
                 mmr=0.004, partial_frac=1.0, lev_override=0.0, no_partial=False,
                 max_quote_gap=0.05):
        self.entry = entry
        self.interval = interval
        self.use_leverage = use_leverage
        self.slip_bps = slip_bps
        self.fee_taker = fee_taker
        self.fee_maker = fee_maker
        self.limit_hours = limit_hours
        self.max_hold_days = max_hold_days
        self.mmr = mmr
        self.partial_frac = partial_frac
        self.lev_override = lev_override
        self.no_partial = no_partial
        self.max_quote_gap = max_quote_gap


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--entry", default="market", choices=["market", "limit"])
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--leverage", action="store_true")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--lev", type=float, default=0.0, help="override leverage for all trades")
    ap.add_argument("--no-fees", action="store_true")
    ap.add_argument("--no-partial", action="store_true", help="no TP scale-outs, exit only on flip")
    ap.add_argument("--hold-days", type=float, default=90.0)
    ap.add_argument("--max-quote-gap", type=float, default=0.05)
    a = ap.parse_args()
    tag = a.tag or f"{a.entry}_{'lev'+str(int(a.lev)) if a.lev else ('axi' if a.leverage else 'x1')}_{a.interval}"
    cfg = Cfg(entry=a.entry, interval=a.interval, use_leverage=a.leverage, lev_override=a.lev)
    cfg.max_hold_days = a.hold_days
    cfg.max_quote_gap = a.max_quote_gap
    if a.no_partial:
        cfg.no_partial = True
    if a.no_fees:
        cfg.fee_taker = cfg.fee_maker = 0.0
        cfg.slip_bps = 0.0
    run(a.channel, cfg, tag)
