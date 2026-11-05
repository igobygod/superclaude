#!/usr/bin/env python3
"""voice-gemini-chat: holds the Gemini key; clients (voicetasks group) send one JSON line over a unix socket
{system, contents, tools?, max_tokens?, timeout?} (or {"op":"status"}) and get {ok, content, model, ms, tokens} back.
The key is never sent out. Models are tried in order of real availability: a model that answers 429/503/timeouts is put on cooldown;
at most 2 quick attempts (about 2.5 s each; longer when media is attached), then the caller falls back to Claude.
The text side has its own daily budget so the voice line's Gemini quota is never starved."""
import json, os, re, socket, threading, time, urllib.request, urllib.error
SOCK = "/run/voice-gemini-chat/chat.sock"
STATE = "/var/lib/voice-gemini-chat/usage.json"
API = "https://generativelanguage.googleapis.com/v1beta/models/"
CANDIDATES = ["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
DAILY = 300          # text-side requests per day (well under the free tier); Gemini Live (calls) is counted separately by voice-core
SOFT = 0.8           # above 80% of the budget: one attempt only
LOCK = threading.Lock()
MODEL = {m: {"cool": 0.0, "ok": 0, "fail": 0, "ms": 0.0, "think": "budget0"} for m in CANDIDATES}
DAY = {"day": "", "n": 0, "ok": 0, "fail": 0, "tokens": 0, "by_model": {}}


def key():
    for l in open("/etc/voice-caller/secrets.env"):
        if l.startswith("GEMINI_API_KEY="):
            return l.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("no key")


KEY = key()


def roll():
    today = time.strftime("%Y-%m-%d")
    if DAY["day"] != today:
        DAY.update({"day": today, "n": 0, "ok": 0, "fail": 0, "tokens": 0, "by_model": {}})
        try:
            s = json.load(open(STATE))
            if s.get("day") == today:
                DAY.update(s)
        except Exception:
            pass


def save():
    try:
        json.dump({**DAY, "models": {m: {"cooldown_s": max(0, int(v["cool"] - time.time())), "ok": v["ok"], "fail": v["fail"]} for m, v in MODEL.items()}}, open(STATE, "w"))
    except Exception:
        pass


def cooldown(m, code, body=""):
    d = 90
    if code == 429:
        d = 900
        mm = re.search(r"retry in ([\d.]+)s", body) or re.search(r'"retryDelay": "(\d+)s"', body)
        if mm:
            d = max(60, min(3600, int(float(mm.group(1)))))
    elif code == 404:
        d = 43200
    MODEL[m]["cool"] = time.time() + d


def order():
    now = time.time()
    live = [m for m in CANDIDATES if MODEL[m]["cool"] <= now]
    live.sort(key=lambda m: (MODEL[m]["ok"] == 0 and MODEL[m]["fail"] > 2, MODEL[m]["ms"] or 9999))
    if not live:  # everything cooling down: try the one that recovers first, once
        live = [min(CANDIDATES, key=lambda m: MODEL[m]["cool"])]
    return live


def attempt(m, body, timeout):
    body = json.loads(json.dumps(body))
    if MODEL[m]["think"] == "budget0":
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    r = urllib.request.Request(f"{API}{m}:generateContent", json.dumps(body).encode(), {"x-goog-api-key": KEY, "Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        d = json.loads(urllib.request.urlopen(r, timeout=timeout).read())
        return 200, d, int((time.time() - t0) * 1000), ""
    except urllib.error.HTTPError as e:
        return e.code, None, int((time.time() - t0) * 1000), re.sub(r"AIza[\w-]+", "***", e.read().decode(errors="replace")[:300])
    except Exception as e:
        return 0, None, int((time.time() - t0) * 1000), re.sub(r"AIza[\w-]+", "***", str(e))[:200]


def handle(req):
    with LOCK:
        roll()
        if req.get("op") == "status":
            return {"ok": True, "day": DAY, "daily_budget": DAILY, "models": {m: {"cooldown_s": max(0, int(v["cool"] - time.time())), "ok": v["ok"], "fail": v["fail"], "avg_ms": int(v["ms"])} for m, v in MODEL.items()}}
        if DAY["n"] >= DAILY:
            return {"ok": False, "error": "daily text budget reached"}
        DAY["n"] += 1
        soft = DAY["n"] > DAILY * SOFT
    body = {"system_instruction": {"parts": [{"text": str(req["system"])[:30000]}]}, "contents": req["contents"],
            "generationConfig": {"maxOutputTokens": int(req.get("max_tokens", 700)), "temperature": 0.5}}
    if req.get("tools"):
        body["tools"] = [{"function_declarations": req["tools"]}]
    timeout = float(req.get("timeout", 2.5))
    tried, errs, t0 = 0, [], time.time()
    for m in order():
        if tried >= (1 if soft else 2):
            break
        tried += 1
        code, d, ms, err = attempt(m, body, timeout)
        if code == 400 and "thinking" in err.lower() and MODEL[m]["think"] == "budget0":
            MODEL[m]["think"] = "none"  # this model rejects thinkingBudget: remember, retry once without it
            code, d, ms, err = attempt(m, body, timeout)
        with LOCK:
            v = MODEL[m]
            if code == 200 and d.get("candidates"):
                v["ok"] += 1; v["ms"] = ms if not v["ms"] else v["ms"] * 0.7 + ms * 0.3
                tok = d.get("usageMetadata", {})
                DAY["ok"] += 1; DAY["tokens"] += tok.get("totalTokenCount", 0)
                DAY["by_model"][m] = DAY["by_model"].get(m, 0) + 1
                save()
                c = d["candidates"][0]
                return {"ok": True, "content": c["content"], "finish": c.get("finishReason"), "model": m, "ms": int((time.time() - t0) * 1000),
                        "tokens": {"prompt": tok.get("promptTokenCount"), "total": tok.get("totalTokenCount")}, "attempts": tried}
            v["fail"] += 1
            cooldown(m, code, err)
        errs.append(f"{m}:{code or 'timeout'}")
    with LOCK:
        DAY["fail"] += 1
        save()
    return {"ok": False, "error": "no Gemini answer (" + ", ".join(errs) + ")"}


def serve(c):
    try:
        c.settimeout(60)
        buf = b""
        while not buf.endswith(b"\n") and len(buf) < 30000000:
            ch = c.recv(65536)
            if not ch:
                break
            buf += ch
        try:
            res = handle(json.loads(buf))
        except Exception as e:
            res = {"ok": False, "error": re.sub(r"AIza[\w-]+", "***", str(e))[:300]}
        c.sendall((json.dumps(res) + "\n").encode())
    finally:
        c.close()


os.makedirs(os.path.dirname(SOCK), exist_ok=True)
if os.path.exists(SOCK):
    os.unlink(SOCK)
s = socket.socket(socket.AF_UNIX)
s.bind(SOCK)
os.chown(SOCK, -1, __import__("grp").getgrnam(os.environ.get("SOCKET_GROUP", "voicetasks")).gr_gid)
os.chmod(SOCK, 0o660)
s.listen(8)
while True:
    c, _ = s.accept()
    threading.Thread(target=serve, args=(c,), daemon=True).start()
