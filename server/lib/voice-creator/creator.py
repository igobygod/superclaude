#!/usr/bin/env python3
"""voice-creator: upload monitor + weekly channel report for the owner's channels (public YouTube RSS, no keys).
  creator.py monitor [--dry]   every 10 min: record views at ~1 h / 24 h / 7 d after upload, compare with the channel's usual, notify
  creator.py weekly [--dry]    Sunday report: what worked, what next, best times
  creator.py status            what is being tracked
Suggestions only: nothing is ever changed on YouTube. Notifies via voice-notify (info)."""
import sys, os, re, json, time, subprocess, statistics, urllib.request, html
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
# CREATOR_CHANNELS="name=UCxxxxxxxxxxxxxxxxxxxxxx,name2=UCyyyy..." (name = your label, value = YouTube channel id). Empty = nothing to monitor.
CH = dict(kv.split("=", 1) for kv in os.environ.get("CREATOR_CHANNELS", "").split(",") if "=" in kv)
STATE = "/var/lib/voice-creator/monitor.json"
TZ = ZoneInfo(os.environ.get("AGENT_TZ", "UTC"))
CP = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}
dry = "--dry" in sys.argv

def feed(cid):
    x = urllib.request.urlopen(urllib.request.Request(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode()
    out = []
    for e in x.split("<entry>")[1:]:
        g = lambda p: (re.search(p, e) or [None, None])[1]
        out.append({"id": g(r"<yt:videoId>(.*?)<"), "title": html.unescape(g(r"<title>(.*?)<") or ""),
                    "pub": datetime.fromisoformat(g(r"<published>(.*?)<")).timestamp(), "views": int(g(r'views="(\d+)"') or 0),
                    "likes": int(g(r'ratingCount="(\d+)"') or 0)})
    return out

def load():
    try: return json.load(open(STATE))
    except Exception: return {"videos": {}, "seeded": False}
def save(s):
    t = STATE + ".tmp"; json.dump(s, open(t, "w"), indent=1); os.chmod(t, 0o664); os.replace(t, STATE)

def notify(text):
    print("NOTIFY:", text)
    if not dry: subprocess.run(["/usr/local/bin/voice-notify", "--level", "info", "--text", text, "--no-wait"], timeout=60)

def fmt(n): return f"{n:,}"

def baseline(s, ch, cp, exclude):
    """usual views at this checkpoint = median of this channel's own earlier snapshots (needs 3+)"""
    v = [x["snaps"][cp] for k, x in s["videos"].items() if x["ch"] == ch and k != exclude and cp in x["snaps"]]
    return statistics.median(v) if len(v) >= 3 else None

def fallback_total(s, ch, now):
    v = [x["last_views"] for x in s["videos"].values() if x["ch"] == ch and now - x["pub"] > 7 * 86400]
    return statistics.median(v) if len(v) >= 3 else None

def monitor():
    s = load(); now = time.time(); first = not s["seeded"]
    for ch, cid in CH.items():
        try: items = feed(cid)
        except Exception as e: print("feed error", ch, e); continue
        for it in items:
            v = s["videos"].setdefault(it["id"], {"ch": ch, "title": it["title"], "pub": it["pub"], "snaps": {}, "alerts": [], "tracked": (not first) and now - it["pub"] < 2 * 3600 or False})
            v["last_views"] = it["views"]; v["title"] = it["title"]
            if first: continue
            if not v["tracked"]:
                continue
            age = now - it["pub"]
            for cp, sec in CP.items():
                if cp in v["snaps"] or age < sec: continue
                if age > sec * 1.5 + 3600: v["snaps"][cp] = None; continue  # missed the window
                v["snaps"][cp] = it["views"]
                base = baseline(s, ch, cp, it["id"]); fb = fallback_total(s, ch, now)
                short = it["title"][:60]
                msg = None
                if base:
                    r = it["views"] / base
                    if r >= 2: msg = f"🔥 \"{short}\" ({ch}) has {fmt(it['views'])} views at {cp}, {r:.1f}× your usual {fmt(int(base))}. Want me to draft a pinned comment?"
                    elif r <= 0.5 and cp != "1h": msg = f"\"{short}\" ({ch}) has only {fmt(it['views'])} views at {cp}, about {int(r*100)}% of your usual {fmt(int(base))}. Want 3 new thumbnail or title options? (I can also check its click-through rate in vidIQ.)"
                elif fb and it["views"] > fb:
                    msg = f"🔥 \"{short}\" ({ch}) already has {fmt(it['views'])} views at {cp}, more than your typical video total ({fmt(int(fb))}). Pin a comment?"
                else:
                    print(f"{ch} {it['id']} {cp}: {it['views']} views (no history yet, collecting)")
                if msg: notify(msg); v["alerts"].append([cp, msg])
    s["seeded"] = True; s["last_run"] = int(now); save(s)

def weekly():
    s = load(); now = time.time(); lines = ["📈 Weekly channel report"]; best_h = {}
    for ch, cid in CH.items():
        try: items = feed(cid)
        except Exception as e: lines.append(f"{ch}: could not read feed ({e})"); continue
        week = [i for i in items if now - i["pub"] < 7 * 86400]
        older = [i for i in items if now - i["pub"] >= 7 * 86400]
        usual = statistics.median([i["views"] for i in older]) if len(older) >= 3 else None
        lines.append(f"\n{ch}: {len(week)} upload(s) this week" + (f", usual video ~{fmt(int(usual))} views" if usual else ""))
        for i in sorted(week, key=lambda i: -i["views"])[:3]:
            t = f" ({i['views']/usual:.1f}× usual)" if usual else ""
            lines.append(f"• {i['title'][:55]} - {fmt(i['views'])} views{t}")
        if not week: lines.append("• nothing uploaded - even one short helps the algorithm")
        top = max(items, key=lambda i: i["views"]) if items else None
        if top: lines.append(f"Make next: more like \"{top['title'][:50]}\" ({fmt(top['views'])} views, best of the last {len(items)})")
        for i in items:
            if now - i["pub"] > 3 * 86400:
                h = datetime.fromtimestamp(i["pub"], TZ); best_h.setdefault((ch, h.strftime("%a"), h.hour), []).append(i["views"])
    sl = sorted(((statistics.mean(v), k, len(v)) for k, v in best_h.items()), reverse=True)[:3]
    if sl: lines.append("\nBest posting slots (local time, from recent videos): " + "; ".join(f"{k[0]} {k[1]} {k[2]}:00 (avg {fmt(int(m))}, {n} video{'s' if n>1 else ''})" for m, k, n in sl) + ". Small sample, treat as a hint.")
    notify("\n".join(lines))

def status():
    s = load()
    print("last run", time.strftime("%F %T", time.localtime(s.get("last_run", 0))), "videos", len(s["videos"]))
    for k, v in s["videos"].items():
        if v.get("tracked"): print(k, v["ch"], v["title"][:40], v["snaps"], v["alerts"])

{"monitor": monitor, "weekly": weekly, "status": status}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
