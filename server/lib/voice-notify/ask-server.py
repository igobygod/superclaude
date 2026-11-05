#!/usr/bin/env python3
"""'Ask Claude' endpoint for the iPhone shortcut. Listens on 127.0.0.1:7894 behind nginx at /ask/<token>.
POST (multipart form or JSON or plain text): fields text, url, file. Stores it as an inbound owner request for the
voice-notify daemon (same helper Claude path as the iMessage chat). Runs as claude-helper."""
import json, os, re, secrets, subprocess, sys, threading, time
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, "/usr/local/lib/voice-notify")
import vn_common as v, media

TOKEN = open("/etc/voice-ask/token").read().strip()
BEAT = open("/etc/voice-ask/beat-token").read().strip()
FILES = os.path.join(v.DIR, "ask-files")
MAX = 14 * 1024 * 1024


def store(c, text, url, files):
    rid = int(time.time() * 1000)  # unique id in the inbound table (iMessage rowids are small)
    parts = ["[ASK:shortcut] The owner sent this from their iPhone 'Ask Claude' shortcut."]
    if text:
        parts.append("Their words/shared text: " + text)
    if url:
        parts.append("Link they shared: " + url + " (open and read it yourself only if needed)")
    for fn, data in files:
        e = media.save(data, fn, "shortcut", text[:200])
        parts.append(f"[MEDIA:{e['type']}] {e['path']}")
    c.execute("insert into inbound(rowid_src,ts,text) values(?,?,?)", (rid, time.time(), "\n".join(parts)[:6000]))
    return rid



MAC = os.environ.get("WAKE_MAC", "YOU@192.168.1.50")   # Mac login: MAC_USER@MAC_LAN_IP (set WAKE_MAC)
KEYF = "/etc/mac-helpers/mac_key"
SSHO = ["ssh", "-i", KEYF, "-o", "SetEnv=LC_WAKE_LEASE_MIN=3", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=/etc/mac-helpers/known_hosts"]
WAKE_CMD = "~/bin/wake-lease 30 >/dev/null 2>&1; ~/bin/imessage-agent --poke"
WAKE = {"t": 0.0, "res": None, "busy": False, "hits": []}
WLOCK = threading.Lock()


def try_wake(tries: int) -> bool:
    """SSH wakes a sleeping Mac through the Apple TV (Sleep Proxy). Holds it awake 30 min and makes the listener scan right now."""
    for _ in range(tries):
        try:
            r = subprocess.run(SSHO + [MAC, WAKE_CMD], capture_output=True, text=True, timeout=25)
            if r.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(["ping", "-c", "2", "-W", "2", MAC.split("@")[-1]], capture_output=True)
        time.sleep(2)
    return False


def background_retry():
    ok = try_wake(20)  # up to ~2 min more
    if ok:
        v.telegram("Mac woke up a little late; Claude is awake now.")


def beat_age() -> float:
    r = v.db().execute("select v from kv where k='mac_beat'").fetchone()
    return time.time() - float(r["v"]) if r else 1e9


def poke_only() -> bool:
    try:
        return subprocess.run(SSHO + [MAC, "~/bin/imessage-agent --poke"], capture_output=True, text=True, timeout=25).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def wake(force: bool = False) -> tuple[bool, bool]:
    """(mac_reachable, cached). Rate limited: repeated taps within 20 s reuse the last answer; max 30 per hour."""
    with WLOCK:
        now = time.time()
        WAKE["hits"] = [t for t in WAKE["hits"] if now - t < 3600]
        if WAKE["res"] is not None and now - WAKE["t"] < (10 if force else 20):
            return WAKE["res"], True
        if len(WAKE["hits"]) >= 30:
            return bool(WAKE["res"]), True
        WAKE["hits"].append(now)
        ok = try_wake(2)
        WAKE["t"], WAKE["res"] = time.time(), ok
    if not ok:
        v.telegram("Wake Claude: your Mac can't be reached right now. Use Telegram for now. I'll keep trying for about 2 minutes and tell you if it comes back.")
        threading.Thread(target=background_retry, daemon=True).start()
    return ok, False


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self.reply(404, {"ok": False})

    def do_POST(self):
        p = self.path.rstrip("/")
        if secrets.compare_digest(p, "/beat/" + BEAT):  # the Mac listener says "awake" every ~30 s
            self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1000))
            v.db().execute("insert or replace into kv(k,v) values('mac_beat',?)", (str(time.time()),))
            return self.reply(200, {"ok": True})
        if secrets.compare_digest(p, "/wake/" + TOKEN) or secrets.compare_digest(p, "/force/" + TOKEN):
            force = p.startswith("/force/")
            self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10000))
            if not force and beat_age() < 60:   # smart wake: the Mac is already up, only trigger an immediate scan
                ok, text = poke_only() or True, "Claude is already awake"
                state = "already"
            else:
                ok, cached = wake(force)
                state = "woke" if ok else "unreachable"
                text = ("Mac awake" if force else "Woke Claude") if ok else "Mac unreachable, use Telegram"
            body = text.encode()
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.send_header("X-Wake", json.dumps({"ok": ok, "state": state}))
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if not secrets.compare_digest(self.path.rstrip("/"), "/ask/" + TOKEN):
            return self.reply(404, {"ok": False})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX:
            return self.reply(413, {"ok": False, "error": "too big"})
        body = self.rfile.read(n)
        ct = self.headers.get("Content-Type", "")
        text, url, files = "", "", []
        try:
            if ct.startswith("multipart/"):
                msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + ct.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
                for p in msg.iter_parts():
                    name, fn, data = p.get_param("name", header="content-disposition"), p.get_filename(), p.get_payload(decode=True) or b""
                    if fn and not (p.get_content_maintype() == "text" and name == "file" and len(data) < 8000):
                        files.append((fn, data))
                    else:
                        s = data.decode("utf8", "replace").strip()
                        if name == "url": url = s
                        elif s and s not in text: text = (text + "\n" + s).strip()
            elif ct.startswith("application/x-www-form-urlencoded"):
                from urllib.parse import parse_qs
                q = parse_qs(body.decode("utf8", "replace"))
                text, url = " ".join(q.get("text", [])).strip(), " ".join(q.get("url", [])).strip()
            elif "json" in ct:
                j = json.loads(body or b"{}"); text, url = str(j.get("text", "")).strip(), str(j.get("url", "")).strip()
            else:
                text = body.decode("utf8", "replace").strip()
        except Exception:
            return self.reply(400, {"ok": False, "error": "bad request"})
        sys.stderr.write(f"ask: ct={ct.split(';')[0]} len={n} text={len(text)} url={len(url)} files={len(files)}\n"); sys.stderr.flush()
        if not (text or url or files):
            return self.reply(400, {"ok": False, "error": "empty"})
        c = v.db()
        if c.execute("select count(*) from inbound where rowid_src>?", (int((time.time() - 3600) * 1000),)).fetchone()[0] >= 30:
            return self.reply(429, {"ok": False, "error": "slow down"})
        rid = store(c, text[:4000], url[:1000], files[:3])
        self.reply(200, {"ok": True, "id": rid})


ThreadingHTTPServer(("127.0.0.1", 7894), H).serve_forever()
