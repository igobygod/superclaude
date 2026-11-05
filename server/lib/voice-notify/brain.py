"""Gemini text brain for iMessage / Ask Claude (same persona + rules as the phone line, written-text version).
Gemini answers quick things; real work is delegated to Claude. Any Gemini problem raises BrainError -> caller falls back to Claude."""
import json, os, re, socket, subprocess, time
from datetime import datetime
from zoneinfo import ZoneInfo

TZNAME = os.environ.get("AGENT_TZ", "UTC")
SOCK = "/run/voice-gemini-chat/chat.sock"
CAPS = "/var/lib/voice-tasks/capabilities.md"
PERSONA = """You are the owner's personal assistant, now answering by TEXT MESSAGE (iMessage / the Ask Claude shortcut). Behind you is
Claude, a capable agent on their server (Claude Code with their Gmail, Google Calendar, web browser, files, Telegram and their Mac).
You do the talking; Claude does the work.

Personality: a composed, quietly confident butler-style assistant: calm, precise, with an occasional dry touch of wit (rare, never at
the cost of speed or clarity). Anticipate the next need. Acknowledge crisply ("Right away.", "One moment.", "Done."); address the
owner as "sir" now and then or by name, unless memory says otherwise. Only a style; never claim to be a fictional character.
How to write: SMS style: plain words, short, at most about 500 characters, no markdown, no lists, no links or long numbers unless asked.
The owner is a beginner. English by default (reply in another language only if they write in it).
Current time: {now} ({tz}). The owner's email: {owner_email}.

About the owner:
{profile}

Memory (goals, past calls and texts, promises, people):
{memory}
Memory rules: act only on facts the owner SAID; facts marked inferred or "may be out of date": check with them first. A line starting
"PRIVATE:" means private info (immigration, money, IDs) is held by Claude: never guess or say it; reply "I have that, I'll have Claude
handle it" and call delegate_to_claude. For anything older or not shown, use recall.

Open questions waiting on the owner (ids are for you; do not show them):
{questions}
Recently answered (already handled; never act on them again):
{recent}

Lessons learned from past calls and texts (follow them; newest wins):
{lessons}

What Claude can use right now: {caps}
NEVER say Claude can't do something or lacks access or logins; delegate it and let Claude report back.

Rules:
- Quick things you can answer from this prompt or the thread (chit-chat, what's pending, simple facts, the time): answer directly, instantly.
- Anything that needs real work, current information, email, calendar, web, files, the Mac, or changing anything: call delegate_to_claude with a
  self-contained task (names, the owner's exact words, their method if they gave one) AND write a short acknowledgement ("On it, sir." / "Right away.").
  Claude's result will be texted to them afterwards. One task per goal: never delegate something already running or just finished in the thread.
- You NEVER send email, texts or messages to anyone yourself, and never change or cancel anything yourself: delegate. When the work involves
  sending, tell Claude to read back the exact recipient and text and ask "Shall I send it?" first.
- Short replies ("Which?", "yes", "the second one", "why?") refer to the last text you sent (see the thread, including texts other systems sent) or to an
  open question: resolve them from that; never ask "what is this about" if the thread shows it. A "yes" answering an open question: call answer_question; if
  it says "already done", tell them "already done ✓" and do nothing more; if it succeeds and the question needs action, then also delegate_to_claude (once).
- If the owner shares something to remember (lasting preference or fact), call remember (private=true for immigration, money, ID details).
- NEVER say something is done, saved, set, sent, scheduled, on or off unless a tool result in THIS turn confirms it (the thread is not proof, and
  your delegation is not proof). If asked about the state of something, or to do something, delegate and say only "On it, sir." Do not promise what
  Claude will do or show; Claude reports for itself.
- Never invent emails, events or results. If you don't know, delegate or use recall. Never leave a message without a reply."""

TOOLS = [
    {"name": "delegate_to_claude", "description": "Hand real work to Claude (email, calendar, web, files, Mac, research, anything that does or changes something). Claude texts the result later.",
     "parameters": {"type": "OBJECT", "properties": {"task": {"type": "STRING", "description": "Self-contained task with names and the owner's exact wording"}}, "required": ["task"]}},
    {"name": "recall", "description": "Look up anything from past calls, texts, emails, people, projects or promises in long-term memory.",
     "parameters": {"type": "OBJECT", "properties": {"question": {"type": "STRING"}}, "required": ["question"]}},
    {"name": "remember", "description": "Save a lasting fact or preference the owner just told you.",
     "parameters": {"type": "OBJECT", "properties": {"fact": {"type": "STRING"}, "private": {"type": "BOOLEAN"}}, "required": ["fact"]}},
    {"name": "answer_question", "description": "The owner answered an open question. Closes it for iMessage, Telegram and calls (first answer wins).",
     "parameters": {"type": "OBJECT", "properties": {"id": {"type": "STRING"}, "answer": {"type": "STRING"}}, "required": ["id", "answer"]}},
]


CLAIM = re.compile(r"\b(done|saved|i(?:'ve| have)? (?:set|saved|turned|sent|created|scheduled|added|cancel)\w*|turned (?:it )?on|turned (?:it )?off|is (?:now )?(?:set|on|scheduled|sent)|has been (?:sent|set|saved)|reminder (?:is )?set|(?:i )?sent it)\b", re.I)


class BrainError(Exception):
    pass


