#!/usr/bin/env python3
"""Runs every minute (voice-extras-tick.timer, as claude-helper): due reminders, then scheduled jobs."""
import sys, subprocess
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
D = "/usr/local/lib/voice-extras"
n = now()
if (TASKS / "STOP").exists(): sys.exit(0)
with lock("reminders"):
    r = load("reminders.json", []); keep = []
    for x in r:
        if datetime.fromisoformat(x["at"]) <= n:
            if x["channel"] == "telegram": tg("⏰ " + x["text"])
            else: call_owner("Reminder you asked for: " + x["text"], f"The owner asked for this reminder. Say it, then ask if they want it snoozed or anything else.", proactive=False, telegram_text="⏰ " + x["text"])
        else: keep.append(x)
    if len(keep) != len(r): save("reminders.json", keep)
c = conf(); sched = load("schedule.json", {}); today = n.strftime("%F")
def due(job, hhmm, days=None):
    h, m = (int(v) for v in hhmm.split(":"))
    return sched.get(job) != today and (n.hour, n.minute) >= (h, m) and (n.hour * 60 + n.minute) - (h * 60 + m) < 180 and (days is None or n.weekday() in days)
def interval(job, hours): return time.time() - sched.get(job, 0) >= hours * 3600
jobs = []
if due("scout", c["scout_time"]): jobs.append(("scout", "scout.py", [], today))
if due("briefing", c["briefing_time"], c["briefing_days"]): jobs.append(("briefing", "briefing.py", [], today))
if due("mailwatch", c["mailwatch_time"]): jobs.append(("mailwatch", "mailwatch.py", [], today))
if 7 <= n.hour < 23 and interval("jobanswers", 0.08): jobs.append(("jobanswers", "jobanswers.py", [], time.time()))
if c["build_watch"]["enabled"] and due("buildwatch", c["build_watch"]["time"]): jobs.append(("buildwatch", "buildwatch.py", [], today))
if 7 <= n.hour < 23 and interval("patch", c["patch_radar_hours"]): jobs.append(("patch", "radar.py", ["patch"], time.time()))
if c["appstore_apps"] and 7 <= n.hour < 23 and interval("reviews", c["review_watch_hours"]): jobs.append(("reviews", "radar.py", ["reviews"], time.time()))
for name, script, args, mark in jobs:
    sched[name] = mark
    log = open(STATE / f"{name}.log", "a")
    subprocess.Popen(["/usr/bin/python3", f"{D}/{script}", *args], stdout=log, stderr=log, start_new_session=True)
if jobs: save("schedule.json", sched)
