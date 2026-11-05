# Notifications and open questions

Two small CLIs let any part of the system (including Claude jobs) reach you without spamming you. Code: `server/lib/voice-notify/`. State: `/var/lib/voice-questions/vq.db`.

## voice-notify: tell the owner something

```
voice-notify --level info|important|urgent --text "..." [--question-id Q]
```

| Level | What happens |
|---|---|
| `info` | An iMessage. Telegram if the Mac can't be reached. |
| `important` | An iMessage, then a call request after 10 minutes if the linked question is still open. |
| `urgent` | A call request **and** an iMessage right away. |

Daily caps (per day in `AGENT_TZ`): 40 texts (urgent doesn't count), 3 "important" calls, 5 calls in total. Calls skip quiet hours (23-7 by default) unless urgent.

Why: the agent is proactive, so it needs hard limits that a model can't talk its way around.

## voice-questions: ask the owner something and act once

```
voice-questions add --text "..." --kind approve|decide|check [--ref gmail:<thread>|cal:<uid>|jobsearch:*] [--action "..."]
voice-questions answer ID --via imessage|telegram|call|self --text "..."
voice-questions list --open|--all [--json]
voice-questions close ID
```

- The **first answer wins**, from any channel. `answer` exits **0** = "act now, once"; exit **3** = "already done", do not act again.
  Why: you might answer on a call and by text; the action must still happen only once.
- Open questions are put into every call and text prompt, so you can answer them anywhere ("yes to the second one").
- Open questions expire after 3 days.

## Waking the Mac for a reply

If a question is waiting and the Mac may be asleep, the daemon pokes the Mac listener (`imessage-agent --poke`) every 10 minutes from +10 to +60 minutes, then every 30 minutes up to 4 hours, so your answer is picked up.

## Call requests

Any part can ask for a call by writing `/var/lib/voice-tasks/call-requests/<id>.json` with `{"reason": "...", "details": "...", "urgent": false}`. `voice-watcher` places it, following quiet hours and caps.
