#!/usr/bin/env python
"""
Telegram QR login helper.

Serves a local page (http://127.0.0.1:PORT/) that always shows a FRESH
Telegram QR token, so the person just scans it with the Telegram app.

  Phone: Settings -> Devices -> Link Desktop Device -> scan the screen.

On success the MTProto session is written to ../session/aloento.session and
reusable by every other script in this project (no second login).

2FA: if the account has a cloud password, scanning still authorises the
device; in the rare case Telegram asks for the password the page shows a
password field and posts it straight to this process.
"""

import asyncio
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import qrcode
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

# Telegram Desktop's public API credentials - the usual pragmatic choice for
# personal MTProto tooling. Swap for your own from my.telegram.org if you like.
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

PORT = int(os.environ.get("QR_PORT", "8765"))
STATE_FILE = os.path.join(PROJ, "out", "login_state.json")

STATE = {
    "stage": "starting",     # starting | qr | password | done | error | already
    "url": None,
    "png": None,
    "seq": 0,
    "expires": 0,
    "message": "",
    "error": None,
    "me": None,
}
LOCK = threading.Lock()
PW = {"value": None, "seq": 0}


def render_png(data: str) -> bytes:
    qr = qrcode.QRCode(border=2, box_size=8, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>Telegram 登录 · tg-signal-backtest</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root{color-scheme:dark}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      background:#0f1115;color:#e6e9ef;font:15px/1.55 -apple-system,Segoe UI,Roboto,"Helvetica Neue",Arial,"Noto Sans SC",sans-serif}
 .card{width:420px;max-width:92vw;background:#161a21;border:1px solid #242a35;border-radius:14px;padding:26px 26px 22px;
       box-shadow:0 12px 40px rgba(0,0,0,.45)}
 h1{font-size:16px;margin:0 0 4px;font-weight:600;letter-spacing:.2px}
 .sub{color:#8b95a7;font-size:12.5px;margin-bottom:18px}
 .qrbox{background:#fff;border-radius:10px;padding:10px;display:flex;justify-content:center;align-items:center;min-height:272px}
 .qrbox img{width:252px;height:252px;display:block;image-rendering:pixelated}
 ol{margin:16px 0 0;padding-left:18px;color:#c3cad8;font-size:13px}
 ol li{margin:5px 0}
 code{background:#0c0f14;border:1px solid #242a35;border-radius:5px;padding:1px 5px;font-size:12px}
 .st{margin-top:14px;font-size:12.5px;color:#8b95a7;min-height:18px}
 .ok{color:#4ade80}.warn{color:#fbbf24}.err{color:#f87171}
 form{margin-top:14px;display:none}
 input{width:100%;padding:9px 11px;border-radius:8px;border:1px solid #2c3442;background:#0c0f14;color:#e6e9ef;font-size:14px}
 button{margin-top:8px;width:100%;padding:9px;border-radius:8px;border:0;background:#2f6feb;color:#fff;font-size:14px;cursor:pointer}
</style></head>
<body><div class="card">
  <h1>Telegram 设备授权</h1>
  <div class="sub">扫码即完成登录，密码不会被写入本页之外的任何地方</div>
  <div class="qrbox"><img id="qr" alt="QR"></div>
  <form id="pwf"><input id="pw" type="password" placeholder="两步验证密码（如果要求）" autocomplete="off"><button>提交</button></form>
  <ol>
    <li>手机 Telegram → 设置 → 设备 → <b>关联桌面设备</b></li>
    <li>对准此二维码扫描并确认</li>
    <li>本页会自动跳转成 ✅，无需其他操作</li>
  </ol>
  <div class="st" id="st">正在连接 Telegram…</div>
</div>
<script>
let seq=0, have=false;
async function tick(){
  try{
    const r=await fetch('/state.json?_='+Date.now()); const s=await r.json();
    if(s.stage==='done'){document.getElementById('st').innerHTML='<span class="ok">授权成功 ✅ 可以关掉这个页面了</span>';return;}
    if(s.stage==='error'){document.getElementById('st').innerHTML='<span class="err">'+(s.error||'出错了')+'</span>';return;}
    if(s.stage==='password'){document.getElementById('pwf').style.display='block';
      document.getElementById('st').innerHTML='<span class="warn">'+s.message+'</span>';}
    if(s.stage==='qr'){
      if(s.seq!==seq){seq=s.seq;document.getElementById('qr').src='/qr.png?seq='+s.seq;}
      const left=Math.max(0,Math.round(s.expires-Date.now()/1000));
      document.getElementById('st').textContent='二维码有效，剩余 '+left+' 秒（自动刷新）';
    }
  }catch(e){}
  setTimeout(tick, 2000);
}
tick();
document.getElementById('pwf').addEventListener('submit', async (ev)=>{
  ev.preventDefault();
  const pw=document.getElementById('pw').value;
  if(!pw) return;
  await fetch('/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pw})});
  document.getElementById('pw').value='';
  document.getElementById('st').textContent='校验中…';
});
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the console clean
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif p == "/qr.png":
            with LOCK:
                png = STATE["png"]
            if png:
                self._send(200, png, "image/png")
            else:
                self._send(404, "no qr yet", "text/plain")
        elif p == "/state.json":
            with LOCK:
                s = {
                    "stage": STATE["stage"],
                    "seq": STATE["seq"],
                    "expires": STATE["expires"],
                    "message": STATE["message"],
                    "error": STATE["error"],
                    "me": STATE["me"],
                }
            self._send(200, json.dumps(s))
        else:
            self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if self.path.startswith("/password"):
            try:
                pw = json.loads(raw.decode() or "{}").get("pw")
            except Exception:
                pw = None
            if pw:
                PW["value"] = pw
                PW["seq"] += 1
            self._send(200, json.dumps({"ok": bool(pw)}))
        else:
            self._send(404, "{}")


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


def set_state(**kw):
    with LOCK:
        STATE.update(kw)
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({k: STATE[k] for k in ("stage", "seq", "expires", "message", "error", "me")}, f)
    except Exception:
        pass


async def main():
    os.makedirs(os.path.join(PROJ, "session"), exist_ok=True)
    client = TelegramClient(os.path.join(PROJ, "session", "aloento"), API_ID, API_HASH,
                            device_model="Desktop", system_version="Windows 10",
                            app_version="1.0", lang_code="en", system_lang_code="en")
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        set_state(stage="done", message="already authorized", me={"id": me.id, "username": me.username})
        print("ALREADY_AUTHORIZED", me.id, me.username, flush=True)
        await client.disconnect()
        return

    qr = await client.qr_login()
    png = render_png(qr.url)
    set_state(stage="qr", png=png, seq=STATE["seq"] + 1, url=qr.url,
              expires=int(qr.expires.timestamp()))
    print(f"QR_PAGE_READY http://127.0.0.1:{PORT}/", flush=True)

    pw_seen = 0
    while True:
        try:
            await qr.wait(timeout=18)
            break
        except asyncio.TimeoutError:
            pass
        except SessionPasswordNeededError:
            set_state(stage="password", message="账号开启了两步验证，请输入密码")
            print("PASSWORD_NEEDED", flush=True)
            while PW["seq"] == pw_seen:
                await asyncio.sleep(0.4)
            pw_seen = PW["seq"]
            try:
                await client.sign_in(password=PW["value"])
                break
            except PasswordHashInvalidError:
                set_state(stage="password", message="密码不对，再试一次", error="PasswordHashInvalid")
                continue
        except PhoneNumberInvalidError as e:  # pragma: no cover - defensive
            set_state(stage="error", error=str(e))
            raise
        if qr.expires and qr.expires.timestamp() < time.time() + 1:
            await qr.recreate()
            png = render_png(qr.url)
            set_state(stage="qr", png=png, seq=STATE["seq"] + 1, url=qr.url,
                      expires=int(qr.expires.timestamp()))

    if not await client.is_user_authorized():
        await client.sign_in()  # no-op guard

    me = await client.get_me()
    info = {"id": me.id, "username": me.username, "first_name": me.first_name,
            "phone": ("+" + me.phone) if me.phone else None}
    set_state(stage="done", message="authorized", me=info)
    print("AUTHORIZED", json.dumps(info, ensure_ascii=False), flush=True)
    await client.disconnect()


if __name__ == "__main__":
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(0.4)
    try:
        asyncio.run(main())
    except Exception as e:
        set_state(stage="error", error=f"{type(e).__name__}: {e}")
        print("ERROR", type(e).__name__, e, flush=True)
        sys.exit(1)
