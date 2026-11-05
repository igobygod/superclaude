"""Shared helpers for voice-extras (runs as claude-helper). No secrets printed."""
import fcntl, json, os, pathlib, subprocess, time, urllib.parse, urllib.request, uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Pick up AGENT_TZ / OWNER_NAME / JOB_SEARCH_DIR even when run by hand (systemd already loads this file for the timer).
try:
    for _l in open("/etc/voice-caller/agent.env"):
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.rstrip("\n").split("=", 1); os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))
except OSError:
    pass
TZ_NAME = os.environ.get("AGENT_TZ", "UTC")
TZ = ZoneInfo(TZ_NAME)
OWNER_NAME = os.environ.get("OWNER_NAME", "the owner")
# Optional job-search helpers: folder ON THE MAC that holds the job-search system (PROGRESS.md, tracker.csv, applicant-profile.md). Empty = job-search helpers do nothing.
JOB_SEARCH_DIR = os.environ.get("JOB_SEARCH_DIR", "")
STATE = pathlib.Path("/var/lib/voice-extras")
TASKS = pathlib.Path("/var/lib/voice-tasks")
HOME = pathlib.Path.home()
DRY = os.environ.get("VOICE_EXTRAS_DRY") == "1"
CONF_FILE = STATE / "config.json"
DEFAULT_CONF = {
    "briefing_time": "08:00", "briefing_days": [0, 1, 2, 3, 4],   # Mon=0
    "scout_time": "07:20", "mailwatch_time": "09:00",
    "quiet_hours": "23-7", "max_proactive_calls_per_day": 3,
    "followup_days": 5, "patch_radar_hours": 6, "review_watch_hours": 3,
    "mac_projects": {"myapp": "~/Documents/MyApp"},   # ASSUMPTION: example project key -> Mac folder; edit in config.json
    "build_watch": {"enabled": False, "time": "02:30", "project": "myapp", "command": "xcodebuild -project MyApp.xcodeproj -scheme MyApp -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build"},
    "appstore_apps": [],   # [{"name":"My App","id":"123456789","country":"us"}]
    "games": [],   # e.g. [{"name": "Some Game", "steam": 12345}] (Steam app ids) for the patch radar
}

def conf():
    c = dict(DEFAULT_CONF)
    try:
        c.update(json.loads(CONF_FILE.read_text()))
    except Exception:
        pass
    return c

def now(): return datetime.now(TZ)

def load(name, default):
    try: return json.loads((STATE / name).read_text())
    except Exception: return default

def save(name, data):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / name; t = p.with_name(name + ".tmp")
    t.write_text(json.dumps(data, indent=1)); os.chmod(t, 0o660); t.replace(p)

class lock:
    def __init__(self, name): self.f = open(STATE / (name + ".lock"), "w")
    def __enter__(self): fcntl.flock(self.f, fcntl.LOCK_EX); return self
    def __exit__(self, *a): fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()

def _tg_creds():
    ch = HOME / ".claude/channels/telegram"
    tok = next(l.split("=", 1)[1].strip() for l in (ch / ".env").read_text().splitlines() if l.startswith("TELEGRAM_BOT_TOKEN="))
    return tok, json.loads((ch / "access.json").read_text())["allowFrom"][0]

def tg(text):
    """Telegram message to the owner only."""
    if DRY:
        print("[DRY telegram]", text); return True
    try:
        tok, chat = _tg_creds()
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
        return True
    except Exception as e:
        print("telegram failed:", type(e).__name__); return False

def quiet_now():
    q = conf()["quiet_hours"]
    if q == "off": return False
    a, b = (int(x) for x in q.split("-")); h = now().hour
    return (h >= a or h < b) if a > b else (a <= h < b)

def calls_today():
    d = load("calls.json", {})
    return d.get("n", 0) if d.get("day") == now().strftime("%F") else 0

