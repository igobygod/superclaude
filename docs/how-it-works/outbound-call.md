# Outbound call: the server rings your iPhone

## What can start a call

| Trigger | Who decides |
|---|---|
| A timed calendar event starts in 10 minutes (all-day, declined and cancelled events are skipped) | `voice-watcher`, reading your private calendar feed (`CALENDAR_ICS_URL`) |
| An urgent email (optional) | `voice-watcher`: a Claude Haiku model triages emails your separate mail sorter kept (max 40 a day, emails older than 30 min ignored) |
| A delegated task finished (and wasn't already announced on a live call) | `voice-watcher` |
| A call request file from any part of the system, e.g. the Telegram helper or `voice-notify` escalation | `voice-watcher` reads `/var/lib/voice-tasks/call-requests/<id>.json` = `{"reason": "...", "details": "...", "urgent": true/false}` (reason up to 300 chars, details up to 1000) |
| The "Call me" shortcut | `voice-watcher`'s `/call/<secret>` endpoint |
| By hand | `sudo voicecall "reason" --details "..."` |
| A snooze you asked for ("call me back in 20 minutes") | `voice-watcher` |

## Step by step

1. **Rules check.** The watcher respects quiet hours (`QUIET_HOURS`, default `23-7` in your `AGENT_TZ`; `off` disables): during quiet hours you get Telegram only, unless it is urgent. Daily caps also apply (see [notify-and-questions](notify-and-questions.md)).
2. **Create a room.** `call.py` creates a LiveKit room and dispatches the agent named `pa-caller` into it, with the reason and details as metadata.
   Why: in LiveKit every call is a "room"; the agent and the phone are both participants.
3. **Dial.** The agent asks livekit-sip to add a SIP participant through the outbound trunk `linphone`. livekit-sip calls `sip:<OWNER_SIP_USER>@sip.linphone.org`, signing in with the server Linphone account's password (digest auth), with **SRTP required**.
4. **Linphone push.** Linphone's servers send a push notification that wakes the Linphone app and rings the phone, even when it is locked.
5. **Ring.** The agent waits up to 40 s (`RING_SECONDS`).
6. **Answer.** Audio flows phone <-> livekit-sip as SRTP on UDP 10000-10100; livekit-sip <-> LiveKit <-> agent on the server itself. The event `answered` is written to `/var/lib/voicecaller/calls.jsonl`.
7. **Talk.** See [during-a-call](during-a-call.md). The agent opens with why it called.
8. **Hang up.** The event `ended` is written; the transcript goes to the memory journal and call notes go to Telegram.

## When it doesn't connect

- **Missed:** the watcher retries **once after 3 minutes**, then sends you a Telegram message.
- **SIP 404:** the Linphone app on the phone isn't signed in.
- **SIP 488:** media encryption mismatch (the app isn't using SRTP).
- **SIP 486:** you declined.
- **Room gone, no `ended`:** every 60 s the watcher checks that each open call's room still exists, and marks it ended ("room gone") if not.
