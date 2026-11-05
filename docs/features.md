# Features

One line each. Details are in [how-it-works/](how-it-works/) and [setup/](setup/).

## Phone calls
- The agent calls your iPhone through the free Linphone app; push rings a locked phone.
- You call the agent by tapping a "Claude" contact in Linphone; only your own account can get through.
- Gemini Live voice (about 1 s to the first word), wideband G722 audio, encrypted media (SRTP).
- Calls 10 minutes before timed calendar events.
- Optional calls for urgent emails (Claude Haiku triage).
- Calls you back when a delegated task finishes.
- "Call me" iPhone shortcut and `voicecall` command.
- Missed call retried once after 3 minutes, then Telegram.
- Snooze ("call me back in 20 minutes") and leave-a-note.
- Quiet hours (Telegram only unless urgent) and daily call caps.
- Pre-recorded greeting in the agent's own voice for inbound calls.
- Noise removal (RNNoise) on incoming audio.
- Quiet "thinking" sounds while tools work over 1 s; you can like, ban or turn them off.
- Saved name pronunciations, with numbered options sent to Telegram when it can't get one right.
- Switch a call to text, set timers, check plan usage, end the call by voice.
- Idle check: "Are you still there?", then hang up; inbound calls capped at 30 minutes.

## Never ghost, never lie
- ReplyGuard forces a reply when the agent goes silent after you speak.
- StallWatch recovers from a stuck turn or deaf input.
- ClaimGuard catches "I changed it" claims no tool backed up.
- Sends need a read-back and a real go-ahead, checked in code.
- "Stop everything" only runs on a clear request.

## Claude does the real work
- Task queue to headless Claude Code (Sonnet or Opus) on your Claude plan, 2 at a time, 45-minute timeout.
- Warm spare Claude for faster starts, one task each.
- Fast `ask_claude` answers on a live call (about 6 s).
- Gmail send tools only for confirmed sends; blocked sends reported as "not sent".
- Daily list of Claude's real connectors and skills, so it never says "can't" wrongly.
- Kill switch: stop all tasks by voice, Telegram, dashboard or command.

## Texting
- iMessage the agent's own Apple ID; Gemini answers in about 3-4 s, Claude for real work.
- Photos, voice notes, videos and files in texts are understood.
- Delayed answers say which message they answer.
- Falls back to Telegram when the Mac is unreachable.
- Telegram chat with an always-on Claude Code session.
- "Ask Claude" Share Sheet / Siri shortcut.
- "Wake Claude", "Text Claude", "Force Wake" shortcuts, plus a Mac heartbeat.

## Memory and learning
- Facts, journal, promises, goals, people, projects, mistakes; nothing ever deleted.
- Private facts stay on the Claude side, never sent to Gemini.
- Nightly clean-up and one question a day; weekly review on Telegram.
- Every call and chat is graded afterwards; safe lessons apply automatically, risky ones need your approval.
- Mac Claude Code sessions journaled by a hook.

## Notifications
- `voice-notify` with info / important / urgent levels and daily caps.
- `voice-questions`: ask once, answer anywhere, act exactly once.

## Mac control
- Run Claude Code on your home Mac from a call or text (`mac-run`), even when it's asleep.
- List, check and resume Mac Claude sessions; message a running session.
- Look at the Mac screen.
- Send iMessages from the Mac.
- Wake the Mac through an Apple TV (Tailscale subnet router + Sleep Proxy).

## Dashboard and safety
- Private job dashboard with Stop / Stop all / Resume.
- Claude plan usage meter with 80% warnings; asks first at 90%.
- Health check every 5 minutes, instant failure alerts, nightly backup, daily summary.
- Approved installer: software installs only with a one-time code you confirm on Telegram.
- One-tap admin commands (`agent-status`, `agent-stop`, `agent-restart`, ...) and a deploy script that refuses during live calls.

## Optional helpers
- Reminders, morning briefing, mail watch (drafts only), patch radar, App Store review watch.
- Gym log, idea vault, Xcode build watch.
- Job-search digest and apply helper (if you have a job-search folder).
- Creator tools: upload monitor, weekly channel report, Gemini video review, trim / silence cut / shorts with captions.
- Shared media inbox for everything you send.
