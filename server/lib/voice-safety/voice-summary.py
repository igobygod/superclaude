#!/usr/bin/env python3
"""Daily activity summary to Telegram (AGENT_TZ day). Usage: voice-summary.py [--print]"""
import json,glob,os,sys,re,urllib.request,urllib.parse
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
tz=ZoneInfo(os.environ.get("AGENT_TZ","UTC")); now=datetime.now(tz)
start=datetime.combine(now.date(),time(0),tz).timestamp(); end=start+86400
def jl(p):
    out=[]
    try:
        for l in open(p):
            try: out.append(json.loads(l))
            except Exception: pass
    except Exception: pass
    return out
ev=[e for e in jl("/var/lib/voicecaller/calls.jsonl") if start<=e.get("time",0)<end]
calls={}
for e in ev:
    c=calls.setdefault(e["call_id"],{"reason":"","ans":False,"miss":False,"err":None})
    k=e.get("event")
    if k=="dialing": c["reason"]=e.get("reason","")
    elif k=="answered": c["ans"]=True
    elif k=="not_answered": c["miss"]=True; c["err"]=e.get("error")
placed=len(calls); ans=sum(1 for c in calls.values() if c["ans"]); miss=sum(1 for c in calls.values() if c["miss"] and not c["ans"])
tasks=[]
for p in glob.glob("/var/lib/voice-tasks/done/*.json"):
    try: d=json.load(open(p))
    except Exception: continue
    if start<=d.get("finished",0)<end: tasks.append(d)
tasks.sort(key=lambda d:d["finished"])
sendre=re.compile(r"^\s*(send|email|e-mail|text|message|reply|forward)\b",re.I)
sent=[t for t in tasks if t.get("ok") and sendre.search(t.get("task",""))]
failed=[t for t in tasks if not t.get("ok")]
def one(s,n=110):
    s=re.sub(r"\s+"," ",s or "").strip(); return s if len(s)<=n else s[:n-1]+"…"
L=[f"📋 Voice agent summary, {now:%a %b %-d}"]
L.append(f"📞 Calls: {placed} placed, {ans} answered, {miss} missed")
for cid,c in calls.items():
    if c["miss"] and not c["ans"]: L.append(f"  • missed: {one(c['reason'],70)}")
L.append(f"🛠 Tasks run: {len(tasks)}")
for t in tasks[-8:]: L.append(f"  • {'✓' if t.get('ok') else '✗'} {one(t.get('spoken') or t.get('task'))}")
if len(tasks)>8: L.append(f"  (+{len(tasks)-8} earlier)")
L.append(f"✉️ Messages sent: {len(sent)}")
for t in sent: L.append(f"  • {one(t['task'],90)}")
probs=[]
for t in failed: probs.append(f"task failed: {one(t.get('task'),80)}")
for c in calls.values():
    if c["miss"] and not c["ans"] and c["err"] and "404" not in str(c["err"]) : probs.append(f"call error: {one(str(c['err']),60)}")
try: probs+= [f"health open: {x}" for x in json.load(open("/var/lib/voice-safety/health.json"))["alerted"]]
except Exception: pass
L.append("⚠️ Problems: "+("none" if not probs else ""))
for p in probs: L.append("  • "+p)
txt="\n".join(L)
if "--print" in sys.argv: print(txt); sys.exit(0)
env={}
for l in open("/etc/voice-caller/secrets.env"):
    if "=" in l: k,v=l.rstrip("\n").split("=",1); env[k]=v.strip("'\"")
data=urllib.parse.urlencode({"chat_id":env["TELEGRAM_CHAT_ID"],"text":txt}).encode()
r=urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",data,timeout=20)
print("sent",r.status)
