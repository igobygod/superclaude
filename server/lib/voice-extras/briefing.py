#!/usr/bin/env python3
"""Morning briefing: Claude gathers it, Telegram gets the full text, phone call gets the short spoken part."""
import sys, json, glob
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
today = now().strftime("%F")
scout = load(f"scout-{today}.json", {})
mw = load("mailwatch.json", {})
soon = [d for d in mw.get("deadlines", {}).values() if 0 <= (datetime.fromisoformat(d["date"]).date() - now().date()).days <= 7] if mw else []
PROMPT = f"""Prepare the owner's morning briefing for {now().strftime('%A %B %d')} ({TZ_NAME}). Read-only: send nothing, change nothing, do not mark mail read.
- Meetings today: the owner's calendar feed URL is the single line in /var/lib/voice-extras/ical.url. Download it with curl (never print the URL), and list today's ({TZ_NAME} date) events with start times, expanding recurring ones (RRULE) and skipping cancelled/declined/all-day. If the file or download fails, say you couldn't check the calendar.
- Important emails: search Gmail for unread mail from the last 18 hours; mention only what matters (recruiters, interviews, deadlines, replies to applications). Skip newsletters.
- Finished overnight work: files in ~/assistant/jobs/ with STATUS: done modified since yesterday 6pm, skipping files named voice-* (those were already reported on calls); one line each.
- Job search status from the owner's existing job-search system (already summarised, use as given: new finds, applications sent, items waiting on the owner): {json.dumps(scout)}
- Upcoming deadlines (given): {json.dumps(soon)}
Output ONLY JSON: {{"spoken":"under 600 characters, plain friendly sentences meant to be read aloud, most important first","full":"the whole briefing as short bullet lines for Telegram"}}"""
r = ask_claude(PROMPT, "sonnet", 900)
d = extract_json((r.get("details") or "") + "\n" + (r.get("spoken") or "")) or {}
spoken = d.get("spoken") or "I couldn't put the briefing together this morning. Check Telegram or ask me for your day."
full = d.get("full") or spoken
tg("Good morning! Briefing:\n" + full)
print(call_owner("Good morning. Here is your morning briefing.", spoken, proactive=True, telegram_text=None))
