#!/usr/bin/env python3
"""When the owner answers a jobsearch:* question, finish that application via the existing job-search system's process."""
import sys, json, subprocess
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
if not JOB_SEARCH_DIR: sys.exit(0)
done = load("jobanswers-done.json", {})
p = subprocess.run(["voice-questions", "list", "--all", "--json"], capture_output=True, text=True)
try: qs = json.loads(p.stdout)
except Exception: sys.exit(0)
for q in qs:
    if not str(q.get("ref", "")).startswith("jobsearch:") or q.get("status") != "answered" or q["id"] in done: continue
    done[q["id"]] = now().isoformat(); save("jobanswers-done.json", done)
    task = (f"The owner answered a question from the job-search system. Question: {q['text']}\nOwner's answer: {q.get('answer_text')}\n"
            "Follow this folder's PROGRESS.md and SYNC-RULES (Drive copy if needed) exactly: check tracker.csv for a duplicate first; if the answer is yes/OK, finish THAT application through the usual process "
            "(same tracker/lock rules, same submission method as the scheduled runs). If the answer is no, mark it skipped per the rules. Facts about the owner come only from applicant-profile.md; never invent. "
            "Never create accounts or type passwords; if one is needed stop and say so. End with one SPOKEN line: what was done.")
    if DRY: print("[DRY would run on Mac]", task[:200]); continue
    r = mac(task, JOB_SEARCH_DIR, 1200)
    msg = (r.get("spoken") or "done") + ("" if r.get("ok") else " (the Mac task had a problem)")
    tg("Job search: " + msg)
    subprocess.run(["voice-questions", "close", "--text", msg[:200], q["id"]], capture_output=True)
