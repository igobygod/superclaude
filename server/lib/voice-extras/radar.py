#!/usr/bin/env python3
"""Patch radar (Steam news, free, no key) and App Store review watch (iTunes RSS, free). Baselines on first run, then Telegram on new items."""
import sys, json, re
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
mode = sys.argv[1] if len(sys.argv) > 1 else "patch"
seen = load(f"{mode}-seen.json", {})
first = not seen; out = []
if mode == "patch":
    for g in conf()["games"]:
        try:
            j = json.loads(fetch(f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={g['steam']}&count=8&maxlength=300"))
        except Exception as e:
            print(g["name"], "fetch failed", type(e).__name__); continue
        for n in j.get("appnews", {}).get("newsitems", []):
            if n["gid"] in seen: continue
            seen[n["gid"]] = 1
            if re.search(r"patch|update|hotfix|season|notes|balance|fix", n["title"], re.I):
                out.append(f"{g['name']}: {n['title']}\n{n['url']}")
else:
    for a in conf()["appstore_apps"]:
        try:
            j = json.loads(fetch(f"https://itunes.apple.com/{a.get('country','us')}/rss/customerreviews/id={a['id']}/sortby=mostrecent/json"))
        except Exception as e:
            print(a["name"], "fetch failed", type(e).__name__); continue
        for e in j.get("feed", {}).get("entry", [])[:10]:
            rid = e.get("id", {}).get("label")
            if not rid or rid in seen: continue
            seen[rid] = 1
            stars = int(e.get("im:rating", {}).get("label", 5))
            out.append(f"{a['name']}: {stars} stars - {e.get('title',{}).get('label','')}: {e.get('content',{}).get('label','')[:200]}")
save(f"{mode}-seen.json", seen)
print("baseline saved" if first else "\n".join(out) or "nothing new")
if out and not first:
    tg(("Game updates:\n" if mode == "patch" else "New App Store reviews:\n") + "\n\n".join(out[:6]))
