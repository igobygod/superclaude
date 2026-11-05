#!/usr/bin/env python3
"""Stuck-job sweeper (runs as claude-helper every minute): a job marked running with no process for >10 min is marked failed."""
import json, sys, time
sys.path.insert(0, "/usr/local/lib/voice-dashboard")
from dashlib import *

GRACE = 10 * 60


def set_failed(job: Path, why: str):
    lines = job.read_text(errors="replace").splitlines()
    if lines:
        lines[0] = "STATUS: failed"
    lines.append("UPDATE: Problem: " + why)
    job.write_text("\n".join(lines) + "\n")


def main():
    plist = procs()
    claude_up = any_claude_running(plist)
    n = 0
    for f in JOBS.glob("*.md"):
        try:
            if time.time() - f.stat().st_mtime < GRACE:
                continue
            j = parse_job(f)
            if j["status_raw"].lower() != "running":
                continue
            tid = f.stem[6:] if f.stem.startswith("voice-") else None
            rf = RUNNING / f"{tid}.json" if tid else None
            task = jload(rf) if rf and rf.exists() else None
            alive = bool(task_procs(task, plist)) if task else claude_up
            if tid and task is None and (QUEUE / f"{tid}.json").exists():
                continue  # waiting in the queue, not running
            if alive:
                continue
            why = "Marked failed by the sweeper: no process was running for more than 10 minutes."
            set_failed(f, why)
            if tid:
                if not (DONE / f"{tid}.json").exists():
                    jwrite(DONE / f"{tid}.json", {"id": tid, "ok": False, "spoken": "That task got stuck with no process, so it was marked failed.",
                           "details": "", "task": j["task"], "finished": time.time(), "seconds": 0, "callback": False})
                if rf:
                    rf.unlink(missing_ok=True)
            print("swept", f.stem, flush=True)
            n += 1
        except Exception as e:
            print("sweep error", f.name, type(e).__name__, e, flush=True)
    return n


if __name__ == "__main__":
    main()
