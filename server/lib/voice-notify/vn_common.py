"""Shared code for voice-notify / voice-questions (state in /var/lib/voice-questions/vq.db)."""
import hashlib, json, os, re, secrets, sqlite3, subprocess, time, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

os.umask(0o007)
DIR = os.environ.get("VN_DIR", "/var/lib/voice-questions")
TZ = ZoneInfo(os.environ.get("AGENT_TZ", "UTC"))   # owner time zone, e.g. America/New_York
OWNER_PHONE = os.environ.get("OWNER_PHONE", "+15555550100")        # texts/calls go here
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "owner@example.com")
# iMessage handles accepted from the Mac listener (comma-separated phone numbers / Apple ID emails)
OWNER_HANDLES = {h.strip() for h in os.environ.get("OWNER_HANDLES", f"{OWNER_PHONE},{OWNER_EMAIL}").split(",") if h.strip()}
CALL_REQ = os.environ.get("VN_CALLREQ", "/var/lib/voice-tasks/call-requests")
QUIET = os.environ.get("QUIET_HOURS", "23-7")
CAP_TEXT, CAP_CALL_IMPORTANT, CAP_CALL_URGENT = 40, 3, 5   # per local day (AGENT_TZ)
IMESSAGE = os.environ.get("VN_IMESSAGE", "/usr/local/bin/imessage-send")

SCHEMA = """
create table if not exists questions(id text primary key, text text, kind text, ref text, status text default 'open',
  created real, answered_at real, answer_text text, answer_via text, next_check real, meta text);
create table if not exists notifs(id text primary key, level text, text text, question_id text, created real,
  status text default 'queued', escalate_at real, escalated int default 0, detail text);
create table if not exists inbound(rowid_src integer primary key, ts real, text text, status text default 'new', handled real);
create table if not exists chat(n integer primary key autoincrement, ts real, role text, text text);
create table if not exists events(n integer primary key autoincrement, ts real, kind text, info text);
create table if not exists kv(k text primary key, v text);
"""


def now() -> float:
    return time.time()


def db() -> sqlite3.Connection:
    os.makedirs(DIR, exist_ok=True)
    c = sqlite3.connect(os.path.join(DIR, "vq.db"), timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        os.chmod(os.path.join(DIR, "vq.db"), 0o660)  # sqlite creates it 0644&~umask; the group must write
    except OSError:
        pass
    c.execute("pragma journal_mode=delete")
    c.executescript(SCHEMA)
    return c


def new_id(prefix="") -> str:
    return prefix + secrets.token_hex(2)


def quiet_now(t: float | None = None) -> bool:
    if QUIET == "off":
        return False
    a, b = (int(x) for x in QUIET.split("-"))
    h = datetime.fromtimestamp(t or now(), TZ).hour
    return (h >= a or h < b) if a > b else (a <= h < b)


def day_start(t: float | None = None) -> float:
    d = datetime.fromtimestamp(t or now(), TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.timestamp()


def count_today(c, kind: str) -> int:
    return c.execute("select count(*) from events where kind=? and ts>=?", (kind, day_start())).fetchone()[0]


def log_event(c, kind: str, info: str = "") -> None:
    c.execute("insert into events(ts,kind,info) values(?,?,?)", (now(), kind, info[:300]))


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())[:40]


def telegram(text: str) -> bool:
    """Plain Telegram message to the owner. Tries the helper's bot file, then the voice secrets."""
    srcs = []
    try:
        tok = None
        for l in open("/home/claude-helper/.claude/channels/telegram/.env"):
            if l.startswith("TELEGRAM_BOT_TOKEN="):
                tok = l.split("=", 1)[1].strip().strip("'\"")
        chat = json.load(open("/home/claude-helper/.claude/channels/telegram/access.json"))["allowFrom"][0]
        if tok:
            srcs.append((tok, chat))
    except Exception:
        pass
    try:
        e = {}
        for l in open("/etc/voice-caller/secrets.env"):
            if "=" in l:
                k, v = l.rstrip("\n").split("=", 1)
                e[k] = v.strip("'\"")
        srcs.append((e["TELEGRAM_BOT_TOKEN"], e["TELEGRAM_CHAT_ID"]))
    except Exception:
        pass
    for tok, chat in srcs:
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text[:3900]}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=20)
            return True
        except Exception:
            continue
    return False


def journal(text: str, qid: str) -> None:
    try:
        subprocess.run(["/usr/local/bin/voice-memory", "journal", "--source", "note", "--id", "q-" + qid, "--text", text],
                       capture_output=True, timeout=30)
    except Exception:
        pass


# ---------- questions ----------
def q_add(c, text, kind, ref=None, meta=None):
    """Create an open question. Same open ref -> returns the existing id (nothing is asked twice)."""
    if kind not in ("approve", "decide", "check"):
        raise ValueError("kind must be approve, decide or check")
    if ref:
        r = c.execute("select id from questions where ref=? and status='open'", (ref,)).fetchone()
        if r:
            return r["id"], False
    qid = new_id("q")
    t = now()
    c.execute("insert into questions(id,text,kind,ref,created,next_check,meta) values(?,?,?,?,?,?,?)",
              (qid, text[:600], kind, ref, t, t + 600, json.dumps(meta or {})))
    return qid, True


def q_answer(c, qid, via, text):
    """First answer wins. Returns ('ok'|'already'|'missing', row)."""
    qid = qid.strip().lower()
    cur = c.execute("update questions set status='answered', answered_at=?, answer_text=?, answer_via=?, next_check=null "
                    "where id=? and status='open'", (now(), text[:1000], via, qid))
    row = c.execute("select * from questions where id=?", (qid,)).fetchone()
    if row is None:
        return "missing", None
    if cur.rowcount == 1:
        log_event(c, "answered", f"{qid} via {via}")
        return "ok", row
    return "already", row


def q_self_close(c, qid, why):
    cur = c.execute("update questions set status='self', answered_at=?, answer_text=?, answer_via='self', next_check=null "
                    "where id=? and status='open'", (now(), why[:300], qid))
    if cur.rowcount == 1:
        row = c.execute("select * from questions where id=?", (qid,)).fetchone()
        journal(f"Owner handled this themselves ({why}): {row['text']}", qid)
        return True
    return False


def q_open(c):
    return c.execute("select * from questions where status='open' order by created").fetchall()


def chat_add(c, role, text):
    """Conversation memory. Skips a repeat of the same text (our own sends are seen twice: by the daemon and the Mac)."""
    n = norm(text)
    if not n:
        return
    for r in c.execute("select role,text,ts from chat order by n desc limit 15"):
        if role == "claude" and r["role"] == role and norm(r["text"]) == n and now() - r["ts"] < 600:
            return
    c.execute("insert into chat(ts,role,text) values(?,?,?)", (now(), role, text[:1500]))
