# 9. iPhone Shortcuts

Shortcuts are one-tap buttons (Home Screen, Share Sheet or Siri) that call your server over HTTPS. Each one uses a **secret link**: the path after `/call/`, `/ask/`, `/wake/` or `/force/` is a long random string that only your shortcut knows. A wrong path gets "Not found". Treat a shortcut file like a password: anyone who has it can use it.

Set up HTTPS first ([10-telegram-nginx-https.md](10-telegram-nginx-https.md)). The original shortcuts were exported as **signed** shortcut files (sign mode "anyone") and sent to the owner on Telegram to import.

## The shortcuts

| Shortcut | What it does | Server side | Verified? |
|---|---|---|---|
| **Call me** (originally "Call Claude") | Sends a request to `https://PUBLIC_HOST/call/<secret>`. The server answers "Calling you now" and rings your Linphone app within seconds. | `voice-watcher` on 127.0.0.1:7891 queues a call with the reason "The owner tapped Call me and wants to talk". Secret: `CALL_TOKEN`. | Yes, calls ring and connect. |
| **Ask Claude** | From the Share Sheet or Siri: sends text, a link, or a file (up to 14 MB) to `/ask/<secret>`. You get an instant "Got it, working on it" iMessage, then the answer by iMessage. | `voice-ask` (127.0.0.1:7894) saves it as an owner request; `voice-notify` handles it exactly like an iMessage (Gemini first, Claude for real work). Holds a 30-minute Mac wake lease. Limit 30 requests per hour. | Server side yes; it joins the same tested text pipeline. |
| **Wake Claude** (smart wake) | Sends a request to `/wake/<secret>` and shows the reply as a notification. | If the Mac's heartbeat is fresh (under 60 s old), it only tells the listener to scan for new messages now, and replies "Claude is already awake" (about 1.9 s). Otherwise it SSHes to the Mac through the Apple TV path (which wakes it), starts a 30-minute wake lease, scans, and replies "Woke Claude". If the Mac can't be reached after 2 tries (about 20 s): "Mac unreachable, use Telegram", a Telegram note, and a background retry for 2 minutes that tells you if the Mac comes back. | Server side yes (already/woke/force/stale/wrong-secret tests). The notification display on the phone: **not verified**. |
| **Text Claude** | Asks for text (or Siri dictation), sends it as an iMessage from your iPhone to `AGENT_APPLE_ID` (without opening Messages), then runs the smart wake and shows a notification. Works from the Home Screen or "Hey Siri, text Claude". | Same as Wake Claude, plus the normal iMessage path. | Imports fine. **Not verified on a phone:** the Send Message recipient handling, the Siri phrase, and the notification. |
| **Force Wake** | Sends a request to `/force/<secret>`. Always wakes the Mac and holds it awake for 30 minutes. Replies "Mac awake". | Same code as smart wake, without the heartbeat shortcut. | Server side yes. |
| **Self-text "wake" automation** | An iOS Personal Automation: when you send yourself a message containing "wake", run Wake Claude. | Same as Wake Claude. | **Not verified.** It is unknown whether iOS fires a Message automation for texts you send yourself. |

`/wake/` and `/force/` share the Ask Claude secret. Rate limits: a repeat tap within 20 s (smart) or 10 s (force) is answered from a cache, and there are at most 30 real wakes per hour. The reply also carries an `X-Wake` header with JSON (`ok`, `state`) if you want to branch on it in the shortcut.

## The heartbeat (why smart wake is fast)

The Mac listener posts a heartbeat to `/beat/<beat secret>` every 30 seconds (its own secret, stored in `/etc/voice-ask/beat-token` on the server and in `~/.imessage-agent/beat-token` on the Mac). The server counts the Mac as awake when the last beat is under 60 s old, so it can skip the slow SSH wake.

## Building the shortcuts yourself

Assumption: the original shortcut files are not in this repo (they contain secrets). Each one is simple to rebuild in the Shortcuts app:
1. "Get Contents of URL" with method **POST** and your secret link (for Ask Claude: a form with fields `text`, `url` and/or `file`; text, JSON or a multipart form all work).
2. "Show Notification" with the result.
3. For Text Claude, put "Send Message" (recipient: the agent's Apple ID, "Show When Run" off) before step 1.

## Where the secrets live on the server

`CALL_TOKEN` in `/etc/voice-caller/secrets.env`; the Ask/Wake secret in `/etc/voice-ask/token` (root:claude-helper 640); the heartbeat secret in `/etc/voice-ask/beat-token`. Make each one with something like `openssl rand -hex 24`. Never print them in logs.