def cli(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 1, str(e)


def gemini(system, contents, tools=None, timeout=14, max_tokens=700, rtimeout=2.5):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        for attempt in range(3):  # the service restarts during deploys: retry briefly
            try:
                s.connect(SOCK)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if attempt == 2:
                    raise
                time.sleep(2)
        s.sendall((json.dumps({"system": system, "contents": contents, "tools": tools, "model": "fast", "max_tokens": max_tokens, "timeout": rtimeout}) + "\n").encode())
        b = b""
        while not b.endswith(b"\n"):
            ch = s.recv(65536)
            if not ch:
                break
            b += ch
        r = json.loads(b)
    except Exception as e:
        raise BrainError(f"gemini socket: {e}")
    finally:
        s.close()
    if not r.get("ok"):
        raise BrainError(r.get("error", "gemini failed"))
    if r.get("finish") == "MAX_TOKENS":
        raise BrainError("reply truncated (max tokens)")
    return r


def inline(path):
    import base64, mimetypes
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if path.endswith(".mp3"):
        mime = "audio/mpeg"
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(open(path, "rb").read()).decode()}}


def transcribe(path):
    """Voice note -> words (Gemini). Raises BrainError if it fails."""
    if os.path.getsize(path) > 15 * 1024 * 1024:
        raise BrainError("audio too big for inline transcription")
    r = gemini("You transcribe audio exactly. Output only the spoken words, no commentary. If it is silent or unintelligible output EMPTY.",
               [{"role": "user", "parts": [inline(path), {"text": "Transcribe this voice note."}]}], None, 90, 2000, 20)
    t = "".join(p.get("text", "") for p in r["content"].get("parts", [])).strip()
    if not t or t.upper().startswith("EMPTY"):
        raise BrainError("no speech")
    return t


def tool(name, args, qinfo):
    if name == "recall":
        rc, out = cli(["/usr/local/bin/voice-memory", "recall", str(args.get("question", "")), "--voice"], 25)
        return {"result": out[:1500] or "nothing found"}
    if name == "remember":
        a = ["/usr/local/bin/voice-memory", "remember", "--fact", str(args.get("fact", ""))[:500], "--source", "said", "--confidence", "high"]
        if args.get("private"):
            a.append("--private")
        rc, out = cli(a)
        return {"result": "saved" if rc == 0 else "could not save: " + out[:100]}
    if name == "answer_question":
        rc, out = cli(["/usr/local/bin/voice-questions", "answer", str(args.get("id", "")), "--via", "imessage", "--text", str(args.get("answer", ""))[:300]])
        qinfo.append((rc, out))
        return {"result": out[:300], "already_done": rc == 3}
    return {"result": "unknown tool"}


LIM = {"profile": 1500, "memory": 1200, "lessons": 1200} if os.environ.get("VN_LIMITS") != "old" else {"profile": 3500, "memory": 2600, "lessons": 3500}


def lessons() -> str:
    try:
        return open(os.environ.get("VN_LESSONS", "/var/lib/voice-tasks/voice-lessons.md")).read().strip()[-LIM["lessons"]:] or "none yet"
    except OSError:
        return "none yet"


def run(message, history, profile, memory, questions, recent, caps_line, images=()):
    """Returns (reply_text, delegated_task or None, info dict). Raises BrainError on any Gemini problem."""
    system = PERSONA.format(now=datetime.now(ZoneInfo(TZNAME)).strftime("%A %B %d, %I:%M %p"), tz=TZNAME, owner_email=os.environ.get("OWNER_EMAIL", "owner@example.com"), profile=profile[:LIM["profile"]], memory=memory[:LIM["memory"]], questions=questions or "none",
                            recent=recent or "none", caps=caps_line, lessons=lessons())
    img = [inline(p) for p in list(images)[:4] if os.path.exists(p) and os.path.getsize(p) < 8 * 1024 * 1024]
    contents = [{"role": "user", "parts": img + [{"text": f"Recent text thread (oldest first):\n{history}\n\nNew text from the owner (attached pictures, if any, are what they sent; their file paths are in the text):\n{message}"}]}]
    delegated, texts, qinfo, ms, calls, confirmed, ptok = None, [], [], 0, 0, False, 0
    for _ in range(4):
        r = gemini(system, contents, TOOLS, 40 if img else 14, 700, 8 if img else 2.5)
        ptok += (r.get("tokens") or {}).get("prompt") or 0
        ms += r["ms"]
        content = r["content"]
        parts = content.get("parts", [])
        texts += [p["text"] for p in parts if p.get("text")]
        fcs = [p["functionCall"] for p in parts if p.get("functionCall")]
        if not fcs:
            break
        contents.append(content)
        resp = []
        for fc in fcs:
            calls += 1
            if fc["name"] == "delegate_to_claude":
                delegated = (delegated + "\n" if delegated else "") + str(fc.get("args", {}).get("task", ""))
                resp.append({"functionResponse": {"name": fc["name"], "response": {"result": "Claude has the task and will text the result."}}})
            else:
                res = tool(fc["name"], fc.get("args", {}), qinfo)
                if fc["name"] in ("remember", "answer_question") and not res.get("already_done") and "could not" not in str(res.get("result", "")):
                    confirmed = True
                resp.append({"functionResponse": {"name": fc["name"], "response": res}})
        contents.append({"role": "user", "parts": resp})
    reply = "\n".join(t.strip() for t in texts if t.strip())
    if not reply and not delegated:
        raise BrainError("empty answer")
    claim = CLAIM.search(reply)
    guarded = False
    if (claim and not confirmed) or (delegated and reply):
        # code guard: no completion claims without a confirming tool result; a delegation gets a neutral acknowledgement only
        reply = "On it, sir." if (delegated or claim) else reply
        delegated = delegated or message
        guarded = bool(claim and not confirmed)
    return reply, delegated, {"ms": ms, "calls": calls, "answered": qinfo, "guarded": guarded, "prompt_tokens": ptok, "model": r.get("model")}
