#!/usr/bin/env python
"""
Turn raw channel JSONL into a structured signal table.

Classification is grammar-based (the poster uses a fixed template):
  SIGNAL        Pair + Direction + Entry  (+ leverage, targets, stop)
  SL_UPDATE     "Stop Loss: 123.4"  (replies to the signal; "Defined Later" case)
  TP_HIT        "Profit: 20% Target 1"
  CLOSE         "#BTC/USDT Closed due to opposite direction signal"
  FULL_CLOSE    "Fully close your previous LONG position"
  OTHER         everything else

Events are attached to signals primarily through the reply chain (reply_to),
with a per-symbol fallback when the poster forgot to reply.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
RAW = os.path.join(PROJ, "data", "raw")
OUT = os.path.join(PROJ, "out")

RE_PAIR = re.compile(r"Pair:\s*([A-Za-z0-9/_.\-]{2,24})")
RE_PAIR_HASH = re.compile(r"#([A-Z0-9]{2,20})[/\-_]?(USDT|USDC|BUSD|USD|PERP)?\b")
RE_DIR = re.compile(r"Direction:\s*(Long|Short|LONG|SHORT|Buy|Sell|BUY|SELL)")
RE_LEV = re.compile(r"Leverage:\s*(?:(Cross|Isolated|CROSS|ISOLATED)\s*)?([\d.]+)\s*[xX]")
RE_ENTRY = re.compile(r"Entry\s*:\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-~]\s*[0-9]+(?:\.[0-9]+)?)?)")
RE_TARGET = re.compile(r"Target\s*([1-9])\s*:\s*([0-9]+(?:\.[0-9]+)?)")
RE_SL = re.compile(r"Stop\s*-?\s*Loss\s*:\s*([0-9]+(?:\.[0-9]+)?|Defined\s*Later|Later|None|-|—)", re.I)
RE_PROFIT = re.compile(r"Profit:\s*([-+]?[0-9.,]+)\s*%\s*(?:Target\s*([1-9]))?", re.I)
# older era (2022-2023): "Take-Profit target 4 ✅ / Profit: 57.2253% 📈"
RE_TP_OLD = re.compile(r"Take-?Profit\s*target\s*([1-9])", re.I)
RE_CLOSED = re.compile(r"Closed\s+(?:due to|at|by)\s*([^\n]*)", re.I)
RE_FULLCLOSE = re.compile(r"Fully\s+close\s+your\s+previous\s+(LONG|SHORT)\s+position", re.I)
RE_CANCEL = re.compile(r"\b(cancel+ed|cancel+ing|invalid|expired)\b", re.I)
RE_TIME = re.compile(r"Time:\s*([0-9]+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?)", re.I)


def norm_pair(p: str) -> str:
    if not p:
        return ""
    s = p.upper().replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
    s = s.replace(".P", "")
    return s


def classify(text: str):
    if not text:
        return "OTHER"
    t = text
    if RE_FULLCLOSE.search(t):
        return "FULL_CLOSE"
    if "Pair:" in t and "Direction:" in t:
        return "SIGNAL"
    if "Pair:" in t and "Entry" in t:
        return "SIGNAL"
    if RE_PROFIT.search(t) and "Coin" in t:
        return "TP_HIT"
    if RE_PROFIT.search(t) and "Target" in t:
        return "TP_HIT"
    if RE_TP_OLD.search(t):
        return "TP_HIT"
    if RE_CLOSED.search(t):
        return "CLOSE"
    if RE_SL.search(t) and "Stop" in t and "Pair:" not in t:
        return "SL_UPDATE"
    if RE_CANCEL.search(t) and len(t) < 220 and ("#" in t or "cancel" in t.lower()):
        return "CANCEL"
    return "OTHER"


def parse_signal(text: str) -> dict:
    d = {}
    m = RE_PAIR.search(text)
    if m:
        d["pair_raw"] = m.group(1)
    else:
        m2 = RE_PAIR_HASH.search(text)
        d["pair_raw"] = m2.group(0) if m2 else ""
    d["pair"] = norm_pair(d.get("pair_raw", ""))

    m = RE_DIR.search(text)
    d["dir"] = {"long": "L", "buy": "L", "short": "S", "sell": "S"}.get(
        (m.group(1).lower() if m else ""), None)
    m = RE_LEV.search(text)
    if m:
        d["margin_mode"] = (m.group(1) or "").lower() or None
        d["leverage"] = float(m.group(2))
    else:
        d["margin_mode"] = None
        d["leverage"] = None

    m = RE_ENTRY.search(text)
    if m:
        raw = m.group(1)
        if re.search(r"[-~]", raw):
            a, b = re.split(r"\s*[-~]\s*", raw)
            d["entry_raw"] = raw
            d["entry_lo"], d["entry_hi"] = float(a), float(b)
            d["entry"] = (float(a) + float(b)) / 2
        else:
            v = float(raw)
            d["entry_raw"] = raw
            d["entry_lo"] = d["entry_hi"] = d["entry"] = v
    else:
        d["entry_raw"] = None
        d["entry"] = d["entry_lo"] = d["entry_hi"] = None

    tg = {}
    for n, v in RE_TARGET.findall(text):
        tg[int(n)] = float(v)
    for i in range(1, 8):
        d[f"tp{i}"] = tg.get(i)

    m = RE_SL.search(text)
    if m:
        raw = m.group(1)
        try:
            d["sl"] = float(raw)
        except ValueError:
            d["sl"] = None
        d["sl_raw"] = raw
    else:
        d["sl"] = None
        d["sl_raw"] = None
    return d


def load_channel(channel_id: str) -> pd.DataFrame:
    path = os.path.join(RAW, f"{channel_id}.jsonl")
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit(f"empty {path}")
    df = df.sort_values("id").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["date"], utc=True, format="ISO8601")
    df["channel"] = channel_id
    return df


def build(channel_id: str):
    df = load_channel(channel_id)
    df["kind"] = [classify(t) for t in df["text"].tolist()]
    print(f"[{channel_id}] messages={len(df)}", Counter(df["kind"]).most_common())

    sig_mask = df["kind"] == "SIGNAL"
    sigs = df[sig_mask].copy()
    parsed = [parse_signal(t) for t in sigs["text"].tolist()]
    pdf = pd.DataFrame(parsed)
    sigs = pd.concat([sigs.reset_index(drop=True), pdf.reset_index(drop=True)], axis=1)

    bad = sigs[(sigs["pair"] == "") | (sigs["entry"].isna()) | (sigs["dir"].isna())]
    if len(bad):
        print(f"  [warn] {len(bad)} signals failed basic parse; sample ids: {bad['id'].head(5).tolist()}")

    # events
    ev = df[df["kind"].isin(["TP_HIT", "CLOSE", "FULL_CLOSE", "SL_UPDATE", "CANCEL"])].copy()
    events = []
    for r in ev.itertuples(index=False):
        rec = {"ev_id": r.id, "ev_dt": r.dt, "ev_kind": r.kind, "reply_to": r.reply_to, "text": r.text}
        t = r.text
        if r.kind == "TP_HIT":
            mo = RE_TP_OLD.search(t)
            if mo and "Target" not in t:
                mm = RE_PROFIT.search(t)
                rec["profit_pct"] = float(mm.group(1).replace(",", "")) if mm else None
                rec["target_n"] = int(mo.group(1))
                mm2 = RE_PAIR_HASH.search(t)
                rec["pair"] = norm_pair(mm2.group(1) + (mm2.group(2) or "")) if mm2 else ""
                events.append(rec)
                continue
            m = RE_PROFIT.search(t)
            if m:
                rec["profit_pct"] = float(m.group(1).replace(",", ""))
                rec["target_n"] = int(m.group(2)) if m.group(2) else None
            else:
                rec["profit_pct"] = None
                rec["target_n"] = None
            mm = RE_PAIR_HASH.search(t)
            rec["pair"] = norm_pair(mm.group(1) + (mm.group(2) or "")) if mm else ""
        elif r.kind == "CLOSE":
            m = RE_CLOSED.search(t)
            rec["reason"] = (m.group(1).strip() if m else "")[:80]
            mm = RE_PAIR_HASH.search(t)
            rec["pair"] = norm_pair(mm.group(1) + (mm.group(2) or "")) if mm else ""
        elif r.kind == "FULL_CLOSE":
            m = RE_FULLCLOSE.search(t)
            rec["dir"] = "L" if (m and m.group(1).upper() == "LONG") else "S"
            mm = RE_PAIR_HASH.search(t)
            rec["pair"] = norm_pair(mm.group(1) + (mm.group(2) or "")) if mm else ""
        elif r.kind == "SL_UPDATE":
            m = RE_SL.search(t)
            rec["sl"] = None
            if m:
                try:
                    rec["sl"] = float(m.group(1))
                except ValueError:
                    pass
        events.append(rec)
    evdf = pd.DataFrame(events)

    os.makedirs(OUT, exist_ok=True)
    sigs.to_parquet(os.path.join(OUT, f"signals_{channel_id}.parquet"), index=False)
    evdf.to_parquet(os.path.join(OUT, f"events_{channel_id}.parquet"), index=False)
    df[["id", "dt", "kind", "text", "reply_to", "views", "edit_date"]].to_parquet(
        os.path.join(OUT, f"messages_{channel_id}.parquet"), index=False)

    print(f"  signals={len(sigs)} events={len(evdf)} {Counter(evdf['ev_kind']).most_common()}")
    print(f"  pairs={sigs['pair'].nunique()} dirs={Counter(sigs['dir']).most_common()} "
          f"leverage={Counter(sigs['leverage']).most_common(8)}")
    print(f"  date range {sigs['dt'].min()} .. {sigs['dt'].max()}")
    print(f"  edited={int(sigs['edit_date'].notna().sum())}")
    no_tp = int(sigs["tp1"].isna().sum())
    print(f"  without any target={no_tp}   sl 'defined later'={int((sigs['sl_raw']=='Defined Later').sum())}")
    return sigs, evdf, df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    a = ap.parse_args()
    build(a.channel)
