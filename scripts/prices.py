#!/usr/bin/env python
"""
Binance kline cache.

  ks = Klines()
  df = ks.get("BTCUSDT", start_ms, end_ms, "1m")   # fetches only what's missing

Layout: data/klines/<interval>/<SYMBOL>.parquet   columns: t,o,h,l,c,v  (t = open ms, UTC)
Falls back to spot if the symbol is not on USD-M futures.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CACHE = os.path.join(PROJ, "data", "klines")

FAPI = "https://fapi.binance.com/fapi/v1/klines"
SAPI = "https://api.binance.com/api/v3/klines"

STEP_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
           "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

_S = requests.Session()
_S.headers.update({"User-Agent": "tg-signal-backtest/1.0"})

_lock = threading.Lock()
_rate = {"t": 0.0, "n": 0.0}
RATE_PER_SEC = 8.0


def _throttle():
    with _lock:
        now = time.time()
        if _rate["t"] == 0:
            _rate["t"] = now
        _rate["n"] += 1
        expected = _rate["t"] + _rate["n"] / RATE_PER_SEC
        if now < expected:
            time.sleep(expected - now)


def _fetch_page(url, symbol, interval, start, limit=1500):
    for attempt in range(6):
        _throttle()
        try:
            r = _S.get(url, params={"symbol": symbol, "interval": interval,
                                    "startTime": start, "limit": limit}, timeout=20)
            if r.status_code == 200:
                return r.json(), None
            if r.status_code in (418, 429):
                wait = 15 * (attempt + 1)
                print(f"[rate] {r.status_code} sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return None, r.json().get("msg", "bad request")
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            time.sleep(2 * (attempt + 1))
            err = str(e)
            if attempt == 5:
                return None, err
    return None, "gave up"


def _market_of(symbol):
    """'fapi' | 'spot' | None - cached on disk."""
    p = os.path.join(CACHE, "_markets.json")
    import json
    try:
        with open(p, "r", encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        m = {}
    if symbol in m:
        return m[symbol]
    rows, err = _fetch_page(FAPI, symbol, "1m", int(time.time() * 1000) - 3600_000, 1)
    if rows is not None:
        m[symbol] = "fapi"
    else:
        rows2, err2 = _fetch_page(SAPI, symbol, "1m", int(time.time() * 1000) - 3600_000, 1)
        m[symbol] = "spot" if rows2 is not None else None
    os.makedirs(CACHE, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f)
    return m[symbol]


def _to_df(rows):
    if not rows:
        return pd.DataFrame(columns=["t", "o", "h", "l", "c", "v"])
    df = pd.DataFrame([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                       for r in rows], columns=["t", "o", "h", "l", "c", "v"])
    return df


class Klines:
    def __init__(self, cache_dir=CACHE, offline=True):
        self.cache_dir = cache_dir
        self.offline = offline
        self._memo = {}

    def _path(self, symbol, interval):
        return os.path.join(self.cache_dir, interval, f"{symbol}.parquet")

    def _load(self, symbol, interval):
        key = (symbol, interval)
        if key in self._memo:
            return self._memo[key]
        p = self._path(symbol, interval)
        if os.path.exists(p):
            df = pd.read_parquet(p)
        else:
            df = pd.DataFrame(columns=["t", "o", "h", "l", "c", "v"])
        self._memo[key] = df
        return df

    def _save(self, symbol, interval, df):
        p = self._path(symbol, interval)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
        df.to_parquet(p, index=False)
        self._memo[(symbol, interval)] = df

    def get(self, symbol, start_ms, end_ms, interval="1m"):
        step = STEP_MS[interval]
        start_ms = int(start_ms // step * step)
        end_ms = int(end_ms // step * step)
        df = self._load(symbol, interval)

        need_fetch = False
        if not len(df):
            need_fetch = True
        else:
            tv = df["t"].values
            if start_ms < tv[0] or end_ms > tv[-1] + step:
                need_fetch = True

        if need_fetch and not self.offline:
            self._fetch(symbol, interval, start_ms, end_ms)
            df = self._load(symbol, interval)

        if not len(df):
            return df
        tv = df["t"].values
        i0 = int(np.searchsorted(tv, start_ms, "left"))
        i1 = int(np.searchsorted(tv, end_ms, "right"))
        return df.iloc[i0:i1]

    # ---------------- network (only used when offline=False) ----------------
    def _fetch(self, symbol, interval, start_ms, end_ms):
        step = STEP_MS[interval]
        mkt = _market_of(symbol)
        if mkt is None:
            return
        url = FAPI if mkt == "fapi" else SAPI
        cur = start_ms
        chunks = []
        while cur <= end_ms:
            rows, err = _fetch_page(url, symbol, interval, cur)
            if not rows:
                break
            d = _to_df(rows)
            d = d[d["t"] <= end_ms]
            if not len(d):
                break
            chunks.append(d)
            last = int(d["t"].iloc[-1])
            cur = last + step
            if len(rows) < 1500:
                break
        if chunks:
            df = chunks[0] if len(chunks) == 1 else pd.concat(chunks, ignore_index=True)
            self._save(symbol, interval, pd.concat([self._load(symbol, interval), df], ignore_index=True)
                       if len(self._load(symbol, interval)) else df)


if __name__ == "__main__":
    import sys
    ks = Klines()
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    now = int(time.time() * 1000)
    d = ks.get(sym, now - 6 * 3600_000, now, "1m")
    print(sym, len(d), "candles")
    print(d.tail(3).to_string())
