#!/usr/bin/env python3
"""voice-memory: the owner's memory for the voice line and the Claude helper.

Plain JSON/Markdown files in /var/lib/voice-memory (readable by the owner):
  facts.json        canonical owner profile (source, confidence, expiry, private tag)
  profile-full.md   readable view of every fact with its tags
  journal.jsonl     dated entries per call / task / Mac session (+ journal/YYYY-MM.md views)
  promises.json     open promises and follow-ups
  goals.json        short goal list
  people.json       people <-> companies <-> calls / tasks / emails
  proposals.json    things learned but NOT saved until the owner confirms
  questions.json    at most one question per day for the owner
  mistakes.json     mistake log; rules.md = the rules learned from it
Generated views: /var/lib/voice-tasks/profile.md (public facts, for the voice line) and
helper notes/USER.md (all facts incl. private, Claude only; syncs to the Mac).

Commands (exit 0, plain text): context, recall, brief, journal, remember, plus sync,
promise, goal, people, confirm, reject, question, answer, nightly, weekly, backfill,
mac-ingest, llm-serve.
"""
import argparse, shlex, datetime as dt, fcntl, hashlib, json, os, re, secrets, socket, subprocess, sys, threading, time
import urllib.parse, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

E = os.environ.get
BASE = Path(E("VM_BASE", "/var/lib/voice-memory"))
TASKS = Path(E("VM_TASKS", "/var/lib/voice-tasks"))
INBOX = Path(E("VM_INBOX", str(TASKS / "memory-inbox")))
PROFILE_MD = Path(E("VM_PROFILE_MD", str(TASKS / "profile.md")))
HELPER = Path(E("VM_HELPER", "/home/claude-helper"))
USER_MD = Path(E("VM_USER_MD", str(HELPER / "assistant/notes/USER.md")))
HELPER_MEMORY = HELPER / "assistant/notes/MEMORY.md"
SKILLS = HELPER / ".claude/skills"
CALLS = Path(E("VM_CALLS", "/var/lib/voicecaller/calls.jsonl"))
EMAILS = Path(E("VM_EMAILS", os.environ.get("EMAIL_QUEUE", "/var/lib/voice-email/kept-for-caller.jsonl")))
CLAUDE = E("VM_CLAUDE", str(HELPER / ".local/bin/claude"))
LLM_CMD = E("VM_LLM_CMD")          # tests: a fake command that reads the prompt on stdin
LLM_SOCK = Path(E("VM_LLM_SOCK", str(BASE / "llm.sock")))
TG_ENV = Path(E("VM_TG_ENV", str(HELPER / ".claude/channels/telegram/.env")))
TG_ACCESS = TG_ENV.parent / "access.json"
TZ = ZoneInfo(os.environ.get("AGENT_TZ", "UTC"))   # owner time zone, e.g. America/New_York

USER_CAP = 3000      # helper rule: notes/USER.md under 3000 characters
PROFILE_CAP = 5000   # agent.py cuts profile.md at 6000
CONTEXT_CAP = 2500
SECTION_ORDER = ["About the owner", "Identity", "Work and job search", "Writing style", "Key people",
                 "Preferences", "Devices and setup", "Learned on calls", "Private"]
LEARNED = "Learned on calls"
PRIVATE_HDR = "Private (Claude only; never give to the voice line)"

PRIVATE_RX = re.compile(
    r"\b(immigra\w*|visa|permit|residen(cy|t status)|sponsor\w*|citizenship|"
    r"national id|tax id|id number|passport|date of birth|DOB|(?<!job )bank\w*|account (no|number)|credit|debit|debt|"
    r"loan|mortgage|salary|income|wage|pay ?stub|tax(es)?|money|savings|invest\w*|crypto|rent\b)|\$\s?\d", re.I)
# Same unsafe-text checks as the helper's scan-memory (anything flagged is never written to a loaded file).
UNSAFE = [re.compile(x, re.I | re.S) for x in [
    r"(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|earlier|above|all|your|system)\b.{0,30}\b(instructions?|rules?|prompts?|guidelines?)",
    r"(\byou are now\b|\bnew instructions\b|\bsystem prompt\b|\bdeveloper message\b|<\s*/?\s*system\b)",
    r"\b(send|post|upload|forward|exfiltrate|email|leak)\b.{0,60}\b(passwords?|tokens?|secrets?|credentials?|cookies?|api[ _-]?keys?|\.env)\b",
    r"\b(curl|wget)\b[^\n]{0,200}\|\s*(sudo\s+)?(ba|z)?sh\b",
    r"(\.ssh/|id_ed25519|\.credentials\.json|channels/telegram/\.env|/etc/voice-caller|/etc/nginx)",
    r"\b(do not|don't|never|without)\b.{0,20}\b(tell|telling|inform|informing|mention|mentioning|notify|notifying|alert|alerting)\b.{0,30}\b(the )?(owner|user)\b",
    r"<!--", "[​‌‍⁠⁢⁣⁤﻿‪-‮⁦-⁩\U000e0000-\U000e007f]",
    r"[A-Za-z0-9+/]{200,}={0,2}",
    r"(\bsk-[A-Za-z0-9_-]{20,}|\b\d{6,}:[A-Za-z0-9_-]{30,}|\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{30,}|\b(password|passwd|api[ _-]?key|secret)\s*[:=]\s*\S{6,})"]]
REDACT_RX = re.compile(r"\b(\d{3}[- ]?\d{3}[- ]?\d{3}|[A-Z]{1,2}\d{6,8}|\d{8,})\b")  # national-ID/passport/account-like numbers
STOP = set("""a an and are as at be been but by can could did do does for from had has have how i i'm if in into is it its
me my of on or our so than that the their them then there these they this to was we were what when where which who whom
why will with would you your about any anything did tell said say know remember ask asked please just like get got""".split())

# ---------------------------------------------------------------- helpers
def now(): return time.time()
def today(): return dt.datetime.now(TZ).date()
def iso(ts=None): return dt.datetime.fromtimestamp(ts or now(), TZ).strftime("%Y-%m-%d")
def when(ts): return dt.datetime.fromtimestamp(ts, TZ).strftime("%b %-d %H:%M")
def nid(p): return p + secrets.token_hex(3)
def clean(s, n=None):
    s = " ".join(str(s or "").split())
    return s[:n] if n else s
def norm(s):
    s = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", str(s))
    return re.sub(r"[^a-z0-9@.]+", " ", s.lower()).strip()
def words(s): return {w for w in norm(s).split() if len(w) > 2 and w not in STOP}
def similar(a, b):
    A, B = words(a), words(b)
    return bool(A and B) and len(A & B) / len(A | B) >= 0.8
def unsafe(text): return any(r.search(text or "") for r in UNSAFE)
def is_private(text): return bool(PRIVATE_RX.search(text or ""))
def redact(text): return REDACT_RX.sub("[hidden]", text or "")

def load(name, default):
    p = BASE / name
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, ValueError):
        return default
    except PermissionError:
        return default

def save(name, data):
    p = BASE / name
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o660)
    os.replace(tmp, p)

def write_text(p, text):
    """Rewrite in place (keeps owner, group and mode; other writers append to these files)."""
    p = Path(p)
    if p.exists():
        with open(p, "r+") as f:
            if f.read() == text:
                return False
            f.seek(0); f.write(text); f.truncate()
    else:
        p.write_text(text)
        os.chmod(p, 0o660)
    return True

class Lock:
    def __enter__(self):
        self.f = open(BASE / ".lock", "a+")
        try: os.chmod(BASE / ".lock", 0o660)
        except PermissionError: pass
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self
    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()

def writable():
    try:
        return os.access(BASE, os.W_OK) and (not (BASE / "facts.json").exists() or os.access(BASE / "facts.json", os.W_OK))
    except OSError:
        return False

def spool(op, args):
    """Fallback when the caller cannot write /var/lib/voice-memory (e.g. a sandboxed service)."""
    INBOX.mkdir(exist_ok=True)
    p = INBOX / f"{int(now()*1000)}-{secrets.token_hex(3)}.json"
    tmp = INBOX / f".{p.name}.tmp"
    tmp.write_text(json.dumps({"op": op, "args": args, "time": now()}))
    os.chmod(tmp, 0o660)
    os.replace(tmp, p)
    return p

def read_jsonl(p, limit=None):
    out = []
    try:
        with open(p) as f:
            for line in f:
                try: out.append(json.loads(line))
                except ValueError: pass
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return []
    return out[-limit:] if limit else out

def log(msg):
    try:
        with open(BASE / "memory.log", "a") as f:
            f.write(f"{dt.datetime.now(TZ):%Y-%m-%d %H:%M} {msg}\n")
    except OSError:
        pass

# ---------------------------------------------------------------- LLM (Claude Haiku on the Max plan)
def _run_claude(prompt, timeout, model="haiku", tools=None):
    if LLM_CMD:
        cmd = shlex.split(LLM_CMD)
    else:
        cmd = [CLAUDE, "-p", "--model", model, "--no-session-persistence"]
        if tools:   # read-only MCP use: everything that writes, sends or deletes is denied outright
            deny = [f"mcp__claude_ai_Gmail__{t}" for t in ("send_message", "reply", "forward", "create_draft", "update_draft",
                    "delete_draft", "trash_message", "trash_thread", "delete_label", "create_label", "update_label",
                    "label_message", "label_thread", "unlabel_message", "unlabel_thread", "update_message_labels",
                    "mark_message_spam", "mark_thread_spam", "unmark_message_spam", "unmark_thread_spam",
                    "untrash_message", "untrash_thread", "apply_sensitive_message_label", "apply_sensitive_thread_label")]
            cmd += ["--permission-mode", "default", "--tools", "", "--allowedTools", *tools, "--disallowedTools", *deny]
        else:
            cmd += ["--tools", "", "--setting-sources", "", "--strict-mcp-config"]
    cwd = BASE / "llm-cwd"
    cwd.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(HELPER)) if not LLM_CMD else None
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-300:])
    return r.stdout.strip()

def llm(prompt, timeout=12, model="haiku", tools=None):
    """Return model text or None. claude-helper runs claude directly; other users go through llm.sock."""
    try:
        if LLM_CMD or os.access(CLAUDE, os.X_OK):
            return _run_claude(prompt, timeout, model, tools)
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout + 3)
            s.connect(str(LLM_SOCK))
            s.sendall(json.dumps({"prompt": prompt, "timeout": timeout, "model": model}).encode() + b"\n")
            s.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := s.recv(65536):
                data += chunk
        r = json.loads(data or b"{}")
        return r.get("text")
    except Exception as e:  # noqa: BLE001 - memory must never break the caller
        log(f"llm failed: {type(e).__name__}: {str(e)[:200]}")
        return None

def llm_json(prompt, timeout=120, tools=None):
    text = llm(prompt + "\n\nReply with JSON only, no prose, no code fences.", timeout=timeout, tools=tools)
    if not text:
        return None
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        log("llm returned bad JSON")
        return None

