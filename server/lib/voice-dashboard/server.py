#!/usr/bin/env python3
"""Private job dashboard for the voice assistant. 127.0.0.1:7893 behind Nginx /jobs/<token>/.
Read-only except: Stop (one running task), Stop all (STOP kill-switch file) and Resume (removes it)."""
import hmac, json, os, signal, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, "/usr/local/lib/voice-dashboard")
from dashlib import *

HERE = Path("/usr/local/lib/voice-dashboard")
TOKEN = Path("/run/voice-dashboard/token").read_text().strip()
assert len(TOKEN) >= 24
PREFIX = "/jobs/" + TOKEN


def state() -> dict:
    cancelled = set(jload(CANCELLED, []))
    plist = procs()
    rows, seen = [], set()
    for t in sorted(QUEUE.glob("*.json"), key=lambda f: f.stat().st_mtime):
        task = jload(t, {})
        rows.append({"id": task.get("id", t.stem), "voice": True, "status": "queued", "task": task.get("task", "")[:300],
                     "worker": task.get("kind", "claude"), "updates": [], "result": "", "stoppable": False,
                     "started": None, "seconds": None, "age": round(time.time() - t.stat().st_mtime)})
        seen.add("voice-" + task.get("id", t.stem))
    files = sorted(JOBS.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:40]
    for f in files:
        try:
            j = parse_job(f)
        except Exception:
            continue
        voice = f.stem.startswith("voice-")
        tid = f.stem[6:] if voice else None
        done = jload(DONE / f"{tid}.json") if voice else None
        run = RUNNING / f"{tid}.json" if voice else None
        status = classify(j["status_raw"], done, tid in cancelled, False)
        started, secs = None, None
        if done:
            secs = done.get("seconds")
            started = (done.get("finished") or 0) - (secs or 0)
        elif status == "running":
            started = (run.stat().st_mtime if run and run.exists() else j["mtime"])
            secs = round(time.time() - started)
        stoppable = bool(status == "running" and run and run.exists() and task_procs(jload(run, {}), plist))
        result = (done.get("spoken") if done else None) or j["result"] or (j["updates"][-1] if j["updates"] and status != "running" else "")
        rows.append({"id": tid or j["name"], "voice": voice, "status": status, "task": j["task"][:300], "worker": j["worker"],
                     "updates": j["updates"][-4:], "result": (result or "")[:500], "stoppable": stoppable,
                     "started": started, "seconds": secs, "age": round(time.time() - j["mtime"])})
    order = {"running": 0, "queued": 1}
    rows.sort(key=lambda r: (order.get(r["status"], 2), r["age"]))
    usage = jload(UD / "latest.json", {})
    return {"now": time.time(), "paused": STOP.exists(), "jobs": rows[:40], "calls": jload(UD / "calls.json", []),
            "usage": {"five_hour": usage.get("five_hour"), "week": usage.get("week"), "limits": usage.get("limits", []),
                      "ts": usage.get("ts"), "source": usage.get("source"), "error": usage.get("error")}}


def stop_one(tid: str) -> tuple[bool, str]:
    if not ID_RE.match(tid):
        return False, "bad id"
    run = RUNNING / f"{tid}.json"
    if not run.exists():
        return False, "not running"
    hits = task_procs(jload(run, {}))
    if not hits:
        return False, "no process found (the sweeper will clear it if it is stuck)"
    c = set(jload(CANCELLED, []))
    c.add(tid)
    jwrite(CANCELLED, sorted(c)[-200:])
    for pid, pg in hits:
        try:
            os.killpg(pg, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return True, "stopping"


class H(BaseHTTPRequestHandler):
    server_version = "x"
    sys_version = ""

    def log_message(self, *a):
        pass

    def send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        path = self.path.split("?", 1)[0]
        parts = path.split("/")  # ['', 'jobs', token, ...]
        if len(parts) < 3 or parts[1] != "jobs" or not hmac.compare_digest(parts[2], TOKEN):
            return None
        return "/" + "/".join(parts[3:])

    def do_GET(self):
        r = self.route()
        if r is None:
            return self.send(404, b"not found", "text/plain")
        if r in ("/", ""):
            html = (HERE / "index.html").read_text().replace("__PREFIX__", PREFIX)
            return self.send(200, html.encode(), "text/html; charset=utf-8")
        if r == "/app.js":
            return self.send(200, (HERE / "app.js").read_bytes(), "application/javascript")
        if r == "/app.css":
            return self.send(200, (HERE / "app.css").read_bytes(), "text/css")
        if r == "/api/state":
            return self.send(200, json.dumps(state()).encode())
        self.send(404, b"not found", "text/plain")

    def do_POST(self):
        r = self.route()
        if r is None:
            return self.send(404, b"not found", "text/plain")
        if self.headers.get("X-Dash") != "1":
            return self.send(403, b'{"ok":false,"msg":"forbidden"}')
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)) or b"{}")
        except Exception:
            body = {}
        if r == "/api/stop":
            ok, msg = stop_one(str(body.get("id", "")))
        elif r == "/api/stopall":
            STOP.write_text("stopped from the dashboard %s\n" % time.strftime("%F %T"))
            os.chmod(STOP, 0o660)
            ok, msg = True, "STOP file written: running tasks will be killed and none will start"
        elif r == "/api/resume":
            STOP.unlink(missing_ok=True)
            ok, msg = True, "resumed"
        else:
            return self.send(404, b"not found", "text/plain")
        self.send(200, json.dumps({"ok": ok, "msg": msg}).encode())


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 7893), H).serve_forever()