def call_owner(reason, details="", urgent=False, proactive=True, telegram_text=None):
    """Request a call. Proactive calls respect the daily cap and quiet hours (-> Telegram only)."""
    reason, details = reason[:300], details[:1000]
    if proactive:
        if quiet_now() and not urgent:
            tg(telegram_text or f"{reason}\n{details}\n(quiet hours, no call)"); return "telegram-quiet"
        if calls_today() >= conf()["max_proactive_calls_per_day"]:
            tg(telegram_text or f"{reason}\n{details}\n(daily call limit reached, so no call)"); return "telegram-cap"
    if DRY:
        print("[DRY call]", json.dumps({"reason": reason, "details": details, "urgent": urgent})); return "dry"
    d = load("calls.json", {}); day = now().strftime("%F")
    d = {"day": day, "n": (d.get("n", 0) if d.get("day") == day else 0) + (1 if proactive else 0)}
    save("calls.json", d)
    f = TASKS / "call-requests" / f"extras-{uuid.uuid4().hex[:8]}.json"
    f.write_text(json.dumps({"reason": reason, "details": details, "urgent": bool(urgent)})); os.chmod(f, 0o660)
    return "called"

def ask_claude(prompt, model="sonnet", timeout=900, confirmed=False):
    """Run a task through the voice task queue (shares the 2-at-once limit and kill switch). Returns done dict."""
    if (TASKS / "STOP").exists(): return {"ok": False, "spoken": "kill switch on", "details": ""}
    if DRY and os.environ.get("VOICE_EXTRAS_NOCLAUDE") == "1":
        return {"ok": True, "spoken": "dry", "details": os.environ.get("VOICE_EXTRAS_FAKE", "")}
    tid = "x" + datetime.now().strftime("%m%d%H%M") + "-" + uuid.uuid4().hex[:4]
    q = TASKS / "queue" / f"{tid}.json"
    task = {"id": tid, "task": prompt, "model": model, "callback": False, "confirmed": confirmed}
    tmp = q.with_name(tid + ".tmp"); tmp.write_text(json.dumps(task)); os.chmod(tmp, 0o660); tmp.replace(q)
    done = TASKS / "done" / f"{tid}.json"; end = time.time() + timeout
    while time.time() < end:
        if done.exists():
            time.sleep(0.5); return json.loads(done.read_text())
        time.sleep(5)
    return {"ok": False, "spoken": "timed out waiting", "details": ""}

def mac(task, folder=None, secs=600):
    """Run a task on the owner's Mac via the task queue (mac-run)."""
    if (TASKS / "STOP").exists(): return {"ok": False, "spoken": "kill switch on", "details": ""}
    tid = "m" + datetime.now().strftime("%m%d%H%M") + "-" + uuid.uuid4().hex[:4]
    t = {"id": tid, "kind": "mac", "task": task, "timeout": secs, "callback": False}
    if folder: t["folder"] = folder
    q = TASKS / "queue" / f"{tid}.json"; tmp = q.with_name(tid + ".tmp")
    tmp.write_text(json.dumps(t)); os.chmod(tmp, 0o660); tmp.replace(q)
    done = TASKS / "done" / f"{tid}.json"; end = time.time() + secs + 400
    while time.time() < end:
        if done.exists():
            time.sleep(0.5); return json.loads(done.read_text())
        time.sleep(5)
    return {"ok": False, "spoken": "timed out waiting", "details": ""}

def extract_json(text):
    """First {...} or [...] block in text."""
    import re
    m = re.search(r"```json\s*(.*?)```", text, re.S)
    s = m.group(1) if m else text
    for o, c in (("{", "}"), ("[", "]")):
        i, j = s.find(o), s.rfind(c)
        if i != -1 and j > i:
            try: return json.loads(s[i:j + 1])
            except Exception: pass
    return None

def fetch(url, timeout=20):
    r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 voice-extras"})
    return urllib.request.urlopen(r, timeout=timeout).read().decode("utf-8", "replace")