def llm_serve(_):
    sem = threading.Semaphore(3)
    if LLM_SOCK.exists():
        LLM_SOCK.unlink()
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(LLM_SOCK)); os.chmod(LLM_SOCK, 0o660); srv.listen(8)
    def handle(c):
        with c:
            try:
                data = b""
                while chunk := c.recv(65536):
                    data += chunk
                    if len(data) > 200_000: break
                req = json.loads(data)
                with sem:
                    text = _run_claude(str(req["prompt"])[:60000], min(int(req.get("timeout", 12)), 60),
                                       "haiku" if req.get("model") != "sonnet" else "sonnet")
                c.sendall(json.dumps({"text": text}).encode())
            except Exception as e:  # noqa: BLE001
                try: c.sendall(json.dumps({"error": str(e)[:200]}).encode())
                except OSError: pass
    while True:
        c, _a = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

# ---------------------------------------------------------------- facts / profile
def section_of(header):
    h = re.sub(r"\(.*?\)", "", header).strip(" #")
    if h.lower().startswith("private"): return "Private"
    if h.lower().startswith("about the owner"): return "About the owner"
    return h or "About the owner"

def add_fact(facts, text, section=LEARNED, source="said", confidence="high", private=None, expires=None, origin="cli"):
    text = clean(re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", text), 300)
    if not text or unsafe(text):
        return None
    priv = (section == "Private") if private is None else private
    priv = priv or is_private(text)
    if section == "Private":
        section = LEARNED
    n = norm(text)
    for f in facts:
        if f["status"] == "active" and norm(f["text"]) == n:   # same fact again: newest wins
            f.update(updated=iso(), source=source, confidence=confidence, private=f["private"] or priv,
                     expires=expires or f.get("expires"))
            return f["id"]
    f = dict(id=nid("f"), text=text, section=section, source=source, confidence=confidence, private=priv,
             expires=expires, added=iso(), updated=iso(), status="active", origin=origin)
    facts.append(f)
    return f["id"]

def bullets(text):
    sec, out = "About the owner", []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            sec = section_of(line[3:])
        elif line.startswith("# "):
            sec = "About the owner"
        elif line.startswith("- "):
            out.append((sec, line[2:].strip()))
    return out

def priority(f):
    return ((f["confidence"] == "high") * 4 + {"said": 3, "email": 2}.get(f["source"], 0)
            + (f["section"] in ("About the owner", "Identity", "Preferences")) * 2, f.get("updated", ""))

def fit(facts, cap, render):
    chosen = sorted(facts, key=priority, reverse=True)
    while chosen and len(render(chosen)) > cap:
        chosen.pop()
    keep = {f["id"] for f in chosen}
    return [f for f in facts if f["id"] in keep], [f for f in facts if f["id"] not in keep]

def _sections(facts, extra_private=False):
    out = []
    for sec in SECTION_ORDER + sorted({f["section"] for f in facts} - set(SECTION_ORDER)):
        group = [f for f in facts if f["section"] == sec and not (extra_private and f["private"])]
        if group or (sec == LEARNED and not extra_private):
            out.append((sec, group))
    return out

def render_profile(facts):
    lines = ["# About the owner (shared by the voice line and Claude)", "",
             "Made by voice-memory from /var/lib/voice-memory/facts.json; private facts are kept out of this file.",
             "Add new facts as lines under 'Learned on calls' (or run voice-memory remember); edits here are picked up."]
    for sec, group in _sections(facts):
        if sec == LEARNED:
            continue
        lines += ["", f"## {sec}"] + [f"- {f['text']}" for f in group]
    lines += ["", f"## {LEARNED}"] + [f"- {f['text']}" for f in facts if f["section"] == LEARNED]
    return "\n".join(lines) + "\n"

def render_user(facts):
    pub = [f for f in facts if not f["private"]]
    priv = [f for f in facts if f["private"]]
    lines = ["# About the owner"]
    for sec, group in _sections(pub, extra_private=True):
        if group:
            lines += ([] if sec == "About the owner" else ["", f"## {sec}"]) + [f"- {f['text']}" for f in group]
    if priv:
        lines += ["", f"## {PRIVATE_HDR}"] + [f"- {f['text']}" for f in priv]
    lines += ["", "(Full profile with sources and expiry: /var/lib/voice-memory/profile-full.md. Save facts with voice-memory remember.)"]
    return "\n".join(lines) + "\n"

def render_full(facts, overflow):
    lines = ["# Owner profile (all facts, with tags)", "",
             "Tags: source (said/email/inferred), confidence, expiry, private. Private facts never reach the voice line.", ""]
    active = [f for f in facts if f["status"] == "active"]
    for sec, group in _sections(active):
        if group:
            lines.append(f"## {sec}")
            for f in group:
                tags = [f["source"], f["confidence"]] + ([f"expires {f['expires']}"] if f.get("expires") else []) \
                       + (["private"] if f["private"] else []) + [f"added {f['added']}", f["id"]]
                lines.append(f"- {f['text']}  [{', '.join(tags)}]")
            lines.append("")
    if overflow:
        lines += ["## Not loaded into USER.md (over the 3000-character cap; still kept here)"] + \
                 [f"- {f['text']}  [{f['id']}]" for f in overflow] + [""]
    old = [f for f in facts if f["status"] != "active"][-40:]
    if old:
        lines += ["## Retired (expired, removed or merged; newest last)"] + \
                 [f"- {f['text']}  [{f['status']} {f.get('updated', '')}, {f['id']}]" for f in old]
    return "\n".join(lines) + "\n"

def _import_view(facts, state, key, path, origin):
    try:
        cur = path.read_text()
    except (FileNotFoundError, PermissionError):
        return 0
    last = state.get("views", {}).get(key)
    if cur == last:
        return 0
    now_b = bullets(cur)
    last_n = {norm(t) for _s, t in bullets(last)} if last is not None else set()
    cur_n = {norm(t) for _s, t in now_b}
    changes = 0
    for sec, text in now_b:
        if norm(text) not in last_n:
            src = "email" if last is None and sec in ("Identity", "Work and job search", "Writing style", "Key people") else "said"
            if add_fact(facts, text, section=sec, source=src, origin=origin if last is not None else "import"):
                changes += 1
    if last is not None:
        for n in last_n - cur_n:
            for f in facts:
                if f["status"] == "active" and norm(f["text"]) == n:
                    f.update(status="removed", updated=iso(), why=f"line deleted from {key}")
                    changes += 1
    return changes

def apply_inbox(facts):
    n = 0
    try:
        files = sorted(INBOX.glob("*.json"))
    except PermissionError:
        return 0
    for p in files:
        try:
            item = json.loads(p.read_text())
            if item["op"] == "remember":
                add_fact(facts, **item["args"]); n += 1
            elif item["op"] == "journal":
                journal_add(**item["args"]); n += 1
            p.unlink()
        except Exception as e:  # noqa: BLE001
            log(f"bad inbox item {p.name}: {e}")
            p.rename(p.with_suffix(".bad"))
    return n

def sync(_=None, quiet=False):
    """Import edits from the two views and the inbox, then regenerate the views."""
    n = 0
    with Lock():
        facts = load("facts.json", [])
        state = load("state.json", {})
        first = not facts
        n += apply_inbox(facts)
        n += _import_view(facts, state, "USER.md", USER_MD, "helper")
        for _try in range(4):
            snap = PROFILE_MD.read_text() if PROFILE_MD.exists() else None
            n += _import_view(facts, state, "profile.md", PROFILE_MD, "voice")
            expire(facts)
            active = [f for f in facts if f["status"] == "active"]
            pub, over_p = fit([f for f in active if not f["private"]], PROFILE_CAP, render_profile)
            prof = render_profile(pub)
            views = state.setdefault("views", {})
            # Another writer (the voice agent appends to profile.md) may have written since we read it: redo.
            if (PROFILE_MD.read_text() if PROFILE_MD.exists() else None) != snap:
                continue
            save("facts.json", facts)
            try:
                write_text(PROFILE_MD, prof); views["profile.md"] = prof
            except PermissionError:
                pass
            break
        user_facts, overflow = fit(active, USER_CAP, render_user)
        if os.access(USER_MD.parent, os.W_OK):
            user = render_user(user_facts)
            write_text(USER_MD, user); views["USER.md"] = user
        if first and facts:
            seed(facts)
        state["overflow"] = [f["id"] for f in overflow]
        state["profile_overflow"] = [f["id"] for f in over_p]
        state["synced"] = now()
        save("state.json", state)
        write_text(BASE / "profile-full.md", render_full(facts, overflow))
        render_people(render_projects()); render_misc(); render_archive()
    if n and not quiet:
        log(f"sync: {n} change(s)")
    return n

def expire(facts):
    """Expiry never deletes: the fact becomes 'stale' (not used as true, left out of the views, still searchable)
    and the nightly job queues a 'still true?' check for the owner."""
    t = iso()
    for f in facts:
        if f["status"] == "active" and f.get("expires") and f["expires"] < t:
            f.update(status="stale", stale_since=t, updated=t)

def seed(facts):
    """First run: people from the Key people section, goals from the profile (to confirm)."""
    ppl = load("people.json", {"people": [], "companies": []})
    for f in facts:
        m = re.match(r"(?P<name>[^,:]+),\s*(?P<email>[\w.+-]+@[\w.-]+\w):\s*(?P<rest>.*)", f["text"])
        if f["section"] == "Key people" and m:
            rest = m.group("rest")
            role, _, comp = rest.partition(",")
            comp = re.split(r"[(.]", comp)[0].strip() or None
            raw = m.group("name")
            alias = (re.search(r"\(([^)]+)\)", raw) or [None, None])[1]
            name = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", raw)).strip()
            upsert_person(ppl, name=name, email=m.group("email"), company=comp, role=role.strip(), note=rest[:200],
                          ref={"kind": "fact", "id": f["id"], "date": f["added"]}, alias=alias)
    save("people.json", ppl)
    if not load("goals.json", None):
        goals = [{"id": nid("g"), "text": t, "added": iso(), "status": "active", "confirmed": False}
                 for t in ["Land a job in my field",
                           "Ship my side project",
                           "Grow my creator channel"]]
        save("goals.json", goals)

def remember(a):
    args = dict(text=a.fact, source=a.source, confidence=a.confidence, private=True if a.private else None,
                expires=a.expires, origin=a.origin)
    if a.expires and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.expires):
        print("expires must be YYYY-MM-DD"); return 2
    if unsafe(a.fact):
        print("Not saved: that text looks unsafe to keep in memory."); return 0
    if not writable():
        spool("remember", args); print("Saved (queued)."); return 0
    with Lock():
        facts = load("facts.json", [])
        fid = add_fact(facts, **args)
        save("facts.json", facts)
    sync(quiet=True)
    priv = any(f["id"] == fid and f["private"] for f in load("facts.json", []))
    print(f"Saved ({fid}{', private: Claude only' if priv else ''}).")
    return 0

# ---------------------------------------------------------------- journal
def journal_load(): return read_jsonl(BASE / "journal.jsonl")

