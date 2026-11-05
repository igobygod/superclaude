#!/usr/bin/env python3
"""Job-search DIGEST (read-only). The owner's existing job-search system does the searching/applying; this only reads
the JOB_SEARCH_DIR folder on the Mac, summarises it, and asks the owner the questions the system is waiting on."""
import sys, json, subprocess
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
if not JOB_SEARCH_DIR: print("job search not configured (set JOB_SEARCH_DIR)"); sys.exit(0)
today = now().strftime("%F")
PROMPT = """STRICT READ-ONLY. Do not create, edit or delete any file, and do not create lock files. Do not search or apply for jobs.
Read: PROGRESS.md (last ~40 lines), tracker.csv, and the newest report-*.md files (today's and yesterday's) in this folder. Facts about the owner come only from applicant-profile.md.
Summarise for the owner: (1) new finds since yesterday, (2) applications sent in the last 2 days, (3) items WAITING ON THE OWNER (an answer to a question, an account to make, a draft to send, a blocked site). Use only what the files say. For each waiting item give the application it blocks (company + job title, or "general").
Keep the whole JSON under 1800 characters: max 4 new_finds (note under 60 chars), applied as company names only (max 10), max 6 waiting items (text under 120 chars). Output ONLY JSON, nothing after it:
{"summary":"under 400 chars, plain spoken sentences","new_finds":[{"company":"","title":"","note":""}],"applied":["Company"],"waiting":[{"key":"short-stable-id","app":"Company - Title","text":"the one question or step for the owner","needs":"answer|account|other"}]}"""
r = mac(PROMPT, JOB_SEARCH_DIR, 600)
d = extract_json((r.get("details") or "") + "\n" + (r.get("spoken") or ""))
if not isinstance(d, dict):
    save(f"scout-{today}.json", {"date": today, "summary": "", "error": "could not read the job-search files", "waiting": []}); print("no JSON"); sys.exit(1)
d["date"] = today; d["waiting"] = (d.get("waiting") or [])[:6]
save(f"scout-{today}.json", d)
asked = load("scout-asked.json", {})
for w in d["waiting"]:
    k = str(w.get("key") or w.get("text", ""))[:60]
    if k in asked: continue
    text = w["text"][:300] + (f" (for {w['app']})" if w.get("app") else "")
    if DRY: print("[DRY ask owner]", text); continue
    if w.get("needs") == "account":
        # account creation and passwords stay with the owner: just tell them
        tg("Job search needs you: " + text + " (I can't make accounts or enter passwords.)"); asked[k] = today; continue
    p = subprocess.run(["voice-questions", "add", "--text", text, "--kind", "check", "--ref", "jobsearch:" + k], capture_output=True, text=True)
    qid = (p.stdout.strip().split() or [""])[-1]
    n = subprocess.run(["voice-notify", "--level", "info", "--text", text + " Reply here with your answer.", "--question-id", qid, "--no-wait"], capture_output=True, text=True) if qid else None
    if not n or n.returncode != 0: tg("Job search question: " + text + " (reply here; I'll pick it up)")
    asked[k] = today
save("scout-asked.json", asked)
print(json.dumps(d, indent=1))
if now().weekday() not in conf()["briefing_days"]:
    tg("Job search update: " + d.get("summary", ""))
