"""Decides when to phone the user, and escalates when they don't answer.

Sources: Google Calendar (private iCal feed), important emails queued by the Gmail
sorter (Claude decides if they're call-worthy), and snoozes made during calls.
Calls go through call.place_call(); missed calls and call notes go to Telegram.
"""

import asyncio
import datetime as dt
import json
import subprocess
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import icalendar
import recurring_ical_events

from livekit import api

from call import place_call

log = logging.getLogger("watcher")
TZ = ZoneInfo(os.environ.get("AGENT_TZ", "UTC"))
STATE = Path(os.environ.get("VOICECALLER_STATE", "/var/lib/voicecaller"))
CALLS_LOG = STATE / "calls.jsonl"
SNOOZE_FILE = STATE / "snoozes.json"
WATCH_STATE = STATE / "watcher.json"
EMAIL_QUEUE = Path(os.environ.get("EMAIL_QUEUE", "/var/lib/voice-email/kept-for-caller.jsonl"))
TASKS = Path("/var/lib/voice-tasks")
WATCHES = TASKS / "watches"  # "call me when they reply" requests (from calls or Telegram)
INTERVIEW_WORDS = ("interview", "screening", "phone screen", "recruiter", "hiring", "technical round", "onsite")
DEBRIEF_AFTER = (4, 25)  # call this many minutes after an interview ends (window)
REPORTED = STATE / "reported.json"  # finished tasks already told to the owner (shared with agent.py)
CALL_TOKEN = os.environ.get("CALL_TOKEN", "")
HTTP_PORT = 7891
ME = (os.environ.get("OWNER_EMAIL") or os.environ.get("MY_EMAIL", "owner@example.com")).lower()

LEAD_MINUTES = 10          # call this long before a meeting
CALENDAR_REFRESH = 300     # seconds between calendar downloads
RETRY_AFTER = 180          # seconds before calling again after a missed call
MAX_TRIES = 2
QUIET_HOURS = os.environ.get("QUIET_HOURS", "23-7")  # no calls overnight, Telegram only; "off" disables
MAX_EMAIL_CHECKS_PER_DAY = 40
EMAIL_MAX_AGE = 30 * 60    # ignore queued emails older than this (e.g. after downtime)
TRIAGE_MODEL = "claude-haiku-5-5"

TRIAGE_PROMPT = """You decide whether an email is urgent enough to PHONE someone who is busy (e.g. at the gym).
Phone only for things that lose value within the next hour or two: an interview or meeting being moved or starting soon,
a recruiter or employer asking for a reply today, a security or account problem needing action now, a family emergency,
a delivery or appointment needing them right now. Do NOT phone for newsletters, receipts, normal job alerts,
applications received, promotions, or anything that can wait a few hours.
The owner may also be waiting for specific replies (WATCHES below). If this email is a reply from, or clearly about,
one of them, set "watch" to its id (then it is call-worthy too).
Set "job_reply" true if it's a recruiter or employer replying about a job application or interview (even if not urgent).
Reply with JSON only: {"call": true|false, "job_reply": true|false, "watch": "<watch id or null>", "summary": "<=20 words, what it is and what they may need to do, no codes or passwords>"}"""


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def telegram(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=15).read()
    except Exception as e:
        log.warning("telegram failed: %s", e)