def journal_save(entries):
    p = BASE / "journal.jsonl"
    tmp = p.with_name(f".journal.{os.getpid()}.tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in sorted(entries, key=lambda e: e["ts"])))
    os.chmod(tmp, 0o660); os.replace(tmp, p)

def journal_add(source, ref, text, who=None, ts=None, summary=None, processed=False, origin="cli", replace=True):
    """Upsert one entry per (source, ref). Caller holds Lock or is apply_inbox (inside sync's lock)."""
    entries = journal_load()
    text = (text or "").strip()[:6000]
    ts = float(ts or now())
    for e in entries:
        if e["source"] == source and e["ref"] == str(ref):
            if not replace:
                return e["id"]
            e.update(text=text, ts=ts if source != "mac" else e["ts"], updated=now(), processed=processed,
                     origin=origin, private=is_private(text))
            if summary: e["summary"] = clean(summary, 240)
            if source == "mac": e["ts_last"] = ts
            break
    else:
        e = dict(id=nid("j"), ts=ts, date=iso(ts), source=source, ref=str(ref), who=who or ["owner"], text=text,
                 summary=clean(summary, 240) if summary else None, decided=[], promises=[], followups=[], people=[],
                 private=is_private(text), processed=processed, origin=origin)
        entries.append(e)
    journal_save(entries)
    render_journal_month(entries, e["date"][:7])
    return e["id"]

def render_journal_month(entries, month):
    d = BASE / "journal"; d.mkdir(exist_ok=True)
    lines = [f"# Journal {month}", ""]
    for e in entries:
        if e["date"][:7] != month:
            continue
        lines.append(f"## {when(e['ts'])} · {e['source']} {e['ref']}" + (" · private" if e.get("private") else ""))
        lines.append(e.get("summary") or clean(e["text"], 300))
        for k, label in (("decided", "Decided"), ("promises", "Promised"), ("followups", "Follow up"), ("people", "People")):
            if e.get(k):
                lines.append(f"- {label}: " + "; ".join(x if isinstance(x, str) else x.get("text") or x.get("name", "") for x in e[k]))
        lines.append("")
    write_text(d / f"{month}.md", "\n".join(lines))

def journal_delete(a):
    """Nothing is deleted: entries move to archive.jsonl, which recall and brief still search."""
    with Lock():
        entries = journal_load()
        gone = [e for e in entries if e["id"] in a.ids or e["ref"] in a.ids]
        keep = [e for e in entries if e not in gone]
        with open(BASE / "archive.jsonl", "a") as f:
            for e in gone:
                f.write(json.dumps(dict(e, kind="journal", archived=iso()), ensure_ascii=False) + "\n")
        journal_save(keep)
        for m in {e["date"][:7] for e in entries}:
            render_journal_month(keep, m)
        render_archive()
    print(f"Archived {len(gone)} entr{'y' if len(gone) == 1 else 'ies'} (still searchable)."); return 0

def render_archive():
    facts = [f for f in load("facts.json", []) if f["status"] != "active"]
    arch = read_jsonl(BASE / "archive.jsonl")
    pr = [p for p in load("promises.json", []) if p["status"] != "open"]
    L = ["# Archive (nothing is ever deleted; recall and brief search all of this)", "",
         "## Retired or stale facts"] + [f"- {f['text']}  [{f['status']} {f.get('updated', '')}{', ' + f['why'] if f.get('why') else ''}]" for f in facts]
    L += ["", "## Closed promises / follow-ups"] + [f"- {p['text']}  [{p['status']} {p.get('updated', '')}]" for p in pr]
    L += ["", "## Archived journal entries"] + [f"- {e.get('date')} {e.get('source')} {e.get('ref')}: {clean(e.get('summary') or e.get('text'), 200)}" for e in arch]
    write_text(BASE / "archive.md", "\n".join(L) + "\n")

def journal_cmd(a):
    text = a.text if a.text != "-" else sys.stdin.read()
    if unsafe(text) and a.source != "call":
        text = "[entry withheld: unsafe-looking text]"
    args = dict(source=a.source, ref=a.id, text=text, ts=a.time, summary=a.summary)
    if not writable():
        spool("journal", args); print("Journaled (queued)."); return 0
    with Lock():
        jid = journal_add(**args)
    print(f"Journaled {jid}.")
    return 0

# ---------------------------------------------------------------- people, promises, goals
def upsert_person(ppl, name, email=None, company=None, role=None, note=None, ref=None, alias=None):
    name = clean(name, 80)
    if not name or len(name) < 2:
        return None
    em = (email or "").lower().strip("<>.,") or None
    p = None
    for q in ppl["people"]:
        if (em and em in q.get("emails", [])) or norm(q["name"]) == norm(name) or norm(name) in map(norm, q.get("aliases", [])):
            p = q; break
    if p is None and len(name.split()) == 1:  # "Sarah" -> an existing "Sarah Lee" if only one matches
        hits = [q for q in ppl["people"] if norm(q["name"]).split()[:1] == [norm(name)]]
        p = hits[0] if len(hits) == 1 else None
    if p is None:
        p = dict(id=nid("p"), name=name, aliases=[], emails=[], company=None, role=None, notes="", refs=[], last_seen=iso())
        ppl["people"].append(p)
    elif len(name) > len(p["name"]) and norm(p["name"]) in norm(name):
        p["aliases"].append(p["name"]); p["name"] = name
    if alias and alias not in p["aliases"]: p["aliases"].append(alias)
    if em and em not in p["emails"]: p["emails"].append(em)
    if company: p["company"] = clean(company, 80)
    if role: p["role"] = clean(role, 80)
    if note and note not in p["notes"]: p["notes"] = clean((p["notes"] + " " + note).strip(), 400)
    if ref and not any(r["kind"] == ref["kind"] and r["id"] == ref["id"] for r in p["refs"]):
        p["refs"] = p["refs"] + [ref]   # never capped: old links stay findable
        p["last_seen"] = max(p.get("last_seen", ""), ref.get("date", ""))
    if p.get("company"):
        c = next((c for c in ppl["companies"] if norm(c["name"]) == norm(p["company"])), None)
        if c is None:
            c = {"name": p["company"], "people": [], "domains": []}; ppl["companies"].append(c)
        if p["id"] not in c["people"]: c["people"].append(p["id"])
        for e in p["emails"]:
            dom = e.split("@")[-1]
            if dom not in c["domains"] and dom not in ("gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"):
                c["domains"].append(dom)
    return p["id"]

def resolve(ppl, text):
    """People mentioned in text by name, first name, alias, email or company."""
    t = " " + norm(text) + " "
    found = []
    for p in ppl["people"]:
        keys = [p["name"], *p.get("aliases", []), *p.get("emails", []), p["name"].split()[0]]
        if p.get("company"): keys.append(p["company"])
        if any(len(norm(k)) > 2 and f" {norm(k)} " in t for k in keys if k):
            found.append(p)
    return found

PROJECT_SEED = [("Job search", ["job search", "interview", "job application", "applying for", "resume", "recruiter",
                                "hiring manager", "job offer"]),
                ("Creator channel", ["youtube", "my channel", "thumbnail"]),
                ("Voice assistant", ["voice line", "voice agent", "voice assistant", "voice-memory", "voice caller"])]

def slug(n): return re.sub(r"[^a-z0-9]+", "-", str(n).lower()).strip("-") or "project"

def projects_load():
    d = load("projects.json", None)
    if d is None:
        d = {"projects": [dict(id=nid("r"), name=n, slug=slug(n), keywords=k, status="active", added=iso(), notes="")
                          for n, k in PROJECT_SEED], "candidates": {}}
    return d

def entry_projects(e, projs):
    t = " " + (str(e.get("text", "")) + " " + str(e.get("summary") or "")).lower() + " "
    tags = set(e.get("projects") or [])
    for p in projs:
        if any(k in t for k in p["keywords"]) or f" {p['name'].lower()}" in t:
            tags.add(p["slug"])
    return tags

def render_projects():
    """One file per project (projects/<slug>.md) + projects.md index; returns person -> project names."""
    d = projects_load()
    if not (BASE / "projects.json").exists():
        save("projects.json", d)
    entries = journal_load() + read_jsonl(BASE / "archive.jsonl")
    pr = load("promises.json", [])
    ppl = load("people.json", {"people": [], "companies": []})
    comp = {norm(p["name"]): p.get("company") for p in ppl["people"]}
    pdir = BASE / "projects"; pdir.mkdir(exist_ok=True)
    idx = ["# Projects", "", "One file per project in projects/, updated automatically from the journal (calls, tasks, Mac sessions).", ""]
    person_proj = {}
    for p in d["projects"]:
        es = sorted((e for e in entries if p["slug"] in entry_projects(e, [p])), key=lambda e: -e.get("ts", 0))
        refs = {f"{e.get('source')} {e.get('ref')}" for e in es}
        names = []
        for e in es:
            for n in e.get("people") or []:
                if n not in names: names.append(n)
        prom = [x for x in pr if x["status"] == "open" and (x.get("ref") in refs or any(k in x["text"].lower() for k in p["keywords"]))]
        last = es[0]["ts"] if es else 0
        L = [f"# {p['name']}", "", f"Status: {p['status']} | {len(es)} journal entries | last activity {when(last) if last else 'none yet'}",
             f"Keywords: {', '.join(p['keywords'])}"] + ([f"Notes: {p['notes']}"] if p.get("notes") else [])
        if prom: L += ["", "## Open promises / follow-ups"] + [f"- [{x['id']}] {x['text']}" for x in prom]
        if names: L += ["", "## People"] + [f"- {n}" + (f" ({comp[norm(n)]})" if comp.get(norm(n)) else "") for n in names]
        L += ["", "## History (newest first, complete)"] + [
            f"- {iso(e.get('ts'))} {e.get('source')}: {clean(e.get('summary') or e.get('text'), 220)}" + (" (private)" if e.get("private") else "")
            + (" (archived)" if e.get("kind") == "journal" else "") for e in es]
        write_text(pdir / f"{p['slug']}.md", "\n".join(L) + "\n")
        idx.append(f"- [{p['name']}](projects/{p['slug']}.md): {p['status']}, {len(es)} entries, last {iso(last) if last else '-'}")
        for n in names:
            person_proj.setdefault(norm(n), []).append(p["name"])
    write_text(BASE / "projects.md", "\n".join(idx) + "\n")
    return person_proj

def project_stats():
    d = projects_load(); entries = journal_load()
    out = []
    for p in d["projects"]:
        if p["status"] != "active": continue
        last = max((e["ts"] for e in entries if p["slug"] in entry_projects(e, [p])), default=0)
        out.append((last, p["name"]))
    return sorted(out, reverse=True)

def project_cmd(a):
    with Lock():
        d = projects_load()
        hit = [p for p in d["projects"] if norm(p["name"]) == norm(a.text) or p["slug"] == slug(a.text)]
        if a.action == "add":
            if hit: out = "already there"
            else:
                kw = [k.strip().lower() for k in (a.keywords or a.text).split(",") if k.strip()]
                d["projects"].append(dict(id=nid("r"), name=clean(a.text, 60), slug=slug(a.text), keywords=kw, status="active", added=iso(), notes=""))
                out = "ok"
        elif a.action in ("done", "pause", "active"):
            for p in hit: p["status"] = a.action
            out = "ok" if hit else "no such project"
        elif a.action == "show":
            out = (BASE / "projects" / f"{hit[0]['slug']}.md").read_text() if hit else "no such project"
        else:
            out = "\n".join(f"{p['name']} ({p['status']}): keywords {', '.join(p['keywords'])}" for p in d["projects"])
        save("projects.json", d)
        render_people(render_projects())
    print(out); return 0

def render_people(person_proj=None):
    person_proj = person_proj or {}
    ppl = load("people.json", {"people": [], "companies": []})
    lines = ["# People and companies", ""]
    for c in sorted(ppl["companies"], key=lambda c: c["name"]):
        lines.append(f"## {c['name']}" + (f" ({', '.join(c['domains'])})" if c.get("domains") else ""))
        for pid in c["people"]:
            p = next((p for p in ppl["people"] if p["id"] == pid), None)
            if p: lines.append(f"- {p['name']}: {p.get('role') or ''} {', '.join(p['emails'])}. {p.get('notes', '')}".strip()
                               + (f" Projects: {', '.join(person_proj[norm(p['name'])])}." if person_proj.get(norm(p["name"])) else ""))
        lines.append("")
    loose = [p for p in ppl["people"] if not p.get("company")]
    if loose:
        lines += ["## No company"] + [f"- {p['name']} {', '.join(p['emails'])}. {p.get('notes', '')}" for p in loose] + [""]
    lines += ["## Links (calls, tasks, emails)"]
    for p in ppl["people"]:
        if p["refs"]:
            lines.append(f"- {p['name']}: " + "; ".join(f"{r['kind']} {r['id']} {r.get('date', '')}" for r in p["refs"]))
    write_text(BASE / "people.md", "\n".join(lines) + "\n")

def render_misc():
    pr = load("promises.json", []); goals = load("goals.json", []); props = load("proposals.json", [])
    lines = ["# Goals", ""] + [f"- {g['text']}" + ("" if g.get("confirmed") else " (not confirmed by the owner yet)")
                               for g in goals if g["status"] == "active"]
    lines += ["", "# Open promises and follow-ups", ""] + [
        f"- [{p['id']}] {p['text']} ({p['who']}{', due ' + p['due'] if p.get('due') else ''})" for p in pr if p["status"] == "open"]
    lines += ["", "# Learned but not saved (waiting for the owner's yes)", ""] + [
        f"- [{p['id']}] {p['text']} ({p.get('why', '')})" for p in props if p["status"] == "pending"]
    write_text(BASE / "open-items.md", "\n".join(lines) + "\n")

def same_item(a, b):
    """Loose match for promises/follow-ups (they get re-worded across tasks)."""
    A, B = {w[:5] for w in words(a)}, {w[:5] for w in words(b)}   # crude stem: commute/commuting
    if not A or not B: return False
    names = lambda t: {w.lower() for w in re.findall(r"[A-Za-z][\w&'-]+", t)[1:] if w[0].isupper() and len(w) > 2 and w.lower() not in STOP}
    NA, NB = names(a), names(b)
    if NA and NB and not NA & NB:      # different people/companies: never the same item
        return False
    inter = len(A & B)
    return inter / len(A | B) >= 0.5 or (inter >= 2 and inter / min(len(A), len(B)) >= 0.6)

def dedupe_promises():
    """Merge re-worded duplicates: the newest wording stays open, older ones are kept as status 'merged'."""
    with Lock():
        pr = load("promises.json", []); n = 0
        open_ = sorted((p for p in pr if p["status"] == "open"), key=lambda p: p.get("created", ""), reverse=True)
        for i, p in enumerate(open_):
            if p["status"] != "open": continue
            for q in open_[i + 1:]:
                if q["status"] == "open" and same_item(p["text"], q["text"]):
                    q.update(status="merged", updated=iso(), why=f"same as {p['id']}")
                    p["due"] = p.get("due") or q.get("due"); p["created"] = min(p.get("created", ""), q.get("created", "")) or p.get("created")
                    n += 1
        save("promises.json", pr); render_misc()
    return n

def add_promise(pr, text, who="assistant", due=None, ref=None, kind="promise"):
    text = clean(text, 240)
    if not text or unsafe(text) or any(p["status"] == "open" and same_item(p["text"], text) for p in pr):
        return None
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due)): due = None
    p = dict(id=nid("o"), text=text, who=clean(who, 60) or "assistant", due=due, kind=kind, status="open",
             ref=ref, created=iso(), updated=iso())
    pr.append(p)
    return p["id"]

