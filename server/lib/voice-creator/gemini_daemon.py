#!/usr/bin/env python3
"""voice-gemini daemon: holds the Gemini key; clients send {file,prompt,model} over a unix socket and get text back.
The key is never sent to clients. Files must live in /var/lib/voice-creator/media. Limit 40 requests/day."""
import os, sys, json, socket, time, re, threading, urllib.request, urllib.error, mimetypes
MEDIA = "/var/lib/voice-creator/media/"
SOCK = "/run/voice-gemini/gemini.sock"
STATE = "/var/lib/voice-creator/gemini-usage.json"
API = "https://generativelanguage.googleapis.com"
MODELS = {"flash": "gemini-3.8-flash", "pro": "gemini-3.1-pro-preview", "lite": "gemini-3.5-flash-lite"}
DAILY = 40

def key():
    for l in open("/etc/voice-caller/secrets.env"):
        if l.startswith("GEMINI_API_KEY="):
            return l.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("no key")
KEY = key()

def call(url, data=None, headers=None, method=None, timeout=120):
    h = {"x-goog-api-key": KEY}; h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=timeout)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()

def budget():
    today = time.strftime("%Y-%m-%d")
    try: s = json.load(open(STATE))
    except Exception: s = {}
    if s.get("day") != today: s = {"day": today, "n": 0}
    if s["n"] >= DAILY: return False
    s["n"] += 1; json.dump(s, open(STATE, "w")); return True

def upload(path):
    size = os.path.getsize(path)
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    st, hd, body = call(API + "/upload/v1beta/files", json.dumps({"file": {"display_name": os.path.basename(path)}}).encode(),
        {"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(size),
         "X-Goog-Upload-Header-Content-Type": mime, "Content-Type": "application/json"}, "POST")
    hd = {k.lower(): v for k, v in hd.items()}
    up = hd.get("x-goog-upload-url")
    if not up: raise RuntimeError(f"upload start failed {st}: {body[:200]!r}")
    with open(path, "rb") as f: data = f.read()
    st, _, body = call(up, data, {"Content-Length": str(size), "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"}, "POST", 600)
    if st != 200: raise RuntimeError(f"upload failed {st}: {body[:200]!r}")
    f = json.loads(body)["file"]
    for _ in range(60):
        if f.get("state") == "ACTIVE": return f, mime
        if f.get("state") == "FAILED": raise RuntimeError("Gemini could not process the file")
        time.sleep(3)
        st, _, body = call(f"{API}/v1beta/{f['name']}")
        f = json.loads(body)
    raise RuntimeError("file processing timed out")

def handle(req):
    p = os.path.realpath(req.get("file", ""))
    if not p.startswith(MEDIA) or not os.path.isfile(p): return {"ok": False, "error": "file must be inside " + MEDIA}
    prompt = str(req.get("prompt", ""))[:4000] or "Describe this video and list the best moments with timestamps."
    model = MODELS.get(req.get("model", "flash"), MODELS["flash"])
    if not budget(): return {"ok": False, "error": f"daily limit of {DAILY} requests reached"}
    f, mime = upload(p)
    try:
        body = {"contents": [{"parts": [{"file_data": {"mime_type": mime, "file_uri": f["uri"]}}, {"text": prompt}]}]}
        chain = [model] + [m for m in ("gemini-3.5-flash", "gemini-3.6-flash") if m != model]
        for attempt in range(4):
            m = chain[min(attempt, len(chain) - 1)] if attempt else model
            st, _, out = call(f"{API}/v1beta/models/{m}:generateContent", json.dumps(body).encode(), {"Content-Type": "application/json"}, "POST", 600)
            if st == 200: model = m; break
            if st in (429, 500, 503) and attempt < 3: time.sleep(10); continue
            return {"ok": False, "error": f"Gemini {st}: " + re.sub(r"AIza[\w-]+", "***", out.decode(errors="replace")[:300])}
        d = json.loads(out)
        try: txt = "".join(x.get("text", "") for x in d["candidates"][0]["content"]["parts"])
        except Exception: return {"ok": False, "error": "no answer (blocked or empty)"}
        return {"ok": True, "text": txt, "model": model}
    finally:
        call(f"{API}/v1beta/{f['name']}", method="DELETE")

def serve(c):
    try:
        c.settimeout(900)
        buf = b""
        while not buf.endswith(b"\n") and len(buf) < 20000: 
            ch = c.recv(4096)
            if not ch: break
            buf += ch
        try: res = handle(json.loads(buf))
        except Exception as e: res = {"ok": False, "error": re.sub(r"AIza[\w-]+", "***", str(e))[:300]}
        c.sendall((json.dumps(res) + "\n").encode())
    finally: c.close()

os.makedirs(os.path.dirname(SOCK), exist_ok=True)
if os.path.exists(SOCK): os.unlink(SOCK)
s = socket.socket(socket.AF_UNIX); s.bind(SOCK); os.chown(SOCK, -1, __import__("grp").getgrnam(os.environ.get("SOCKET_GROUP", "voicetasks")).gr_gid); os.chmod(SOCK, 0o660); s.listen(4)
while True:
    c, _ = s.accept(); threading.Thread(target=serve, args=(c,), daemon=True).start()
