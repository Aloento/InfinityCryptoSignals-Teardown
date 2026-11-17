#!/usr/bin/env python
"""
Bulk kline downloader using data.binance.vision (monthly/daily zips).

Much faster than REST pagination and not rate limited. Writes the same cache
format as prices.Klines: data/klines/<interval>/<SYMBOL>.parquet  (t,o,h,l,c,v)

  python scripts/bulk.py --symbols BTCUSDT,ETHUSDT --interval 1m --start 2022-08
  python scripts/bulk.py --from-signals 1617718235 --interval 15m
"""

import argparse
import io
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CACHE = os.path.join(PROJ, "data", "klines", "src")
OUT = os.path.join(PROJ, "out")

BASE = "https://data.binance.vision/data/futures/um"
SPOT = "https://data.binance.vision/data/spot"

_S = requests.Session()
_S.headers.update({"User-Agent": "tg-signal-backtest/1.0"})

COLS = ["t", "o", "h", "l", "c", "v"]


def month_list(start: str, end: str):
    y0, m0 = map(int, start.split("-"))
    y1, m1 = map(int, end.split("-"))
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def fetch_zip(url, retries=5):
    for i in range(retries):
        try:
            r = _S.get(url, timeout=90)
            if r.status_code == 200:
                return r.content
            if r.status_code in (403, 429, 503, 500):
                time.sleep(1.5 * (i + 1) ** 2)
                continue
            return None
        except Exception:
            time.sleep(1.5 * (i + 1) ** 2)
    return None


def parse_zip(raw, interval):
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        return None
    name = zf.namelist()[0]
    with zf.open(name) as f:
        head = f.readline().decode("utf-8", "ignore")
        skip = 1 if head.startswith("open_time") or head[0].isalpha() else 0
    df = pd.read_csv(io.BytesIO(raw), compression="zip", header=0 if skip else None,
                     usecols=range(6), names=COLS if not skip else None)
    if skip:
        df.columns = COLS
    df = df[df["t"].astype(str).str.isdigit()]
    t = df["t"].astype("int64")
    # some dumps use microseconds
    if t.max() > 10**15:
        t = t // 1000
    df["t"] = t
    for c in ["o", "h", "l", "c", "v"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna()


def job(symbol, ym, interval, market):
    base = BASE if market == "um" else SPOT
    tag = "futures/um" if market == "um" else "spot"
    url = f"https://data.binance.vision/data/{tag}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
    raw = fetch_zip(url)
    if raw is None:
        return symbol, ym, None
    return symbol, ym, parse_zip(raw, interval)


def daily_fill(symbol, interval, start_day, end_day, market):
    tag = "futures/um" if market == "um" else "spot"
    d = start_day
    frames = []
    while d <= end_day:
        url = (f"https://data.binance.vision/data/{tag}/daily/klines/{symbol}/{interval}/"
               f"{symbol}-{interval}-{d}.zip")
        raw = fetch_zip(url)
        if raw:
            df = parse_zip(raw, interval)
            if df is not None and len(df):
                frames.append(df)
        d = (datetime.strptime(d, "%Y-%m-%d") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return pd.concat(frames) if frames else None


def save(symbol, interval, df):
    p = os.path.join(PROJ, "data", "klines", interval, f"{symbol}.parquet")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        old = pd.read_parquet(p)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df.to_parquet(p, index=False)
    return len(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--from-signals", default=None)
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--start", default="2022-08")
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m"))
    ap.add_argument("--market", default="um", choices=["um", "spot"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-existing", action="store_true")
    a = ap.parse_args()

    ranges = {}
    if a.symbols:
        syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    elif a.from_signals:
        sig = pd.read_parquet(os.path.join(OUT, f"signals_{a.from_signals}.parquet"))
        sig = sig[sig["pair"].astype(str).str.len() > 0]
        g = sig.groupby("pair")["dt"].agg(["min", "max"])
        syms = sorted(g.index.tolist())
        for pair, row in g.iterrows():
            ranges[pair] = (row["min"].strftime("%Y-%m"), row["max"].strftime("%Y-%m"))
        a.start = max(a.start, sig["dt"].min().strftime("%Y-%m"))
    else:
        raise SystemExit("need --symbols or --from-signals")

    cur = datetime.now(timezone.utc)
    last_ym = f"{cur.year:04d}-{cur.month:02d}"

    total_months = 0
    for s_ in syms:
        st, en = ranges.get(s_, (a.start, a.end))
        total_months += len(month_list(st, en))
    print(f"{len(syms)} symbols, {total_months} symbol-months @ {a.interval} (market={a.market})")
    t0 = time.time()
    missing = []
    for si, s in enumerate(syms, 1):
        st, en = ranges.get(s, (a.start, a.end))
        months = month_list(st, en)
        todo = [m for m in months if m != last_ym]
        frames = []
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = [ex.submit(job, s, m, a.interval, a.market) for m in todo]
            for f in as_completed(futs):
                _s, m, df = f.result()
                if df is None or df.empty:
                    missing.append((s, m))
                else:
                    frames.append(df)
        start_day = cur.strftime("%Y-%m-01")
        try:
            dnl = daily_fill(s, a.interval, start_day, cur.strftime("%Y-%m-%d"), a.market)
            if dnl is not None and len(dnl):
                frames.append(dnl)
        except Exception:
            pass
        if not frames:
            print(f"  [{si}/{len(syms)}] [empty] {s}", flush=True)
            continue
        df = pd.concat(frames, ignore_index=True)
        n = save(s, a.interval, df)
        print(f"  [{si}/{len(syms)}] {s}: {len(df):,} new rows -> {n:,} cached "
              f"({time.time()-t0:.0f}s)", flush=True)
        del frames, df

    if missing:
        ms = sorted({m for _, m in missing})
        print(f"missing months: {ms[:12]}{'...' if len(ms) > 12 else ''}")


if __name__ == "__main__":
    main()