def promise_cmd(a):
    with Lock():
        pr = load("promises.json", [])
        if a.action == "add":
            out = add_promise(pr, a.text, a.who, a.due, kind=a.kind) or "already listed"
        elif a.action in ("done", "drop"):
            hit = [p for p in pr if p["id"] == a.text]
            for p in hit: p.update(status="done" if a.action == "done" else "dropped", updated=iso())
            out = "ok" if hit else "no such id"
        else:
            out = "\n".join(f"[{p['id']}] {p['text']} ({p['who']}{', due ' + p['due'] if p.get('due') else ''})"
                            for p in pr if p["status"] == "open") or "No open promises."
        save("promises.json", pr); render_misc()
    print(out); return 0

def goal_cmd(a):
    with Lock():
        goals = load("goals.json", [])
        if a.action == "add":
            goals.append({"id": nid("g"), "text": clean(a.text, 160), "added": iso(), "status": "active", "confirmed": True})
            goals = goals[-12:]; out = "ok"
        elif a.action in ("done", "drop", "confirm"):
            hit = [g for g in goals if g["id"] == a.text]
            for g in hit:
                if a.action == "confirm": g["confirmed"] = True
                else: g["status"] = a.action
            out = "ok" if hit else "no such id"
        else:
            out = "\n".join(f"[{g['id']}] {g['text']}" + ("" if g.get("confirmed") else " (unconfirmed)")
                            for g in goals if g["status"] == "active") or "No goals."
        save("goals.json", goals); render_misc()
    print(out); return 0

def people_cmd(a):
    ppl = load("people.json", {"people": [], "companies": []})
    hits = resolve(ppl, a.name) if a.name else ppl["people"]
    for p in hits:
        print(f"{p['name']} [{p['id']}]: {p.get('role') or ''} at {p.get('company') or '?'}; {', '.join(p['emails'])}; "
              f"{p.get('notes', '')} Links: " + "; ".join(f"{r['kind']} {r['id']}" for r in p['refs'][-6:]))
    if not hits: print("No one by that name in memory.")
    return 0

# ---------------------------------------------------------------- context / recall / brief
def recent_calls(entries, n=15):
    calls = [e for e in entries if e["source"] == "call"]
    seen = {e["ref"] for e in calls}
    # Calls not journaled yet (only when this user can read the call log)
    by_id = {}
    for ev in read_jsonl(CALLS, 400):
        cid = ev.get("call_id")
        if not cid or cid in seen: continue
        d = by_id.setdefault(cid, {"ts": ev["time"], "reason": "", "state": "dialed"})
        if ev["event"] == "dialing": d["reason"] = ev.get("reason", "")
        if ev["event"] in ("answered", "not_answered"): d["state"] = ev["event"].replace("_", " ")
    rows = [(e["ts"], e.get("summary") or clean(e["text"], 160), e.get("private")) for e in calls]
    rows += [(d["ts"], f"{clean(d['reason'], 120)} ({d['state']})", False) for d in by_id.values() if d["reason"]]
    return sorted(rows, reverse=True)[:n]

TOPICS = [("immigration", r"immigra|visa|permit|residen|sponsor|citizenship"),
          ("money", r"bank|account|credit|debit|debt|loan|mortgage|salary|income|wage|pay|tax|money|saving|invest|crypto|rent|\$"),
          ("ID numbers", r"national id|tax id|id number|passport|birth|DOB")]

def priv_topics(texts):
    out = []
    for t in texts:
        name = next((n for n, rx in TOPICS if re.search(rx, t or "", re.I)), "personal")
        if name not in out: out.append(name)
    return ", ".join(out) or "personal"

def priv_marker(what, texts):
    return (f"PRIVATE: {what} ({priv_topics(texts)}), kept Claude-side and not said on calls. If it matters, "
            "say you have it and offer to have Claude handle it.")

def context_cmd(a):
    entries = journal_load()
    allf = load("facts.json", [])
    facts = [f for f in allf if f["status"] == "active" and not f["private"]]
    goals = [g for g in load("goals.json", []) if g["status"] == "active"]
    # Open promises never age out: all of them, oldest due first, until marked done or dropped.
    pr_all = sorted((p for p in load("promises.json", []) if p["status"] == "open"), key=lambda p: (p.get("due") or "9999", p.get("created", "")))
    pr = [p for p in pr_all if not is_private(p["text"])]
    priv_pr = [p for p in pr_all if is_private(p["text"])]
    ppl = load("people.json", {"people": [], "companies": []})
    q = todays_question()
    soon = (today() + dt.timedelta(days=14)).isoformat()
    exp = [f for f in facts if f.get("expires") and f["expires"] <= soon]
    stale = [f for f in allf if f["status"] == "stale" and not f["private"]]
    priv_f = [f for f in allf if f["private"] and f["status"] in ("active", "stale") and f.get("expires") and f["expires"] <= soon]
    recent = (today() - dt.timedelta(days=3)).isoformat()
    rel = {p["id"]: p for p in resolve(ppl, (a.today or "") + " " + " ".join(p["text"] for p in pr))}
    for p in ppl["people"]:
        if p.get("last_seen", "") >= recent: rel.setdefault(p["id"], p)
    calls_all = recent_calls(entries)
    calls = [c for c in calls_all if not c[2]]
    priv_calls = [c for c in calls_all if c[2]]
    projs = [n for ts, n in project_stats() if ts][:5]
    marker = []
    if priv_pr: marker.append(f"{len(priv_pr)} open promise(s)/follow-up(s)")
    if priv_f: marker.append(f"{len(priv_f)} fact(s) expiring or stale")
    if priv_calls: marker.append(f"{len(priv_calls)} recent call(s)")

    def build(ncalls, npeople, plen, nprom):
        out = [f"MEMORY ({dt.datetime.now(TZ):%a %b %-d %H:%M}; private facts left out)"]
        if goals: out.append("Goals: " + "; ".join(g["text"] for g in goals[:5]))
        if pr:
            out.append("Open promises / follow-ups (all of them, until done):")
            out += [f"- {clean(redact(p['text']), plen)} ({p['who']}{', due ' + p['due'] if p.get('due') else ''}, since {p.get('created', '?')})"
                    for p in pr[:nprom]]
            if len(pr) > nprom: out.append(f"- +{len(pr) - nprom} more open items (voice-memory promise list)")
        if marker:
            out.append(priv_marker("there are private " + ", ".join(marker), [p["text"] for p in priv_pr] + [f["text"] for f in priv_f]))
        if q and not q.get("private"):
            out.append(f"Ask the owner once today, only if it fits naturally (save the reply with voice-memory answer {q['id']} "
                       f"yes|no|<correction>): {q['text']}")
        if exp:
            out.append("Facts expiring soon: " + "; ".join(f"{f['text']} (until {f['expires']})" for f in exp[:4]))
        if stale:
            out.append("Possibly out of date, do not rely on it (a 'still true?' check is queued): " + "; ".join(clean(f["text"], 100) for f in stale[-4:]))
        if calls[:ncalls]:
            out.append("Recent calls (newest first):")
            out += [f"- {when(ts)}: {clean(s, 150)}" for ts, s, _p in calls[:ncalls]]
        if projs: out.append("Active projects (latest first): " + ", ".join(projs))
        if list(rel.values())[:npeople]:
            out.append("People likely relevant today:")
            out += [f"- {p['name']}" + (f" ({p.get('role') or ''}{', ' if p.get('role') else ''}{p['company']})" if p.get("company") else "")
                    + (f": {clean(p.get('notes'), 90)}" if p.get("notes") else "") for p in list(rel.values())[:npeople]]
        return "\n".join(out)

    n = dict(ncalls=15, npeople=6, plen=140, nprom=len(pr))
    text = build(**n)
    for key, floor, step in (("ncalls", 0, 1), ("npeople", 0, 1), ("plen", 60, 20), ("ncalls", 0, 1)):
        while len(text) > CONTEXT_CAP and n[key] > floor:
            n[key] = max(floor, n[key] - step); text = build(**n)
    while len(text) > CONTEXT_CAP and n["nprom"] > 1:   # only with dozens of open items: the rest are counted, never dropped
        n["nprom"] -= 1; text = build(**n)
    print(text[:CONTEXT_CAP]); return 0

