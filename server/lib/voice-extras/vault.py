#!/usr/bin/env python3
"""voice-vault add "idea" [--tag game] | list [N] | search WORD | random"""
import sys, json, random
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
F = STATE / "clip-ideas.jsonl"
def rows():
    try: return [json.loads(l) for l in F.read_text().splitlines() if l.strip()]
    except FileNotFoundError: return []
a = sys.argv[1:]
if a[:1] == ["add"] and len(a) >= 2:
    tags = []
    while "--tag" in a: i = a.index("--tag"); tags.append(a[i + 1].lower()); del a[i:i + 2]
    with lock("vault"), open(F, "a") as f: f.write(json.dumps({"ts": now().isoformat(), "idea": " ".join(a[1:]), "tags": tags}) + "\n")
    try: os.chmod(F, 0o660)
    except OSError: pass
    print(f"Saved clip idea #{len(rows())}.")
elif a[:1] == ["list"] or not a:
    n = int(a[1]) if len(a) > 1 else 10
    print("\n".join(f"#{i+1} {r['idea']}" + (f" [{','.join(r['tags'])}]" if r["tags"] else "") for i, r in list(enumerate(rows()))[-n:]) or "Vault is empty.")
elif a[0] == "search" and len(a) > 1:
    q = " ".join(a[1:]).lower()
    print("\n".join(f"#{i+1} {r['idea']}" for i, r in enumerate(rows()) if q in r["idea"].lower() or q in r["tags"]) or "Nothing found.")
elif a[0] == "random":
    r = rows(); print(random.choice(r)["idea"] if r else "Vault is empty.")
else: print(__doc__); sys.exit(2)
