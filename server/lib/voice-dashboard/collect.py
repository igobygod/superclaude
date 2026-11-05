#!/usr/bin/env python3
"""Root helper (every 30 s): summarise the last calls from /var/lib/voicecaller/calls.jsonl (not readable by claude-helper)
into /var/lib/voice-usage/calls.json. Only call id, time, status and a short reason/note are copied."""
import json, os
from pathlib import Path
src, dst = Path("/var/lib/voicecaller/calls.jsonl"), Path("/var/lib/voice-usage/calls.json")
calls = {}
for l in src.read_text(errors="replace").splitlines()[-600:]:
    try:
        e = json.loads(l)
    except Exception:
        continue
    c = calls.setdefault(e.get("call_id", "?"), {"id": e.get("call_id", "?"), "time": e.get("time"), "events": [], "reason": "", "note": ""})
    c["events"].append(e.get("event"))
    if e.get("reason"):
        c["reason"] = str(e["reason"])[:160]
    if e.get("note"):
        c["note"] = str(e["note"])[:160]
    if e.get("event") in ("answered", "ended", "not_answered", "dialing"):
        c["last"] = e["event"]
out = []
for c in sorted(calls.values(), key=lambda c: c["time"] or 0, reverse=True)[:12]:
    ev = c["events"]
    status = "answered" if "answered" in ev else ("missed" if "not_answered" in ev else ("dialing" if "dialing" in ev else (ev[-1] if ev else "?")))
    if "answered" in ev and "ended" not in ev:
        status = "live"
    out.append({"id": c["id"], "time": c["time"], "status": status, "reason": c["reason"], "note": c["note"]})
tmp = dst.with_name("calls.json.tmp")
tmp.write_text(json.dumps(out))
os.chmod(tmp, 0o664)
tmp.replace(dst)