def documents(voice=False):
    """ALL history, not just the recent window: every fact (incl. stale/retired), the whole journal, the archive,
    people, projects, every promise, goal, voice task result, kept email and helper note."""
    for f in load("facts.json", []):
        tag = "" if f["status"] == "active" else f" ({f['status']}: may be out of date)"
        yield (f"profile {f['id']}{tag}", 0, f"{f['section']}: {f['text']}", f["private"])
    for e in journal_load():
        txt = (e.get("summary") or "") + " | " + e["text"][:2500] + " " + " ".join(map(str, e.get("decided", [])))
        yield (f"journal {e['source']} {e['ref']} {e['date']}", e["ts"], txt, e.get("private", False))
    for e in read_jsonl(BASE / "archive.jsonl"):
        txt = (e.get("summary") or "") + " | " + str(e.get("text", ""))[:2500]
        yield (f"archive {e.get('source', '')} {e.get('ref', '')} {e.get('date', '')}", e.get("ts", 0), txt, e.get("private", False))
    ppl = load("people.json", {"people": [], "companies": []})
    for p in ppl["people"]:
        yield (f"people {p['name']}", 0, f"{p['name']} {' '.join(p['aliases'])} {p.get('role') or ''} at {p.get('company') or ''} "
               f"{' '.join(p['emails'])} {p.get('notes', '')} last seen {p.get('last_seen', '')} links: "
               + ", ".join(f"{r['kind']} {r['id']} {r.get('date', '')}" for r in p["refs"]), False)
    for p in projects_load()["projects"]:
        yield (f"project {p['name']}", 0, f"Project {p['name']} ({p['status']}): {' '.join(p['keywords'])} {p.get('notes', '')}", False)
    for p in load("promises.json", []):
        yield (f"promise {p['id']} ({p['status']})", 0, f"{p['kind']} by {p['who']}: {p['text']} due {p.get('due')} since {p.get('created')}", is_private(p["text"]))
    for g in load("goals.json", []):
        yield (f"goal {g['id']} ({g['status']})", 0, g["text"], False)
    try:
        for p in sorted((TASKS / "done").glob("*.json")):
            try: d = json.loads(p.read_text())
            except ValueError: continue
            txt = f"Task: {d.get('task', '')} Result: {d.get('spoken', '')} {str(d.get('details', ''))[:1500]}"
            yield (f"task {d.get('id', p.stem)} {iso(d.get('finished', p.stat().st_mtime))}", d.get("finished", 0), txt, is_private(txt))
    except PermissionError:
        pass
    for m in read_jsonl(EMAILS):
        txt = f"Email from {m.get('from', '')}: {m.get('subject', '')}. {str(m.get('body', ''))[:600]}"
        yield (f"email {iso(m.get('time', 0))} {clean(m.get('from', ''), 40)}", m.get("time", 0), txt, is_private(txt))
    try:
        for line in HELPER_MEMORY.read_text().splitlines():
            if line.startswith("- "): yield ("helper notes MEMORY.md", 0, line[2:], is_private(line))
    except (FileNotFoundError, PermissionError):
        pass

def search(question, k=10):
    """Rank every document (private ones included and flagged; callers decide what may be spoken)."""
    ppl = load("people.json", {"people": [], "companies": []})
    terms = words(question)
    for p in resolve(ppl, question):   # "Sarah" -> her full name, company, emails, linked ids
        terms |= words(p["name"]) | words(p.get("company") or "") | {e.lower() for e in p["emails"]} | {r["id"].lower() for r in p["refs"]}
    if not terms:
        return []
    scored = []
    for label, ts, text, priv in documents():
        low = norm(text) + " " + text.lower()
        hits = [t for t in terms if t in low]
        if hits:
            score = len(set(hits)) * 3 + sum(low.count(t) for t in hits) * 0.2 + (ts / 1e10)
            scored.append((score, label, ts, text, bool(priv)))
    scored.sort(reverse=True)
    return scored[:k]

def recall_cmd(a):
    q = a.question.strip()
    hits = search(q, k=14)
    pub = [h for h in hits if not (a.voice and h[4])][:10]
    priv = [h for h in hits if a.voice and h[4]]
    if not pub and not priv:
        print("I couldn't find anything about that in memory."); return 0
    if not pub:
        print("I have something about that, but it is private, so I won't say it on a call. Want me to have Claude handle it?")
        print(priv_marker(f"{len(priv)} private item(s) match", [h[3] for h in priv]))
        print("Sources: private (Claude-side only)"); return 0
    notes = "\n".join(f"[{i}] ({label}) {clean(redact(t) if a.voice else t, 700)}" for i, (_s, label, _ts, t, _p) in enumerate(pub, 1))
    rule = ("This answer will be spoken on a phone call: never mention immigration, money, ID numbers or other private details. "
            if a.voice else "")
    prompt = (f"Answer the owner's question using only these notes from their own memory files. {rule}"
              "Notes marked 'may be out of date' or 'archive' may no longer be true: say so if you rely on them. "
              "If the notes do not answer it, say you don't have that in memory. At most 3 short spoken-style sentences, "
              "then a last line 'SOURCES: ' with the note numbers you used, like 'SOURCES: 1,3'. Today is "
              f"{today():%A %B %-d %Y}.\n\nQuestion: {q}\n\nNotes:\n{notes}")
    text = llm(prompt, timeout=a.timeout)
    used = []
    if text:
        m = re.search(r"SOURCES:\s*([\d,\s]*)", text)
        if m:
            used = [int(x) for x in re.findall(r"\d+", m.group(1)) if 0 < int(x) <= len(pub)]
            text = text[:m.start()].strip()
        if a.voice: text = redact(text)
    else:
        text = "From memory: " + clean(redact(pub[0][3]) if a.voice else pub[0][3], 300)
        used = [1]
    print(text)
    if priv:
        print(priv_marker(f"{len(priv)} more private item(s) match", [h[3] for h in priv]))
    print("Sources: " + "; ".join(pub[i - 1][1] for i in (used or range(1, min(3, len(pub)) + 1))))
    return 0

def brief_cmd(a):
    try:
        ev = json.loads(a.event)
    except ValueError:
        ev = {"title": a.event}
    title = ev.get("title") or ev.get("summary") or "event"
    att = ev.get("attendees") or []
    att_txt = " ".join(x if isinstance(x, str) else f"{x.get('name', '')} {x.get('email', '')}" for x in att)
    blob = " ".join(str(ev.get(k, "")) for k in ("title", "summary", "description", "location", "organizer")) + " " + att_txt
    ppl = load("people.json", {"people": [], "companies": []})
    found = resolve(ppl, blob)
    for em in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", blob):   # match by company domain too
        dom = em.split("@")[1].lower()
        for c in ppl["companies"]:
            if dom in c.get("domains", []):
                found += [p for p in ppl["people"] if p["id"] in c["people"] and p not in found]
    out = [f"Briefing: {title}" + (f" at {ev['start']}" if ev.get("start") else "")]
    entries = journal_load() + read_jsonl(BASE / "archive.jsonl")   # all history, any age
    mails = read_jsonl(EMAILS)
    pr = [p for p in load("promises.json", []) if p["status"] == "open"]
    keys = set()
    for p in found[:4]:
        out.append(f"Who: {p['name']}" + (f", {p['role']}" if p.get("role") else "") + (f" at {p['company']}" if p.get("company") else "")
                   + (f" ({', '.join(p['emails'])})" if p["emails"] else "") + (f". {p['notes']}" if p.get("notes") else ""))
        keys |= {norm(p["name"]), norm(p["name"].split()[0])} | ({norm(p["company"])} if p.get("company") else set()) | set(p["emails"])
    hist, hidden = [], []
    for e in sorted(entries, key=lambda e: -e.get("ts", 0)):
        if not keys: continue
        t = norm(str(e.get("text", "")) + " " + (e.get("summary") or ""))
        if any(k and k in t for k in keys):
            if a.voice and e.get("private"):
                hidden.append(str(e.get("text", ""))); continue
            hist.append(f"- {iso(e['ts'])} {e.get('source')}: {clean(e.get('summary') or e.get('text'), 160)}")
    for m in sorted(mails, key=lambda m: -m.get("time", 0)):
        if keys and any(k and k in norm(m.get("from", "") + " " + m.get("subject", "")) for k in keys):
            hist.append(f"- {when(m['time'])} email from {clean(m.get('from'), 50)}: {clean(m.get('subject'), 100)}")
    if hist: out += ["History (all time, newest first):"] + hist[:8] + ([f"- ...and {len(hist) - 8} older entries"] if len(hist) > 8 else [])
    rel = [p for p in pr if keys and any(k and k in norm(p["text"]) for k in keys)]
    if rel: out += ["Open promises:"] + [f"- {p['text']}" for p in rel[:4]]
    if hidden:
        out.append(priv_marker(f"{len(hidden)} private note(s) about them", hidden))
    if not found:
        hits = [h for h in search(title + " " + att_txt + " " + str(ev.get("description", "")), k=6) if not (a.voice and h[4])][:4]
        out.append("No notes about these people yet." + (" Related: " + " | ".join(clean(h[3], 120) for h in hits) if hits else ""))
    text = "\n".join(out)
    if found and not a.no_llm:
        tip = llm("In one or two short sentences, tell the owner what to keep in mind for this meeting or call, using only "
                  "these notes. No private details (immigration, money, IDs).\n\n" + text, timeout=a.timeout)
        if tip: text += "\nTip: " + clean(tip, 300)
    print(redact(text) if a.voice else text); return 0

