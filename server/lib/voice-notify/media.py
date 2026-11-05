"""Shared media inbox: /var/lib/voice-media/inbox/<date>/<id>-<name> + index.jsonl (time, source, type, path, caption)."""
import json, mimetypes, os, re, subprocess, time

ROOT = os.environ.get("VM_DIR", "/var/lib/voice-media/inbox")
INDEX = os.path.join(ROOT, "index.jsonl")
KEEP_DAYS = 7
EXT = {"image": (".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp"), "audio": (".mp3", ".m4a", ".caf", ".wav", ".aac", ".amr", ".opus", ".ogg"),
       "video": (".mp4", ".mov", ".m4v", ".webm")}


def kind_of(mime: str, name: str) -> str:
    mime = mime or mimetypes.guess_type(name)[0] or ""
    ext = os.path.splitext(name)[1].lower()
    for k, exts in EXT.items():
        if mime.startswith(k + "/") or ext in exts:
            return k
    return "file"


def save(data: bytes, name: str, source: str, caption: str = "", mime: str = "", extra: dict | None = None) -> dict:
    os.umask(0o007)
    day = time.strftime("%Y%m%d")
    d = os.path.join(ROOT, day)
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[-60:] or "file"
    mid = f"{int(time.time() * 1000) % 10**10:010d}"
    path = os.path.join(d, f"{mid}-{safe}")
    with open(path, "wb") as f:
        f.write(data)
    e = {"id": mid, "time": time.time(), "source": source, "type": kind_of(mime, name), "path": path, "caption": caption[:300], "name": name[:80], "size": len(data)}
    e.update(extra or {})
    with open(INDEX, "a") as f:
        f.write(json.dumps(e) + "\n")
    return e


def entries():
    out = []
    try:
        for l in open(INDEX):
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def latest(typ=None, since=None, limit=10):
    now = time.time()
    rows = [e for e in entries() if os.path.exists(e["path"]) and (not typ or e["type"] == typ) and (since is None or now - e["time"] <= since)]
    return rows[-limit:][::-1]


def prune():
    """Delete files older than 7 days unless the journal mentions them or they are marked keep. Returns count removed."""
    ref = ""
    try:
        ref = subprocess.run(["grep", "-rhoE", ROOT + r"/[0-9]+/[^ \"')]+", "/var/lib/voice-memory"], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        pass
    keep, removed, now = set(ref.split()), 0, time.time()
    rows = entries()
    live = []
    for e in rows:
        if now - e["time"] > KEEP_DAYS * 86400 and not e.get("keep") and e["path"] not in keep:
            try:
                os.remove(e["path"]); removed += 1
            except OSError:
                pass
        else:
            live.append(e)
    tmp = INDEX + ".tmp"
    with open(tmp, "w") as f:
        for e in live:
            f.write(json.dumps(e) + "\n")
    os.replace(tmp, INDEX)
    for dd in os.listdir(ROOT):
        p = os.path.join(ROOT, dd)
        if os.path.isdir(p) and not os.listdir(p):
            os.rmdir(p)
    return removed
