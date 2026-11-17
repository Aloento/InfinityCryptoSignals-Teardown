#!/usr/bin/env python
"""
Full-history scraper for a Telegram channel -> JSONL.

Resumable: re-running continues from the oldest id already stored.
Every stored line is one message with the fields we later need for parsing
and for deletion accounting.

  python scripts/scrape.py --channel 1622365719
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

from telethon import TelegramClient, functions
from telethon.tl.types import PeerChannel

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

RAW_DIR = os.path.join(PROJ, "data", "raw")
LOG_DIR = os.path.join(PROJ, "out")


def ser_date(d):
    return d.isoformat() if isinstance(d, datetime) else None


def serialize(m):
    rec = {
        "id": m.id,
        "date": ser_date(m.date),
        "edit_date": ser_date(getattr(m, "edit_date", None)),
        "text": m.text or "",
        "post": bool(getattr(m, "post", False)),
        "views": getattr(m, "views", None),
        "forwards": getattr(m, "forwards", None),
        "grouped_id": getattr(m, "grouped_id", None),
        "reply_to": getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None),
        "via_bot_id": getattr(m, "via_bot_id", None),
        "from_id": None,
        "media": None,
        "action": None,
    }
    fid = getattr(m, "from_id", None)
    if fid is not None:
        rec["from_id"] = getattr(fid, "user_id", None) or getattr(fid, "channel_id", None)
    act = getattr(m, "action", None)
    if act is not None:
        rec["action"] = type(act).__name__
    if getattr(m, "photo", None) is not None:
        rec["media"] = "photo"
    elif getattr(m, "document", None) is not None:
        rec["media"] = "document"
    elif getattr(m, "web_preview", None) is not None:
        rec["media"] = "web"
    fwd = getattr(m, "fwd_from", None)
    if fwd is not None:
        rec["fwd_from"] = {
            "channel_id": getattr(fwd, "from_id", None) and getattr(getattr(fwd, "from_id", None), "channel_id", None),
            "name": getattr(fwd, "from_name", None),
            "date": ser_date(getattr(fwd, "date", None)),
        }
    if getattr(m, "entities", None):
        rec["entities"] = [type(e).__name__ for e in m.entities]
    if getattr(m, "buttons", None):
        rec["buttons"] = [[getattr(b, "text", None) for b in row] for row in m.buttons]
    return rec


async def scrape(channel_id: int, limit: int | None = None, wait_time: float = 1.0,
                 session: str = "aloento"):
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    out_path = os.path.join(RAW_DIR, f"{channel_id}.jsonl")

    # resume point: smallest id already written
    have = set()
    resume_id = 0
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    mid = json.loads(line)["id"]
                    have.add(mid)
                    if resume_id == 0 or mid < resume_id:
                        resume_id = mid
                except Exception:
                    continue

    client = TelegramClient(os.path.join(PROJ, "session", session), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("session not authorized - run scripts/login.py first")

    peer = PeerChannel(channel_id)
    ent = await client.get_entity(peer)
    total = None
    try:
        hist = await client(functions.messages.GetHistoryRequest(
            peer=ent, offset_id=0, offset_date=None, add_offset=0,
            limit=1, max_id=0, min_id=0, hash=0))
        total = hist.count
    except Exception as e:
        print(f"[warn] count failed: {e}", flush=True)

    print(f"[start] {getattr(ent,'title',channel_id)} total={total} resume_from_id={resume_id} "
          f"have={len(have)}", flush=True)

    n = 0
    t0 = time.time()
    last_log = 0.0
    kwargs = dict(limit=limit, wait_time=wait_time, reverse=False)
    if resume_id:
        kwargs["offset_id"] = resume_id

    with open(out_path, "a", encoding="utf-8") as f:
        async for m in client.iter_messages(ent, **kwargs):
            if m.id in have:
                continue
            f.write(json.dumps(serialize(m), ensure_ascii=False) + "\n")
            n += 1
            have.add(m.id)
            if n % 200 == 0:
                f.flush()
                now = time.time()
                if now - last_log > 5:
                    last_log = now
                    rate = n / max(1e-9, now - t0)
                    print(f"[progress] +{n} last_id={m.id} rate={rate:.0f}/s "
                          f"elapsed={(now-t0)/60:.1f}min", flush=True)
        f.flush()

    print(f"[done] wrote {n} new messages in {(time.time()-t0)/60:.1f} min -> {out_path}", flush=True)
    await client.disconnect()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--wait-time", type=float, default=1.0)
    ap.add_argument("--session", type=str, default="aloento")
    a = ap.parse_args()
    asyncio.run(scrape(a.channel, a.limit, a.wait_time, a.session))
