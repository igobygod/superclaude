#!/usr/bin/env python3
"""Stand-in for `claude -p` in tests: canned answers chosen by prompt wording."""
import json, re, sys
p = sys.stdin.read()
if "FAIL_LLM" in p:
    sys.exit(1)
if "You review one finished TEXT conversation" in p:
    tg = "Telegram (Claude helper)" in p
    print(json.dumps({"grade": "C", "summary": "Lost the thread on short replies.", "checks": {"short_reply_context": {"ok": False, "note": "Which?"}},
        "false_claims": [{"said": "Done. I turned on your morning briefing", "times": 1, "tool_evidence": "earlier said it can't"}],
        "lessons": [{"rule": "Treat a short reply like 'yes' or 'which?' as answering your own latest question in the thread.", "why": "Which? was not understood", "scope": "text"},
                    {"rule": "Keep every text reply under three short sentences.", "why": "long replies", "scope": "both"}],
        "proposals": [], "pipeline": [] if tg else [{"problem": "Gemini socket missing, fell back to Claude", "evidence": "13:45:30 brain failed"}]}))
elif "You review one phone call" in p:
    print(json.dumps({"grade": "C", "summary": "Acted on a garbled phrase.", "checks": {"no_action_on_mishearing": {"ok": False, "note": "stop_everything on 'Thank you email'"}},
        "false_claims": [{"said": "I have increased my speaking speed", "times": 7, "tool_evidence": "no speed tool call"}],
        "lessons": [{"rule": "If the owner's words are garbled or partial, ask them to repeat before calling any tool.", "why": "stop_everything ran on 'Thank you email'", "replaces": None},
                    {"rule": "Always read back the recipient before you send an email.", "why": "no read-back"}],
        "proposals": [{"what": "Make stop_everything need a clear 'stop everything' phrase in code", "why": "mishearing"}],
        "pipeline": [{"problem": "Audio input stopped being read twice", "evidence": "watchdog 14:36:27"}]}))
elif "Answer the owner's question" in p:
    print("Jordan Lee is the Design Lead at Acme Corp; you had an interview.\nSOURCES: 1")
elif "very short spoken yes/no check" in p:
    ids = re.findall(r"^(\w+): ", p.split("Items:")[1], re.M)
    print(json.dumps({"q": {i: "Still waiting on that?" for i in ids}}))
elif "For each journal entry" in p:
    ids = re.findall(r"--- id (\S+)", p)
    print(json.dumps({"entries": [{"id": i, "summary": "Owner asked to email Sarah Lee at Acme about the offer.",
        "decided": ["email Sarah"], "promises": [{"text": "Email Sarah Lee the signed form", "who": "assistant", "due": "2026-11-10"}],
        "followups": [], "people": [{"name": "Sarah Lee", "company": "Acme Robotics", "role": "Recruiter", "email": "sarah@acme.example"}],
        "facts": [{"text": "Prefers morning calls", "private": False}], "projects": ["Job search"], "private": False} for i in ids]}))
elif "profile facts" in p:
    rows = re.findall(r"^(f\w+) \| ([^|]+) \| ([^|]+) \|", p, re.M)
    col = [r[0] for r in rows if "concise" in r[2].lower()]
    learned = [r[0] for r in rows if r[1].strip() == "Learned on calls"]
    print(json.dumps({"merge": [{"ids": col[:2], "text": "Prefers concise replies and summaries"}] if len(col) >= 2 else [],
                      "superseded": [], "sections": {i: "Preferences" for i in learned}}))
elif "went wrong" in p:
    refs = re.findall(r"--- ref (\S+)", p)
    print(json.dumps({"mistakes": [{"ref": r, "what": "Email send was blocked", "rule": "When an email send is blocked, say it was not sent and offer a draft"} for r in refs[:1]]}))
elif "Signals:" in p:
    print(json.dumps({"preferences": [{"text": "Answers most calls in the afternoon", "why": "7 of 7 calls answered after 1pm"}]}))
elif "one or two short sentences" in p:
    print("Mention your design experience.")
else:
    print("ok")
