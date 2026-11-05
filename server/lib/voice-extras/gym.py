#!/usr/bin/env python3
"""voice-gym set EXERCISE WEIGHT REPS | protein GRAMS | rest [SECONDS] | today | undo | target GRAMS"""
import sys, json
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
LOG = STATE / "gym.jsonl"

def rows():
    try: return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    except FileNotFoundError: return []
def add(o):
    o["ts"] = now().isoformat()
    with lock("gym"), open(LOG, "a") as f: f.write(json.dumps(o) + "\n")
    try: os.chmod(LOG, 0o660)
    except OSError: pass
def today(): return [r for r in rows() if r["ts"][:10] == now().strftime("%F")]

a = sys.argv[1:]
if not a: print(__doc__); sys.exit(2)
c = a[0]
if c == "set" and len(a) >= 4:
    ex = " ".join(a[1:-2]).lower(); w, reps = float(a[-2]), int(a[-1])
    add({"t": "set", "ex": ex, "w": w, "reps": reps})
    n = sum(1 for r in today() if r["t"] == "set" and r["ex"] == ex)
    prev = [r for r in rows() if r["t"] == "set" and r["ex"] == ex and r["ts"][:10] != now().strftime("%F")]
    pr = " New personal best weight!" if prev and w > max(p["w"] for p in prev) else ""
    print(f"Logged set {n} of {ex}: {w:g} x {reps}.{pr}")
elif c == "protein" and len(a) == 2:
    add({"t": "protein", "g": float(a[1])})
    tot = sum(r["g"] for r in today() if r["t"] == "protein"); tgt = load("gym.json", {}).get("protein_target")
    print(f"Protein today: {tot:g} g" + (f" of {tgt:g} g target, {max(tgt - tot, 0):g} to go." if tgt else "."))
elif c == "target" and len(a) == 2:
    g = load("gym.json", {}); g["protein_target"] = float(a[1]); save("gym.json", g); print(f"Protein target set to {a[1]} g.")
elif c == "rest":
    import remind
    secs = int(a[1]) if len(a) > 1 else 90
    rid, t = remind.add(f"+{max(1, round(secs / 60))}m" if secs >= 60 else "+1m", "Rest over. Next set!", "telegram")
    # exact-second timer for sub-/odd-minute rests
    with lock("reminders"):
        r = load("reminders.json", [])
        for x in r:
            if x["id"] == rid: x["at"] = (now() + timedelta(seconds=secs)).isoformat()
        save("reminders.json", r)
    print(f"Rest timer: {secs} seconds. I'll message you on Telegram when it's over.")
elif c == "undo":
    with lock("gym"):
        L = rows()
        if L: LOG.write_text("".join(json.dumps(r) + "\n" for r in L[:-1])); print("Removed last entry:", L[-1])
        else: print("Nothing to undo.")
elif c == "today":
    t = today(); sets = {}
    for r in t:
        if r["t"] == "set": sets.setdefault(r["ex"], []).append(f"{r['w']:g}x{r['reps']}")
    p = sum(r["g"] for r in t if r["t"] == "protein")
    print("; ".join(f"{k}: {', '.join(v)}" for k, v in sets.items()) or "No sets yet.", f"| protein {p:g} g")
else: print(__doc__); sys.exit(2)
