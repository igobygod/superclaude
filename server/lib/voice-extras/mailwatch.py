#!/usr/bin/env python3
"""Promises, unreplied recruiters, deadlines, deliveries from Gmail. Drafts only; never sends."""
import sys, json, hashlib
sys.path.insert(0, "/usr/local/lib/voice-extras")
from common import *
N = int(conf()["followup_days"])
PROMPT = f"""Scan the owner's Gmail (read-only, except Gmail DRAFTS). Never send anything and never reply. Today is {now().strftime('%F')} ({TZ_NAME}).
Find, from the last 21 days:
A) promises: sent emails where the owner committed to do or send something ("I will send", "I'll get back", "I will call"). Only real commitments.
B) followups: job-related threads (recruiters, hiring managers, applications with a named person) where the owner's message is the last one and {N}+ days passed with no reply. For each, create a Gmail DRAFT reply on that thread (short, polite, formal, signed "Best regards, {OWNER_NAME}") using the create_draft tool. Do not send.
C) deadlines: emails mentioning a date the owner must act by (application deadlines, document requests, assessments, interviews to confirm, bills/renewals). Date as YYYY-MM-DD.
D) deliveries: shipping or tracking emails with an expected delivery date.
Use real Gmail thread/message ids as "id". Output ONLY JSON:
{{"promises":[{{"id":"","to":"","what":"","due":"YYYY-MM-DD or null"}}],"followups":[{{"id":"","who":"","subject":"","days":0,"draft":true}}],"deadlines":[{{"id":"","title":"","date":"YYYY-MM-DD"}}],"deliveries":[{{"id":"","item":"","eta":"YYYY-MM-DD"}}]}}"""
r = ask_claude(PROMPT, "sonnet", 1500)
d = extract_json((r.get("details") or "") + "\n" + (r.get("spoken") or ""))
if not isinstance(d, dict): print("mailwatch: no usable JSON from Claude"); sys.exit(1)
st = load("mailwatch.json", {"promises": {}, "followups": {}, "deadlines": {}, "deliveries": {}})
today = now().date()
def merge(kind, items, keyf):
    for it in items or []:
        k = it.get("id") or hashlib.md5(json.dumps(it, sort_keys=True).encode()).hexdigest()[:10]
        old = st[kind].get(k, {}); it.update({x: old[x] for x in old if x.startswith("notified")}); st[kind][k] = it
for k in ("promises", "followups", "deadlines", "deliveries"): st.setdefault(k, {})
merge("promises", d.get("promises"), None); merge("followups", d.get("followups"), None)
merge("deadlines", d.get("deadlines"), None); merge("deliveries", d.get("deliveries"), None)
def days_to(s):
    try: return (datetime.strptime(s, "%Y-%m-%d").date() - today).days
    except Exception: return None
for k, it in st["deadlines"].items():
    n = days_to(it.get("date"))
    if n is None: continue
    if 2 <= n <= 7 and not it.get("notified_week"):
        tg(f"Deadline in {n} days ({it['date']}): {it['title']}"); it["notified_week"] = True
    if n == 1 and not it.get("notified_day"):
        call_owner(f"Reminder: tomorrow is a deadline. {it['title']}", f"Deadline {it['date']}. Offer to help prepare or draft something, but don't send anything without a yes.",
                   proactive=True, telegram_text=f"Deadline TOMORROW ({it['date']}): {it['title']}")
        it["notified_day"] = True
for k, it in st["followups"].items():
    if not it.get("notified"):
        tg(f"No reply from {it.get('who','?')} for {it.get('days','?')}+ days ({it.get('subject','')}).\n"
           + ("A follow-up draft is waiting in Gmail Drafts. " if it.get("draft") else "") + "Say 'send the follow-up to " + str(it.get("who", "them")).split()[0] + "' and I'll send it after you confirm.")
        it["notified"] = True
for k, it in st["promises"].items():
    n = days_to(it.get("due") or "")
    if n is not None and n <= 1 and not it.get("notified"):
        tg(f"You promised {it.get('to','someone')}: {it.get('what','')} (due {it['due']})"); it["notified"] = True
for k, it in st["deliveries"].items():
    if days_to(it.get("eta")) == 0 and not it.get("notified"):
        tg(f"Package due today: {it.get('item','')}"); it["notified"] = True
save("mailwatch.json", st)
print({k: len(v) for k, v in st.items()})
