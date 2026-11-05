#!/usr/bin/env python3
"""Xcode build watchdog via the Mac (xcodebuild). Calls only on failure. Usage: buildwatch.py [project_key] [--command CMD]"""
import sys
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
c = conf(); bw = c["build_watch"]
key = next((x for x in sys.argv[1:] if not x.startswith("-")), bw["project"])
folder = c["mac_projects"].get(key, key)
cmd = sys.argv[sys.argv.index("--command") + 1] if "--command" in sys.argv else bw["command"]
r = mac(f"In this folder run `{cmd}`. Don't change any files. Report the outcome. The last line of your answer must be exactly RESULT: PASS (build succeeded), RESULT: FAIL (the build ran and failed) or RESULT: BLOCKED (you could not run it, e.g. permission denied). On FAIL list at most 5 errors as file:line message.", folder, 1500)
txt = (r.get("details") or "") + "\n" + (r.get("spoken") or "")
fail = "RESULT: FAIL" in txt and "RESULT: BLOCKED" not in txt
blocked = not fail and "RESULT: PASS" not in txt
print("FAIL" if fail else "BLOCKED" if blocked else "PASS"); print(txt[-800:])
if blocked:
    tg(f"Build check for {key} could not run (not a build failure):\n{txt[-500:]}")
if fail:
    tg(f"Build FAILED for {key} ({cmd}):\n{txt[-700:]}")
    print(call_owner(f"The {key} build failed.", txt[-900:], proactive=True, telegram_text=f"Build FAILED for {key} (no call: quiet hours or daily limit)"))
