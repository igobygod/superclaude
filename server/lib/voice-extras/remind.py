#!/usr/bin/env python3
"""voice-remind add WHEN "text" [--telegram] | list | cancel ID.
WHEN: +30m, +2h, 17:00, tomorrow 09:00, 2026-11-05 17:00 (in the configured AGENT_TZ time zone)."""
import sys, re, uuid
from datetime import datetime, timedelta
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *

def parse_when(s):
    s = s.strip().lower(); n = now()
    m = re.fullmatch(r"\+(\d+)\s*(m|min|h|hr|d)", s)
    if m:
        v = int(m.group(1)); return n + timedelta(**{"minutes": v} if m.group(2).startswith("m") else {"hours": v} if m.group(2).startswith("h") else {"days": v})
    m = re.fullmatch(r"(?:(tomorrow|today)\s+)?(\d{1,2})(?::(\d\d))?\s*(am|pm)?", s)
    if m:
        h = int(m.group(2)); mi = int(m.group(3) or 0)
        if m.group(4) == "pm" and h < 12: h += 12
        if m.group(4) == "am" and h == 12: h = 0
        t = n.replace(hour=h, minute=mi, second=0, microsecond=0)
        if m.group(1) == "tomorrow": t += timedelta(days=1)
        elif t <= n and m.group(1) != "today": t += timedelta(days=1)
        return t
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d)[ t](\d{1,2}):(\d\d)", s)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(hour=int(m.group(2)), minute=int(m.group(3)), tzinfo=TZ)
    raise SystemExit(f"Can't understand time '{s}'. Use +30m, 17:00, tomorrow 09:00 or YYYY-MM-DD HH:MM")

def add(when, text, channel="call", n=None):
    t = parse_when(when)
    with lock("reminders"):
        r = load("reminders.json", [])
        rid = uuid.uuid4().hex[:6]
        r.append({"id": rid, "at": t.isoformat(), "text": text[:300], "channel": channel})
        save("reminders.json", r)
    return rid, t

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        r = sorted(load("reminders.json", []), key=lambda x: x["at"])
        print("\n".join(f"{x['id']} {datetime.fromisoformat(x['at']).strftime('%a %b %d %H:%M')} [{x['channel']}] {x['text']}" for x in r) or "No reminders.")
    elif a[0] == "add" and len(a) >= 3:
        tel = "--telegram" in a; a = [x for x in a if x != "--telegram"]
        rid, t = add(a[1], " ".join(a[2:]), "telegram" if tel else "call")
        print(f"OK {rid}: reminder at {t.strftime('%A %H:%M')} {TZ_NAME} -> {'Telegram' if tel else 'phone call'}: {' '.join(a[2:])}")
    elif a[0] == "cancel" and len(a) == 2:
        with lock("reminders"):
            r = load("reminders.json", []); k = [x for x in r if x["id"] != a[1]]; save("reminders.json", k)
        print("cancelled" if len(k) < len(r) else "no such id")
    else:
        print(__doc__); sys.exit(2)
