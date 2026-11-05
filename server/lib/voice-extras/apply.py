#!/usr/bin/env python3
"""voice-apply URL [notes...]: owner asked to apply to this posting. Uses the existing job-search system's process."""
import sys
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
if len(sys.argv) < 2: print(__doc__); sys.exit(2)
if not JOB_SEARCH_DIR: print("job search not configured (set JOB_SEARCH_DIR)"); sys.exit(0)
link, note = sys.argv[1], " ".join(sys.argv[2:])
task = (f"The owner asked to apply to this posting: {link} {note}\nFollow PROGRESS.md and SYNC-RULES in this folder (Drive copy if needed) exactly. FIRST check tracker.csv for a duplicate (same link, or same company + job title); if found, stop and report its status. "
        "Otherwise run the usual process for one job: prepare materials and submit by the same method the scheduled runs use, with the same tracker/lock rules. Facts about the owner come only from applicant-profile.md; never invent. "
        "Never create accounts or type passwords: if needed, stop and say so. End with one SPOKEN line: applied / duplicate / blocked (and why).")
if DRY: print("[DRY]", task[:300]); sys.exit(0)
r = mac(task, JOB_SEARCH_DIR, 1500)
print(r.get("spoken")); tg("Apply result: " + (r.get("spoken") or "") + "\n" + (r.get("details") or "")[:600])