# ---------------------------------------------------------------- Mac sessions
def mac_ingest(_):
    n = 0
    data = sys.stdin.read(200_000)
    with Lock():
        for line in data.splitlines():
            try: d = json.loads(line)
            except ValueError: continue
            sid = re.sub(r"[^A-Za-z0-9_-]", "", str(d.get("session", "")))[:64]
            summ = clean(d.get("summary"), 400)
            if not sid or not summ: continue
            if unsafe(summ): summ = "[summary withheld: unsafe-looking text]"
            proj = clean(d.get("project"), 60)
            journal_add("mac", sid, f"Mac session in {proj or '?'}: {summ}", ts=float(d.get("ts") or now()),
                        summary=f"Mac ({proj}): {summ}"[:240], processed=False, origin="mac-hook")
            n += 1
    print(f"ok {n}"); return 0

# ---------------------------------------------------------------- catch-up from the call log and task results
def catch_up():
    """Journal calls and voice tasks that nobody journaled yet (backfill + nightly safety net)."""
    entries = journal_load()
    have = {(e["source"], e["ref"]) for e in entries}
    n = 0
    calls = {}
    for ev in read_jsonl(CALLS):
        c = calls.setdefault(ev.get("call_id"), {"ts": ev.get("time", 0), "reason": "", "state": "dialed", "transcript": "", "tasks": [], "notes": []})
        k = ev["event"]
        if k == "dialing": c["reason"] = ev.get("reason", "")
        elif k in ("answered", "not_answered"): c["state"] = k.replace("_", " ")
        elif k == "transcript": c["transcript"] = ev.get("transcript", "")
        elif k == "task": c["tasks"].append(ev.get("task_id"))
        elif k == "ended" and ev.get("note"): c["notes"].append(ev["note"])
        elif k in ("snoozed", "remembered", "note"): c["notes"].append(f"{k}: {clean(ev.get('fact') or ev.get('note') or ev.get('until') or '', 100)}")
    for cid, c in calls.items():
        if not cid or ("call", cid) in have: continue
        if c["transcript"]:
            text = f"Call reason: {c['reason']}\nTasks: {', '.join(filter(None, c['tasks'])) or 'none'}\nTranscript:\n{c['transcript'][-3500:]}"
            journal_add("call", cid, text, who=["owner", "voice assistant"], ts=c["ts"], origin="backfill", replace=False)
        else:
            s = f"Call about: {clean(c['reason'], 140)} ({c['state']})" + (f"; {'; '.join(c['notes'])}" if c["notes"] else "")
            journal_add("call", cid, s, ts=c["ts"], summary=s, processed=True, origin="backfill", replace=False)
        n += 1
    try:
        done = sorted((TASKS / "done").glob("*.json"))
    except PermissionError:
        done = []
    for p in done:
        try: d = json.loads(p.read_text())
        except ValueError: continue
        tid = d.get("id", p.stem)
        if ("task", tid) in have: continue
        text = f"Voice task ({'ok' if d.get('ok') else 'FAILED'}): {d.get('task', '')}\nResult: {d.get('spoken', '')}\n{str(d.get('details', ''))[:2500]}"
        journal_add("task", tid, text, who=["owner", "Claude"], ts=d.get("finished") or p.stat().st_mtime,
                    summary=clean(f"{'Done' if d.get('ok') else 'Failed'}: {d.get('spoken', '')}", 220), origin="backfill", replace=False)
        n += 1
    return n

# ---------------------------------------------------------------- nightly: extract, dedupe, cap, mistakes, learning
EXTRACT_PROMPT = """You maintain the owner's memory. For each journal entry below (calls, tasks, Mac sessions) return:
{"entries":[{"id":"<entry id>","summary":"<one plain sentence: what happened / was decided>","decided":["..."],
"promises":[{"text":"what was promised","who":"owner|assistant|<person>","due":"YYYY-MM-DD or null"}],
"followups":[{"text":"what needs following up","who":"...","due":null}],
"people":[{"name":"","company":"","role":"","email":""}],
"facts":[{"text":"lasting fact or preference about the owner, stated by the owner","private":false}],"projects":[],
"private":false}]}
Rules: only what the entry really says; empty lists when nothing; no promises or follow-ups about testing the
assistant itself, and none that the same entry shows were already done; people = real people or
companies the owner deals with (not the assistant); private=true for immigration, money, ID numbers;
"projects": names from this list when the entry is about one: %s (or a new short project name if clearly a new
ongoing project; else []). Today is %s.

Entries:
%s"""

def process_journal(limit=40):
    todo = [e for e in journal_load() if not e.get("processed")][:limit]
    results = []
    for i in range(0, len(todo), 6):
        batch = todo[i:i + 6]
        body = "\n\n".join(f"--- id {e['id']} ({e['source']} {e['ref']}, {e['date']})\n{e['text'][:3500]}" for e in batch)
        res = llm_json(EXTRACT_PROMPT % (", ".join(p["name"] for p in projects_load()["projects"]), today(), body), timeout=180)
        if isinstance(res, dict):
            ids = {e["id"]: e["text"] for e in batch}
            results += [(r, ids[r["id"]]) for r in res.get("entries", []) if isinstance(r, dict) and r.get("id") in ids]
    if not results:
        return 0
    done = 0
    with Lock():
        entries = journal_load()
        byid = {e["id"]: e for e in entries}
        ppl = load("people.json", {"people": [], "companies": []})
        pr, props, facts = load("promises.json", []), load("proposals.json", []), load("facts.json", [])
        projs = projects_load()
        for r, text_then in results:
            e = byid.get(r["id"])
            if not e or e["text"] != text_then:   # entry changed meanwhile: process it next time
                continue
            ref = {"kind": e["source"], "id": e["ref"], "date": e["date"]}
            e["summary"] = clean(r.get("summary") or e.get("summary") or e["text"], 240)
            e["decided"] = [clean(x, 160) for x in r.get("decided", []) if isinstance(x, str)][:5]
            e["private"] = bool(e.get("private") or r.get("private"))
            for kind in ("promises", "followups"):
                items = [x for x in r.get(kind, []) or [] if isinstance(x, dict) and x.get("text")][:5]
                e[kind] = [clean(x["text"], 160) for x in items]
                for x in items:
                    add_promise(pr, x["text"], x.get("who") or "assistant", x.get("due"), ref=f"{e['source']} {e['ref']}",
                                kind="promise" if kind == "promises" else "followup")
            e["people"] = []
            for x in (r.get("people") or [])[:6]:
                if isinstance(x, dict) and x.get("name") and not unsafe(json.dumps(x)):
                    upsert_person(ppl, x["name"], x.get("email"), x.get("company"), x.get("role"), ref=ref)
                    e["people"].append(clean(x["name"], 60))
            for x in (r.get("facts") or [])[:4]:
                if isinstance(x, dict) and x.get("text"):
                    propose(props, facts, "fact", x["text"], f"heard in {e['source']} {e['date']}", private=x.get("private"))
            tags = set(e.get("projects") or [])
            for name in (r.get("projects") or [])[:3]:
                if not isinstance(name, str) or not clean(name) or unsafe(name): continue
                pj = next((x for x in projs["projects"] if norm(x["name"]) == norm(name) or x["slug"] == slug(name)), None)
                if pj is None:   # a new project needs to show up twice before it gets a file
                    c = projs["candidates"][clean(name, 60)] = projs["candidates"].get(clean(name, 60), 0) + 1
                    if c >= 2:
                        pj = dict(id=nid("r"), name=clean(name, 60), slug=slug(name), keywords=[norm(name)], status="active", added=iso(), notes="auto-created")
                        projs["projects"].append(pj)
                if pj: tags.add(pj["slug"])
            e["projects"] = sorted(tags)
            e["processed"] = True
            done += 1
        save("projects.json", projs)
        journal_save(entries)
        for m in {e["date"][:7] for e in entries}:
            render_journal_month(entries, m)
        save("people.json", ppl); save("promises.json", pr); save("proposals.json", props)
    return done

def propose(props, facts, kind, text, why, private=None):
    text = clean(text, 240)
    if not text or unsafe(text): return None
    pool = [p["text"] for p in props] + [f["text"] for f in facts if f["status"] == "active"]
    if any(norm(t) == norm(text) or similar(t, text) for t in pool): return None
    p = dict(id=nid("q"), kind=kind, text=text, why=clean(why, 200), created=iso(), status="pending",
             private=bool(private) or is_private(text), asked=None)
    props.append(p)
    return p["id"]

DEDUPE_PROMPT = """These are the owner's profile facts (id | section | text | updated). Find:
1. duplicates or near-duplicates to merge into one line ("merge"), and
2. contradictions where a newer fact replaces an older one ("superseded": newer wins), and
3. a better section for facts in "Learned on calls" ("sections"), choosing from: %s.
Return {"merge":[{"ids":["f..","f.."],"text":"merged short line"}],"superseded":[{"old":"f..","new":"f.."}],"sections":{"f..":"Section"}}.
Be conservative: only clear cases. Keep facts short. Facts:
%s"""

def dedupe_facts():
    """Exact duplicates merge (newest wins); Haiku finds near-duplicates, contradictions and sections.
    The LLM runs without the lock; its decisions are applied by id to a fresh copy under the lock."""
    snap = [f for f in load("facts.json", []) if f["status"] == "active"]
    ops = []   # (kind, ids, text/section)
    seen = {}
    for f in sorted(snap, key=lambda f: f.get("updated", "")):
        n = norm(f["text"])
        if n in seen: ops.append(("drop", [seen[n]["id"]], f"same as {f['id']}"))
        seen[n] = f
    live = [f for f in seen.values()]
    if len(live) >= 2:
        listing = "\n".join(f"{f['id']} | {f['section']} | {f['text']} | {f.get('updated')}" for f in live)
        res = llm_json(DEDUPE_PROMPT % (", ".join(SECTION_ORDER[:-2]), listing), timeout=180)
        res = res if isinstance(res, dict) else {}
        for m in res.get("merge", []) or []:
            if isinstance(m, dict) and isinstance(m.get("ids"), list) and clean(m.get("text")):
                ops.append(("merge", m["ids"], clean(m["text"], 300)))
        for x in res.get("superseded", []) or []:
            if isinstance(x, dict): ops.append(("supersede", [x.get("old"), x.get("new")], ""))
        for fid, sec in (res.get("sections") or {}).items():
            ops.append(("section", [fid], sec))
    if not ops:
        return 0
    changes = 0
    with Lock():
        facts = load("facts.json", [])
        byid = {f["id"]: f for f in facts if f["status"] == "active"}
        for kind, ids, arg in ops:
            if kind == "drop" and ids[0] in byid:
                byid.pop(ids[0]).update(status="merged", updated=iso(), why=arg); changes += 1
            elif kind == "merge":
                group = [byid[i] for i in ids if i in byid]
                if len(group) < 2 or unsafe(arg): continue
                keep = max(group, key=lambda f: f.get("updated", ""))
                keep.update(text=arg, updated=iso(), private=any(f["private"] for f in group) or is_private(arg))
                for f in group:
                    if f is not keep: byid.pop(f["id"]).update(status="merged", updated=iso(), why=f"merged into {keep['id']}")
                changes += 1
            elif kind == "supersede":
                o, n = byid.get(ids[0]), byid.get(ids[1])
                if o and n and o is not n and n.get("updated", "") >= o.get("updated", ""):
                    byid.pop(o["id"]).update(status="removed", updated=iso(), why=f"replaced by newer {n['id']}"); changes += 1
            elif kind == "section" and ids[0] in byid and byid[ids[0]]["section"] == LEARNED and arg in SECTION_ORDER[:-2]:
                byid[ids[0]]["section"] = arg; changes += 1
        save("facts.json", facts)
    return changes

