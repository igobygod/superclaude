"""Shared helpers for the voice job dashboard and the stuck-job sweeper (read-mostly)."""
import json, os, re, time
from pathlib import Path

BASE = Path("/var/lib/voice-tasks")
QUEUE, RUNNING, DONE, STOP = BASE / "queue", BASE / "running", BASE / "done", BASE / "STOP"
JOBS = Path("/home/claude-helper/assistant/jobs")
UD = Path("/var/lib/voice-usage")
CANCELLED = UD / "cancelled.json"
import pwd
HELPER_UID = pwd.getpwnam(os.environ.get("HELPER_USER", "claude-helper")).pw_uid
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def jwrite(p: Path, data, mode=0o664):
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, mode)
    tmp.replace(p)


def procs():
    """claude-helper processes: (pid, pgid, args-string)."""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if d.stat().st_uid != HELPER_UID:
                continue
            args = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf8", "replace")
            pgid = os.getpgid(int(d.name))
            out.append((int(d.name), pgid, args))
        except Exception:
            continue
    return out


def task_procs(task: dict, plist=None):
    """Leader processes (pid == pgid, started by task_runner) whose command line holds this task's text."""
    needle = (task.get("text") if task.get("kind") == "imessage" else task.get("task", ""))[:80]
    if len(needle) < 8:
        return []
    return [(pid, pg) for pid, pg, a in (plist if plist is not None else procs()) if pid == pg and needle in a]


def any_claude_running(plist=None) -> bool:
    return any(re.search(r"(^|/)(claude|mac-run|imessage-send)\b", a.split(" ")[0]) or "/claude " in a[:120]
               for _, _, a in (plist if plist is not None else procs()))


def parse_job(p: Path) -> dict:
    lines = p.read_text(errors="replace").splitlines()
    d = {"name": p.stem, "status_raw": "?", "task": "", "worker": "", "updates": [], "result": ""}
    for i, l in enumerate(lines):
        if i == 0 and l.startswith("STATUS:"):
            d["status_raw"] = l[7:].strip()
        elif l.startswith("TASK:"):
            d["task"] = l[5:].strip()
        elif l.startswith("WORKER:"):
            d["worker"] = l[7:].strip()
        elif l.startswith("UPDATE: "):
            d["updates"].append(l[8:].strip())
        elif l.startswith("RESULT:"):
            d["result"] = l[7:].strip()
    st = p.stat()
    d["mtime"] = st.st_mtime
    return d


def classify(raw: str, done: dict | None, cancelled: bool, queued: bool) -> str:
    if queued:
        return "queued"
    if done is not None:
        sp = (done.get("spoken") or "")
        if cancelled or sp.startswith(("Cancelled", "Stopped,")) or "Stopped by the dashboard" in sp:
            return "cancelled"
        if "took longer than" in sp or "timed out" in sp:
            return "timed out"
        return "succeeded" if done.get("ok") else "failed"
    r = raw.lower()
    if r == "running":
        return "running"
    if r == "done":
        return "succeeded"
    if r in ("failed", "interrupted", "error"):
        return "failed"
    if r in ("cancelled", "canceled", "stopped"):
        return "cancelled"
    if "timeout" in r or "timed" in r:
        return "timed out"
    return r or "?"
