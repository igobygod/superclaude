# iMessage and Shortcuts: texting the agent

## Incoming text, hop by hop

1. **You text the "Claude" contact** (the agent's own Apple ID, `AGENT_APPLE_ID`) from your iPhone.
2. **The Mac receives it** in Messages, which is signed in as the agent's Apple ID.
3. **The Mac listener reads it.** `~/bin/imessage-agent` (running inside `ImsgAgent.app`, which has Full Disk Access) reads `chat.db` **read-only** about every 3 s, or at once when poked. It only takes **one-to-one** chats from your handles (`OWNER_PHONE`, `OWNER_EMAIL`). It removes echoes and duplicates (state in `~/.imessage-agent/`: `pid`, `sent.log`, a ledger).
4. **Attachments** from your thread are converted: photos to JPEG (max 2000 px, with `sips`; HEIC conversion tested but not seen from a real HEIC yet), voice notes to mono 16 kHz MP3 (`ffmpeg`), videos and files up to 60 MB (bigger stay on the Mac).
5. **It forwards** text and media over SSH with a restricted key to `imsg-receive` on the server (a JSON line plus raw bytes).
6. **`voice-notify` daemon** stores it in `/var/lib/voice-questions/vq.db` and hands it to the text brain `brain.py`.
7. **Gemini first.** The brain builds a short prompt (persona in text form, your local time from `AGENT_TZ`, memory, lessons, open questions, the last messages of the thread) and sends it through the `voice-gemini-chat` socket. Models are picked by real availability, about 2.5 s per attempt, at most 2 attempts.
8. **The brain's tools:** `delegate_to_claude`, `recall`, `remember`, `answer_question`.
   - Real work -> `delegate_to_claude`: you get a neutral "On it, sir." right away, and the result later, starting with `Re: "<first 50 chars of your message>" —` so you know which message it answers.
   - Gemini never sends mail or texts itself. Sends go to Claude with a read-back; the send stays locked until you say yes (`[AWAITING_CONFIRM]`).
9. **Straight to Claude** (skipping Gemini) when: your message is a "yes" right after a read-back, it has an attachment, or Gemini failed in any way. Nothing is left unanswered.
10. **Honesty guard:** if a reply claims "done / saved / set / sent" without a successful tool result, it is replaced with "On it, sir." and the work is delegated.
11. **Reply** goes back through `imessage-send` -> SSH to the Mac -> `imessage-send-mac` -> Messages. If the Mac can't be reached, the reply goes to Telegram.
12. Each message from you also gives the Mac a **30-minute wake lease**, so the conversation can continue.

Typical speed for a quick answer: about 3-4 s end to end. Voice notes are transcribed by Gemini and treated as your words; pictures are shown to Gemini (Claude as fallback).

## Shortcuts

- **Ask Claude** (Share Sheet / Siri) posts to `/ask/<secret>` -> `voice-ask` stores it as an owner request tagged `[ASK:shortcut]` -> the same pipeline as above. You get "Got it, working on it" at once and the answer by iMessage.
- **Wake Claude / Text Claude / Force Wake** wake the Mac so the listener can read your texts. Details in [setup/09-shortcuts.md](../setup/09-shortcuts.md).
- **Heartbeat:** the listener posts to `/beat/<secret>` every 30 s. A fresh beat (under 60 s) means the Mac is awake, so "Wake Claude" only pokes the listener (`imessage-agent --poke`, which makes it scan right away).

## Why some design choices

- **A separate Apple ID**: with your own ID, Apple doubled every self-chat message and echoed it back. See [setup/08-apple-id-imessage.md](../setup/08-apple-id-imessage.md).
- **Gemini first**: most texts are quick questions; Gemini answers in seconds and doesn't use your Claude plan.
- **Read-only database access**: the listener never writes to `chat.db`.