MISTAKE_PROMPT = """These voice tasks or calls went wrong. For each, write one short rule (max 25 words) that would avoid it
next time, as an instruction to the assistant ("When ..., do ..."). Skip items that were just tests with no lesson.
Return {"mistakes":[{"ref":"<ref>","what":"<what went wrong, one sentence>","rule":"<rule>"}]}.
Existing rules (do not repeat): %s

Items:
%s"""

def learn_mistakes():
    log_ = load("mistakes.json", [])
    known = {m["ref"] for m in log_}
    bad = []
    for e in journal_load():
        if e["ref"] in known: continue
        t = e["text"]
        if (e["source"] == "task" and ("FAILED" in t[:40] or re.search(r"\b(couldn't|could not|blocked|failed|error|wrong|by mistake|duplicate)\b", t[:600], re.I))) \
           or (e["source"] == "call" and re.search(r"restarted mid-call|dropped|that's wrong|not what i asked|you sent it twice", t, re.I)):
            bad.append(e)
    if not bad:
        return 0
    rules = [m["rule"] for m in log_]
    body = "\n\n".join(f"--- ref {e['ref']} ({e['source']}, {e['date']})\n{e['text'][:1500]}" for e in bad[:12])
    res = llm_json(MISTAKE_PROMPT % ("; ".join(rules[-15:]) or "none", body), timeout=180) or {}
    n = 0
    for m in res.get("mistakes", []) if isinstance(res, dict) else []:
        rule = clean(m.get("rule"), 200)
        if not rule or unsafe(rule) or any(similar(rule, r) for r in rules): continue
        log_.append(dict(id=nid("m"), date=iso(), ref=clean(m.get("ref"), 40), what=clean(m.get("what"), 200), rule=rule, status="active"))
        rules.append(rule); n += 1
    for e in bad[:12]:   # mark looked-at items so they are not re-sent every night
        if not any(m["ref"] == e["ref"] for m in log_):
            log_.append(dict(id=nid("m"), date=iso(), ref=e["ref"], what="reviewed, no lesson", rule="", status="none"))
    save("mistakes.json", log_)
    render_rules(log_)
    return n

def render_rules(log_):
    active = [m for m in log_ if m["status"] == "active" and m["rule"]][-15:]
    write_text(BASE / "rules.md", "# Rules learned from mistakes (newest last; made by voice-memory nightly and post-call reviews)\n\n" +
               "".join(f"- {m['rule']} ({m['date']})\n" for m in active))

LEARN_PROMPT = """From these signals about how the owner reacts to their assistant, propose at most 3 preferences that are
clearly supported (e.g. "Prefers calls after 10am", "Usually rewrites the closing of draft emails"). Each needs at least
3 separate supporting signals; ignore test calls and test tasks.
If nothing is clear, return an empty list. Return {"preferences":[{"text":"...","why":"evidence in a few words"}]}.

Signals:
%s"""

def behaviour_signals():
    sig = []
    ev = read_jsonl(CALLS)
    by = {}
    for x in ev:
        c = by.setdefault(x.get("call_id"), {"ts": x.get("time", 0), "reason": "", "res": None, "snooze": False})
        if x["event"] == "dialing": c["reason"] = x.get("reason", "")
        if x["event"] in ("answered", "not_answered") and c["res"] is None: c["res"] = x["event"]
        if "snooz" in x["event"]: c["snooze"] = True
    for c in by.values():
        if c["res"]:
            h = dt.datetime.fromtimestamp(c["ts"], TZ)
            sig.append(f"call {h:%a %H}h '{clean(c['reason'], 60)}': {c['res']}{', snoozed' if c['snooze'] else ''}")
    tasks = sorted((e for e in journal_load() if e["source"] == "task"), key=lambda e: e["ts"])
    for a, b in zip(tasks, tasks[1:] + [None]):
        redo = b is not None and b["ts"] - a["ts"] < 3600 and len(words(a["text"][:300]) & words(b["text"][:300])) >= 4
        sig.append(f"task {a['date']}: {clean(a.get('summary') or a['text'], 80)} -> {'redone/corrected soon after' if redo else 'accepted as is'}")
    try:
        for p in sorted((TASKS / "interviews").glob("*.json"))[-10:]:
            sig.append(f"interview debrief saved {iso(p.stat().st_mtime)} (thank-you draft made)")
    except PermissionError:
        pass
    return sig[-60:]

DRAFT_PROMPT = """Compare email drafts the assistant saved in the last 8 days with what the owner actually sent.
Use the Gmail tools only to read (search, read threads/drafts). For each draft, find the sent message on the same thread
or to the same person and note what the owner changed (tone, length, greeting, sign-off, facts). Never send or change anything.
Return {"diffs":[{"to":"...","change":"short description of what the owner changed, or 'sent as is' or 'not sent'"}]}"""

def draft_signals():
    recent = [e for e in journal_load() if e["source"] == "task" and e["ts"] > now() - 8 * 86400 and re.search(r"\bdraft", e["text"], re.I)]
    if not recent:
        return []
    tools = ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread", "mcp__claude_ai_Gmail__list_drafts",
             "mcp__claude_ai_Gmail__get_draft", "mcp__claude_ai_Gmail__get_message"]
    hint = "\n".join(f"- {e['date']}: {clean(e['text'], 200)}" for e in recent[:8])
    res = llm_json(DRAFT_PROMPT + "\n\nDraft tasks:\n" + hint, timeout=300, tools=tools) or {}
    return [f"draft to {clean(d.get('to'), 40)}: {clean(d.get('change'), 120)}" for d in res.get("diffs", []) if isinstance(d, dict)] \
        if isinstance(res, dict) else []

def learn_behaviour():
    sig = behaviour_signals() + draft_signals()
    if len(sig) < 3:
        return 0
    res = llm_json(LEARN_PROMPT % "\n".join(sig), timeout=120) or {}
    with Lock():
        return _apply_prefs(res)

def _apply_prefs(res):
    props, facts = load("proposals.json", []), load("facts.json", [])
    rejected = [p["text"] for p in props if p["status"] == "rejected"]
    n = 0
    for p in res.get("preferences", [])[:3] if isinstance(res, dict) else []:
        if isinstance(p, dict) and p.get("text") and not any(similar(p["text"], r) for r in rejected):
            if propose(props, facts, "preference", p["text"], p.get("why", "behaviour")): n += 1
    save("proposals.json", props)
    return n

CHECK_PROMPT = """Rewrite each item as a very short spoken yes/no check for the owner, like "Still waiting on Shopify?"
or "Are you still travelling this week?". Return {"q":{"<id>":"<question>"}}.

Items:
%s"""

def stale_items():
    """Open promises past due or untouched for 7+ days, and facts expiring within 2 days or already stale."""
    t = today(); wk = (t - dt.timedelta(days=7)).isoformat(); soon = (t + dt.timedelta(days=2)).isoformat()
    props = load("proposals.json", [])
    pending = {p.get("target") for p in props if p["kind"] == "check" and p["status"] == "pending"}
    out = []
    for p in load("promises.json", []):
        if p["status"] != "open" or f"promise:{p['id']}" in pending or (p.get("checked") or "") > wk: continue
        if (p.get("due") and p["due"] < t.isoformat()) or (p.get("updated") or p.get("created") or "") <= wk:
            out.append(("promise", p["id"], p["text"]))
    for f in load("facts.json", []):
        if f"fact:{f['id']}" in pending or f.get("checked"): continue
        if (f["status"] == "active" and f.get("expires") and f["expires"] <= soon) or f["status"] == "stale":
            out.append(("fact", f["id"], f["text"]))
    return out

def queue_checks():
    items = stale_items()
    if not items: return 0
    res = llm_json(CHECK_PROMPT % "\n".join(f"{i}: {txt}" for _k, i, txt in items), timeout=60) or {}
    qs = res.get("q", {}) if isinstance(res, dict) else {}
    n = 0
    with Lock():
        props, pr, facts = load("proposals.json", []), load("promises.json", []), load("facts.json", [])
        for kind, iid, txt in items:
            q = clean(qs.get(iid), 160) if isinstance(qs.get(iid), str) and not unsafe(qs.get(iid)) else None
            q = q or (f"Is this still open: {clean(txt, 120)}?" if kind == "promise" else f"Is this still true: {clean(txt, 120)}?")
            props.append(dict(id=nid("q"), kind="check", target=f"{kind}:{iid}", text=q, why=f"stale {kind}: {clean(txt, 120)}",
                              created=iso(), status="pending", private=is_private(txt), asked=None))
            for x in (pr if kind == "promise" else facts):
                if x["id"] == iid: x["checked"] = iso()
            n += 1
        save("proposals.json", props); save("promises.json", pr); save("facts.json", facts)
    return n

def todays_question():
    qs = load("questions.json", {})
    d = qs.get("days", {}).get(today().isoformat())
    if not d: return None
    p = next((p for p in load("proposals.json", []) if p["id"] == d), None)
    if not p or p["status"] != "pending": return None
    text = p["text"] if p["kind"] == "check" else f"Quick check, I noted about you: \"{p['text'].rstrip('.')}\". Is that right?"
    return {"id": p["id"], "text": text, "private": p.get("private")}

def pick_question():
    """At most one question per day: stale checks first (they are timely), then the oldest proposal. Never private."""
    qs = load("questions.json", {"days": {}})
    t = today().isoformat()
    if t in qs.setdefault("days", {}):
        return qs["days"][t]
    props = load("proposals.json", [])
    cand = sorted((p for p in props if p["status"] == "pending" and not p.get("asked") and not p.get("private")),
                  key=lambda p: (p["kind"] != "check", p.get("created", "")))
    if not cand: return None
    p = cand[0]; p["asked"] = t
    qs["days"][t] = p["id"]
    save("questions.json", qs); save("proposals.json", props)
    return p["id"]

def resolve_check(p, yes, text, facts, pr):
    kind, iid = p["target"].split(":", 1)
    if kind == "promise":
        for x in pr:
            if x["id"] == iid:
                if text: x.update(text=clean(text, 240), updated=iso())          # an update, still open
                elif yes: x.update(updated=iso())                                 # still open: ask again in a week
                else: x.update(status="done", updated=iso(), why="owner said no longer open")
    else:
        for f in facts:
            if f["id"] == iid:
                if text:
                    f.update(status="removed", updated=iso(), why="owner corrected it")
                    add_fact(facts, text, section=f["section"], private=f["private"], origin="check")
                elif yes:
                    f.update(status="active", expires=(today() + dt.timedelta(days=14)).isoformat(), checked=None, updated=iso())
                else:
                    f.update(status="stale", updated=iso(), why="owner said no longer true", checked=iso())