def notify(level: str, text: str) -> None:
    """voice-notify: iMessage, then a call if still unanswered (important), with Telegram fallback."""
    try:
        r = subprocess.run(["voice-notify", "--level", level, "--text", text[:600], "--no-wait"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return
        log.warning("voice-notify rc %s: %s", r.returncode, r.stderr[-200:])
    except Exception as e:
        log.warning("voice-notify failed: %s", e)
    telegram(text)


def quiet_now() -> bool:
    if QUIET_HOURS == "off":
        return False
    start, end = (int(x) for x in QUIET_HOURS.split("-"))
    h = dt.datetime.now(TZ).hour
    return (h >= start or h < end) if start > end else (start <= h < end)


class Watcher:
    def __init__(self) -> None:
        self.state = load(WATCH_STATE, {"alerted": {}, "email_offset": None, "calls_offset": 0, "email_checks": {}})
        self.pending: list[dict] = []   # alerts waiting for a call (or a retry)
        self.active: dict | None = None  # the call being placed
        self.in_call: dict[str, float] = {}  # answered calls not yet ended
        self.rooms_checked = 0.0
        self.cal = None
        self.cal_fetched = 0.0
        self.claude = anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None
        if self.state["email_offset"] is None:  # start from now, don't replay old mail
            self.state["email_offset"] = EMAIL_QUEUE.stat().st_size if EMAIL_QUEUE.exists() else 0
        if not self.state["calls_offset"] and CALLS_LOG.exists():
            self.state["calls_offset"] = CALLS_LOG.stat().st_size

    # ---------- sources ----------
    def check_calendar(self) -> None:
        url = os.environ.get("CALENDAR_ICS_URL")
        if not url:
            return
        if time.time() - self.cal_fetched > CALENDAR_REFRESH:
            try:
                raw = urllib.request.urlopen(url, timeout=30).read()
                self.cal = icalendar.Calendar.from_ical(raw)
                self.cal_fetched = time.time()
            except Exception as e:
                log.warning("calendar fetch failed: %s", e)
        if self.cal is None:
            return
        now = dt.datetime.now(TZ)
        for ev in recurring_ical_events.of(self.cal).between(now, now + dt.timedelta(minutes=LEAD_MINUTES)):
            start = ev.get("DTSTART").dt
            if not isinstance(start, dt.datetime):
                continue  # all-day event
            if str(ev.get("STATUS", "")).upper() == "CANCELLED" or self.declined(ev):
                continue
            start = start.astimezone(TZ) if start.tzinfo else start.replace(tzinfo=TZ)
            key = f"cal:{ev.get('UID')}:{start.isoformat()}"
            if key in self.state["alerted"] or start < now:
                continue
            self.state["alerted"][key] = time.time()
            title = str(ev.get("SUMMARY", "an event"))
            mins = max(1, round((start - now).total_seconds() / 60))
            where = str(ev.get("LOCATION", "")).strip()
            brief = self.brief(ev, title, start)
            self.queue(
                reason=f"{title} starts in {mins} minutes, at {start.strftime('%-I:%M %p')}",
                details=(f"Location or link: {where[:150]}" if where else "No location given.") +
                        (f"\nBriefing from memory (offer it, keep it short): {brief}" if brief else ""),
                text=f"📅 {title} at {start.strftime('%-I:%M %p')}" + (f" — {where[:150]}" if where else ""),
            )

        self.check_debriefs(now)

    def check_debriefs(self, now: dt.datetime) -> None:
        """A few minutes after an interview ends, call to capture how it went."""
        lo, hi = DEBRIEF_AFTER
        for ev in recurring_ical_events.of(self.cal).between(now - dt.timedelta(minutes=hi + 240), now):
            title = str(ev.get("SUMMARY", ""))
            end = ev.get("DTEND").dt if ev.get("DTEND") else None
            if not isinstance(end, dt.datetime) or not any(w in title.lower() for w in INTERVIEW_WORDS):
                continue
            if str(ev.get("STATUS", "")).upper() == "CANCELLED" or self.declined(ev):
                continue
            end = end.astimezone(TZ) if end.tzinfo else end.replace(tzinfo=TZ)
            mins = (now - end).total_seconds() / 60
            key = f"debrief:{ev.get('UID')}:{end.isoformat()}"
            if not lo <= mins <= hi or key in self.state["alerted"]:
                continue
            self.state["alerted"][key] = time.time()
            self.queue(
                reason=f"Quick debrief: your '{title}' just ended. How did it go?",
                details=("DEBRIEF CALL. Ask these one at a time, briefly: 1) How did it go overall? 2) What did they ask "
                         "or focus on? 3) Anything you're worried about or want to follow up? 4) Next steps, and the "
                         "interviewer's name? Then call save_interview_debrief with the company and all their answers. "
                         f"Event: {title}. Organizer/attendees: {str(ev.get('ORGANIZER', ''))[:120]}"),
                text=f"🎤 Debrief: how did '{title}' go?",
            )

    @staticmethod
    def brief(ev, title: str, start: dt.datetime) -> str:
        """Pre-meeting briefing from the owner's memory (people, past emails, promises); '' if unavailable."""
        att = ev.get("ATTENDEE") or []
        att = att if isinstance(att, list) else [att]
        event = {"title": title, "start": start.isoformat(), "description": str(ev.get("DESCRIPTION", ""))[:500],
                 "attendees": [str(a).removeprefix("mailto:") for a in att][:10]}
        try:
            r = subprocess.run(["voice-memory", "brief", "--event", json.dumps(event), "--voice"],
                               capture_output=True, text=True, timeout=15)
            return r.stdout.strip()[:1200] if r.returncode == 0 else ""
        except Exception as e:
            log.warning("brief failed: %s", e)
            return ""

    @staticmethod
    def declined(ev) -> bool:
        attendees = ev.get("ATTENDEE") or []
        if not isinstance(attendees, list):
            attendees = [attendees]
        for a in attendees:
            if ME in str(a).lower() and str(a.params.get("PARTSTAT", "")).upper() == "DECLINED":
                return True
        return False

    def check_email(self) -> None:
        if not EMAIL_QUEUE.exists() or not self.claude:
            return
        size = EMAIL_QUEUE.stat().st_size
        if size < self.state["email_offset"]:
            self.state["email_offset"] = 0  # file was replaced
        if size == self.state["email_offset"]:
            return
        with EMAIL_QUEUE.open() as f:
            f.seek(self.state["email_offset"])
            lines = f.readlines()
            self.state["email_offset"] = f.tell()
        today = dt.date.today().isoformat()
        for line in lines:
            try:
                mail = json.loads(line)
            except json.JSONDecodeError:
                continue
            if time.time() - mail.get("time", 0) > EMAIL_MAX_AGE:
                continue
            used = self.state["email_checks"].get(today, 0)
            if used >= MAX_EMAIL_CHECKS_PER_DAY:
                log.warning("daily email check limit reached")
                return
            self.state["email_checks"] = {today: used + 1}
            watches = self.active_watches()
            verdict = self.triage(mail, watches)
            log.info("email from %s -> %s", mail.get("from"), verdict)
            w = watches.get(str(verdict.get("watch") or ""))
            if w:
                (WATCHES / f"{w['id']}.json").unlink(missing_ok=True)
                summary = verdict.get("summary") or mail.get("subject", "")
                self.queue(
                    reason=f"The reply you were waiting for from {w['who']} arrived: {summary}",
                    details=(f"From {mail.get('from', '')[:80]}. Subject: {mail.get('subject', '')[:120]}. It's email 1 in "
                             "recent_emails; offer to read it or reply."),
                    text=f"📬 Reply from {w['who']}: {summary}",
                )
            elif verdict.get("job_reply") and not verdict.get("call"):
                summary = verdict.get("summary") or mail.get("subject", "")
                notify("important", f"📧 Job reply from {mail.get('from', '')[:60]}: {summary}")
            elif verdict.get("call"):
                summary = verdict.get("summary") or mail.get("subject", "")
                self.queue(
                    reason=f"Urgent email: {summary}",
                    details=f"From {mail.get('from', '')[:80]}. Subject: {mail.get('subject', '')[:120]}",
                    text=f"📧 Urgent: {summary}\nFrom: {mail.get('from', '')[:80]}",
                )

    @staticmethod
    def active_watches() -> dict:
        watches = {}
        for f in WATCHES.glob("*.json") if WATCHES.exists() else []:
            w = load(f, None)
            if not w or w.get("expires", 0) < time.time():
                if w:
                    telegram(f"⌛ Stopped waiting for a reply from {w.get('who')} (no reply in time).")
                f.unlink(missing_ok=True)
                continue
            watches[str(w["id"])] = w
        return watches

    def triage(self, mail: dict, watches: dict | None = None) -> dict:
        msg = f"From: {mail.get('from')}\nSubject: {mail.get('subject')}\n\n{mail.get('body', '')[:2000]}"
        if watches:
            msg = "WATCHES:\n" + "\n".join(f"- id {w['id']}: reply from {w['who']}" + (f" about {w['about']}" if w.get("about") else "")
                                           for w in watches.values()) + "\n\nEMAIL:\n" + msg
        try:
            r = self.claude.messages.create(
                model=TRIAGE_MODEL, max_tokens=150, system=TRIAGE_PROMPT,
                messages=[{"role": "user", "content": msg}],
            )
            text = r.content[0].text.strip()
            return json.loads(text[text.index("{"): text.rindex("}") + 1])
        except Exception as e:
            log.warning("triage failed: %s", e)
            return {"call": False}

    def check_snoozes(self) -> None:
        snoozes = load(SNOOZE_FILE, [])
        due = [s for s in snoozes if s.get("due", 0) <= time.time()]
        if not due:
            return
        save(SNOOZE_FILE, [s for s in snoozes if s.get("due", 0) > time.time()])
        for s in due:
            self.queue(reason=f"Snoozed reminder: {s.get('reason', '')}", details=s.get("details", "none"),
                       text=f"⏰ Snoozed reminder: {s.get('reason', '')}")

    # ---------- calling ----------
    def check_finished_tasks(self) -> None:
        """Call the owner when a task they gave by voice finishes (unless already told on a call)."""
        self.read_call_events()  # know which calls are live right now
        reported = load(REPORTED, [])
        for f in (TASKS / "done").glob("*.json"):
            tid = f.stem
            if tid in reported:
                continue
            done = load(f, None)
            if not done or done.get("call_id") in self.in_call:
                continue  # the live call announces it itself
            reported = (reported + [tid])[-500:]
            save(REPORTED, reported)
            if not done.get("callback") or time.time() - done.get("finished", 0) > 7200:
                continue
            if quiet_now():
                continue  # Telegram already has the result from the job update
            self.queue(reason=f"Claude finished the task you gave: {done.get('spoken', '')}",
                       details=f"Task was: {done.get('task', '')[:300]}. Extra details: {done.get('details', '')[:600]}",
                       text=f"✅ {done.get('spoken', '')}")

    def check_call_requests(self) -> None:
        """Claude (the Telegram helper) can ask for a call by writing a JSON file here."""
        for f in sorted((TASKS / "call-requests").glob("*.json")):
            req = load(f, {})
            f.unlink(missing_ok=True)
            if req.get("reason"):
                self.queue(reason=str(req["reason"])[:300], details=str(req.get("details", "none"))[:1000],
                           text=f"📞 {str(req['reason'])[:300]}", force=bool(req.get("urgent")))

    async def http_handler(self, reader, writer) -> None:
        """Tiny endpoint for the iPhone 'Call me' shortcut (behind Nginx with a secret path)."""
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace")
            path = line.split(" ")[1] if line.count(" ") >= 2 else ""
            ok = bool(CALL_TOKEN) and path.rstrip("/") == f"/call/{CALL_TOKEN}"
            if ok:
                self.queue(reason="The owner tapped Call me and wants to talk",
                           details="Ask what they need. You can give tasks to Claude or check Claude's jobs.",
                           text="📞 Calling you now", force=True, retry=False)
                self.wakeup.set()
            body = b"Calling you now" if ok else b"Not found"
            writer.write(b"HTTP/1.1 " + (b"200 OK" if ok else b"404 Not Found") +
                         b"\r\nContent-Type: text/plain\r\nContent-Length: " + str(len(body)).encode() +
                         b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
        except Exception as e:
            log.warning("http error: %s", e)
        finally:
            writer.close()

    def queue(self, reason: str, details: str, text: str, force: bool = False, retry: bool = True) -> None:
        log.info("alert: %s", reason)
        if quiet_now() and not force:
            telegram(text + "\n(Quiet hours, so no call.)")
            return
        self.pending.append({"reason": reason, "details": details, "text": text, "tries": 0, "not_before": 0,
                             "max_tries": MAX_TRIES if retry else 1})

    async def run_calls(self) -> None:
        self.read_call_events()
        self.in_call = {k: v for k, v in self.in_call.items() if time.time() - v < 25 * 60}
        if self.active or self.in_call or not self.pending:
            return  # one call at a time
        nxt = next((a for a in self.pending if a["not_before"] <= time.time()), None)
        if not nxt:
            return
        self.pending.remove(nxt)
        nxt["tries"] += 1
        try:
            nxt["call_id"] = await place_call(nxt["reason"], nxt["details"])
            nxt["started"] = time.time()
            self.active = nxt
        except Exception as e:
            log.warning("could not place call: %s", e)
            telegram(nxt["text"] + "\n(Couldn't place a call.)")

    def read_call_events(self) -> None:
        if not CALLS_LOG.exists():
            return
        with CALLS_LOG.open() as f:
            f.seek(self.state["calls_offset"])
            lines = f.readlines()
            self.state["calls_offset"] = f.tell()
        for line in lines:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "note":
                telegram(f"📝 From your call: {ev.get('note', '')}")
            if ev.get("event") == "answered":
                self.in_call[ev.get("call_id")] = time.time()
            elif ev.get("event") == "ended":
                self.in_call.pop(ev.get("call_id"), None)
            a = self.active
            if not a or ev.get("call_id") != a.get("call_id"):
                continue
            if ev.get("event") == "answered":
                self.active = None
            elif ev.get("event") == "not_answered":
                self.active = None
                if a["tries"] < a.get("max_tries", MAX_TRIES):
                    a["not_before"] = time.time() + RETRY_AFTER
                    self.pending.append(a)
                    telegram(a["text"] + f"\n(Missed call — I'll call again in {RETRY_AFTER // 60} min.)")
                else:
                    telegram(a["text"] + "\n(Missed calls — not calling again.)")
        if self.active and time.time() - self.active["started"] > 120:
            log.warning("no outcome for %s, giving up waiting", self.active.get("call_id"))
            self.active = None

    async def check_rooms(self) -> None:
        """A call whose LiveKit room is gone is over, even if its 'ended' event never got written."""
        if not self.in_call or time.time() - self.rooms_checked < 60:
            return
        self.rooms_checked = time.time()
        async with api.LiveKitAPI() as lk:
            live = {r.name for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms}
        for call_id in [c for c in self.in_call if c not in live]:
            self.in_call.pop(call_id, None)
            with CALLS_LOG.open("a") as f:
                f.write(json.dumps({"call_id": call_id, "time": time.time(), "event": "ended", "note": "room gone"}) + "\n")
            log.warning("call %s had no 'ended' event but its room is gone; marked ended", call_id)

    def prune(self) -> None:
        cutoff = time.time() - 3 * 86400
        self.state["alerted"] = {k: v for k, v in self.state["alerted"].items() if v > cutoff}

    async def run(self) -> None:
        log.info("watcher started")
        self.wakeup = asyncio.Event()
        await asyncio.start_server(self.http_handler, "127.0.0.1", HTTP_PORT)
        while True:
            self.wakeup.clear()
            for step in (self.check_calendar, self.check_email, self.check_snoozes,
                         self.check_finished_tasks, self.check_call_requests):
                try:
                    step()
                except Exception:
                    log.exception("%s failed", step.__name__)
            try:
                await self.check_rooms()
            except Exception:
                log.exception("room check failed")
            try:
                await self.run_calls()
            except Exception:
                log.exception("calling failed")
            self.prune()
            save(WATCH_STATE, self.state)
            try:
                await asyncio.wait_for(self.wakeup.wait(), 3)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(Watcher().run())