def confirm_cmd(a, yes=True):
    with Lock():
        props, facts, pr = load("proposals.json", []), load("facts.json", []), load("promises.json", [])
        hit = [p for p in props if p["id"] in a.ids]
        for p in hit:
            if p["kind"] == "check":
                resolve_check(p, yes, a.text, facts, pr)
                p.update(status="answered", answer=("update: " + a.text) if a.text else ("yes" if yes else "no"), answered=iso())
                continue
            if yes:
                add_fact(facts, a.text or p["text"], section=LEARNED, source="said", confidence="high",
                         private=p.get("private"), origin="confirmed")
            p.update(status="confirmed" if yes else "rejected", answered=iso())
        save("proposals.json", props); save("facts.json", facts); save("promises.json", pr)
    sync(quiet=True)
    print(f"{'Saved' if yes else 'Noted'}: {len(hit)}" + ("" if hit else " (no such id)")); return 0

def answer_cmd(a):
    ans = a.answer.strip().lower().rstrip(".!")
    yes_w, no_w = ("yes", "y", "right", "correct", "still", "still waiting", "yep"), ("no", "n", "wrong", "nope", "done")
    ns = argparse.Namespace(ids=[a.id], text=None if ans in yes_w or ans in no_w else a.answer)
    return confirm_cmd(ns, yes=ans not in no_w)

def nightly(a):
    t0 = time.time()
    report = {}
    sync(quiet=True)
    with Lock():
        report["caught_up"] = catch_up()
    report["processed"] = process_journal()
    report["deduped"] = dedupe_facts()
    report["promises_merged"] = dedupe_promises()
    report["mistakes"] = learn_mistakes()
    report["checks"] = queue_checks()
    try:
        import call_review
        report["lessons_merged"] = call_review.merge_lessons()
    except Exception as e:  # noqa: BLE001
        log(f"lesson merge failed: {e}")
    if not a.skip_learning:
        report["learned"] = learn_behaviour()
    with Lock():
        report["question"] = pick_question()
    sync(quiet=True)
    st = load("state.json", {})
    report["overflow"] = len(st.get("overflow", []))
    log("nightly " + json.dumps(report) + f" in {time.time() - t0:.0f}s")
    print(json.dumps(report)); return 0

# ---------------------------------------------------------------- weekly review (Telegram)
def weekly_text():
    wk = (today() - dt.timedelta(days=7)).isoformat()
    props = [p for p in load("proposals.json", []) if p["status"] == "pending"]
    facts = [f for f in load("facts.json", []) if f["status"] == "active" and f.get("added", "") >= wk and f["source"] == "inferred"]
    pr = [p for p in load("promises.json", []) if p["status"] == "open"]
    mist = [m for m in load("mistakes.json", []) if m["status"] == "active" and m["date"] >= wk]
    goals = [g for g in load("goals.json", []) if g["status"] == "active"]
    st = load("state.json", {})
    skills = []
    try:
        for d in SKILLS.iterdir():
            if d.is_dir() and (d.name.startswith("learned-") or d.name.startswith("voice-")) and \
               dt.date.fromtimestamp((d / "SKILL.md").stat().st_mtime).isoformat() >= wk:
                skills.append(d.name)
    except (FileNotFoundError, PermissionError):
        pass
    calls = [e for e in journal_load() if e["date"] >= wk]
    L = [f"Weekly memory review ({today():%b %-d})", f"This week: {sum(e['source'] == 'call' for e in calls)} calls, "
         f"{sum(e['source'] == 'task' for e in calls)} tasks, {sum(e['source'] == 'mac' for e in calls)} Mac sessions journaled."]
    saved = [f for f in load("facts.json", []) if f["status"] == "active" and f.get("added", "") >= wk
             and f["source"] != "inferred" and f.get("origin") != "import"]
    if saved:
        L.append("\nSaved this week:")
        L += [f"- {f['text']}" for f in saved[-6:] if not f["private"]]
        if any(f["private"] for f in saved):
            L.append(f"- plus {sum(f['private'] for f in saved)} private fact(s), not shown here")
    if props or facts:
        L.append("\nLearned - please confirm (reply e.g. 'confirm q1a2b3' or 'forget q1a2b3'):")
        L += [f"- {p['id']}: " + ("a private fact (ask me in chat to see it)" if p.get("private") else p["text"]) for p in props[:8]]
        L += [f"- {f['id']}: {f['text']} (saved, inferred)" for f in facts[:4] if not f["private"]]
    if pr:
        L.append("\nOpen promises / follow-ups:")
        L += [f"- {p['text']} ({p['who']}{', due ' + p['due'] if p.get('due') else ''})" for p in pr if not is_private(p["text"])][:8]
        if any(is_private(p["text"]) for p in pr):
            L.append(f"- plus {sum(is_private(p['text']) for p in pr)} private item(s) (money/IDs), ask me in chat")
    if mist:
        L.append("\nMistakes turned into rules:"); L += [f"- {m['rule']}" for m in mist[:5]]
    if skills:
        L.append("\nNew or improved skills: " + ", ".join(sorted(skills)))
    if st.get("overflow"):
        L.append(f"\nProfile is full: {len(st['overflow'])} low-priority facts are not loaded (kept in profile-full.md).")
    unconf = [g for g in goals if not g.get("confirmed")]
    L.append("\nPlans / goals: " + "; ".join(g["text"] + (" (confirm?)" if not g.get("confirmed") else "") for g in goals[:5]))
    if unconf:
        L.append("Reply 'goals ok' if these goals are right, or tell me the real ones.")
    return "\n".join(L)[:3900]

def telegram(text):
    env = dict(l.split("=", 1) for l in TG_ENV.read_text().splitlines() if "=" in l)
    chat = json.loads(TG_ACCESS.read_text())["allowFrom"][0]
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN'].strip()}/sendMessage", data, timeout=20).read()

def weekly(a):
    text = weekly_text()
    if a.print:
        print(text); return 0
    telegram(text)
    st = load("state.json", {}); st["weekly_sent"] = now(); save("state.json", st)
    log("weekly review sent"); print("sent"); return 0

def backfill(a):
    with Lock():
        n = catch_up()
    print(f"journaled {n} past calls/tasks")
    if not a.no_llm:
        print(f"processed {process_journal(limit=200)} entries")
        sync(quiet=True)
    return 0

def question_cmd(_):
    q = todays_question()
    print(f"{q['text']} (answer with: voice-memory answer {q['id']} yes|no|<correction>)" if q else "No question today.")
    return 0

# ---------------------------------------------------------------- CLI
def main(argv=None):
    os.umask(0o007)
    ap = argparse.ArgumentParser(prog="voice-memory", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("context", help="compact memory block for the voice prompt (no private facts)")
    c.add_argument("--today", default="", help="optional: text of today's calendar events, to pick relevant people")
    r = sub.add_parser("recall", help="answer a question from memory, with sources")
    r.add_argument("question"); r.add_argument("--voice", action="store_true", help="redact private facts (spoken answer)")
    r.add_argument("--timeout", type=int, default=12)
    b = sub.add_parser("brief", help="briefing before a meeting/call")
    b.add_argument("--event", required=True, help="JSON: title, start, attendees, description, location")
    b.add_argument("--voice", action="store_true"); b.add_argument("--no-llm", action="store_true")
    b.add_argument("--timeout", type=int, default=10)
    j = sub.add_parser("journal", help="add or update a journal entry")
    j.add_argument("--source", required=True, choices=["call", "task", "mac", "note", "imessage", "telegram"]); j.add_argument("--id", required=True)
    j.add_argument("--text", required=True, help="text, or - for stdin"); j.add_argument("--summary")
    j.add_argument("--time", type=float)
    m = sub.add_parser("remember", help="save a fact about the owner")
    m.add_argument("--fact", required=True); m.add_argument("--source", default="said", choices=["said", "email", "inferred"])
    m.add_argument("--confidence", default="high", choices=["high", "low"]); m.add_argument("--private", action="store_true")
    m.add_argument("--expires"); m.add_argument("--origin", default="cli")
    sub.add_parser("sync", help="merge edits of profile.md / USER.md / inbox and regenerate views")
    for name, fn in (("promise", promise_cmd), ("goal", goal_cmd)):
        p = sub.add_parser(name); p.add_argument("action", choices=["list", "add", "done", "drop"] + (["confirm"] if name == "goal" else []))
        p.add_argument("text", nargs="?", default=""); p.add_argument("--who", default="assistant"); p.add_argument("--due")
        p.add_argument("--kind", default="promise", choices=["promise", "followup"]); p.set_defaults(fn=fn)
    p = sub.add_parser("people"); p.add_argument("name", nargs="?", default="")
    p = sub.add_parser("journal-delete", aliases=["journal-archive"], help="archive journal entries (never deleted)"); p.add_argument("ids", nargs="+")
    p = sub.add_parser("project"); p.add_argument("action", choices=["list", "add", "show", "done", "pause", "active"])
    p.add_argument("text", nargs="?", default=""); p.add_argument("--keywords"); p.set_defaults(fn=project_cmd)
    for name in ("confirm", "reject"):
        p = sub.add_parser(name); p.add_argument("ids", nargs="+"); p.add_argument("--text")
    p = sub.add_parser("answer"); p.add_argument("id"); p.add_argument("answer")
    sub.add_parser("question")
    p = sub.add_parser("nightly"); p.add_argument("--skip-learning", action="store_true")
    p = sub.add_parser("weekly"); p.add_argument("--print", action="store_true")
    p = sub.add_parser("backfill"); p.add_argument("--no-llm", action="store_true")
    sub.add_parser("mac-ingest"); sub.add_parser("llm-serve")
    sub.add_parser("review-pending", help="post-call review of calls that ended 2+ min ago")
    p = sub.add_parser("review-call"); p.add_argument("call_id"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--print", action="store_true")
    p = sub.add_parser("review-text", help="review a finished iMessage/Ask/Telegram conversation (--list to see ids)")
    p.add_argument("id", nargs="?"); p.add_argument("--list", action="store_true"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("lessons", help="voice lessons: list, undo ID, approve ID, reject ID, merge")
    p.add_argument("action", nargs="?", default="list", choices=["list", "undo", "approve", "reject", "merge"]); p.add_argument("id", nargs="?")
    a = ap.parse_args(argv)
    fns = dict(context=context_cmd, recall=recall_cmd, brief=brief_cmd, journal=journal_cmd, remember=remember,
               sync=lambda a: (print(f"{sync()} change(s)") or 0), people=people_cmd, confirm=confirm_cmd,
               reject=lambda a: confirm_cmd(a, yes=False), answer=answer_cmd, question=question_cmd, nightly=nightly,
               weekly=weekly, backfill=backfill, **{"mac-ingest": mac_ingest, "llm-serve": llm_serve, "journal-delete": journal_delete, "journal-archive": journal_delete})
    if a.cmd in ("review-pending", "review-call", "review-text", "lessons"):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import call_review
        fns.update({"review-pending": lambda a: print(call_review.review_pending()) or 0,
                    "review-call": lambda a: print(call_review.review_call(a.call_id, dry=a.dry_run, show=True)) or 0,
                    "review-text": call_review.review_text_cmd, "lessons": call_review.lessons_cmd})
    fn = getattr(a, "fn", None) or fns[a.cmd]
    try:
        return fn(a) or 0
    except BrokenPipeError:
        return 0

if __name__ == "__main__":
    sys.exit(main())
