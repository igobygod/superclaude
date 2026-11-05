---
name: superclaude
description: Install, configure, debug, maintain or extend SuperClaude, a self-hosted always-on personal assistant (Gemini Live phone calls through Linphone/LiveKit, iMessage through a Mac, Telegram, headless Claude Code task worker, memory, self-review, dashboard, Mac control). Use when the user wants to set it up on an Oracle/Linux server or an always-on Mac, says the assistant "didn't answer", "ghosted", "is slow", "texts are doubled", "can't reach the Mac", wants a new tool, setting or helper, or mentions voice-caller, voice-notify, voice-memory, mac-run, Kamailio, livekit-sip or Linphone. Not for unrelated server work.
---

# SuperClaude: install and maintain

SuperClaude has a fast **Gemini** front desk (voice on phone calls, text on iMessage) and a **Claude Code** back office (real work through a task queue). A Mac reached over Tailscale handles iMessage and Mac control. Memory and lessons feed every brain, and reviewers write new lessons after each call and chat.

## Where things are
Find the repo first. Ask the user for its path if `$SUPERCLAUDE_REPO` isn't set; it's usually where they cloned it.
- `README.md`: overview and repo map
- `docs/setup/00-overview.md` … `12-always-on-mac-host.md`: install steps, in order
- `docs/how-it-works/`: every flow, hop by hop. Read the matching file before changing a flow.
- `docs/troubleshooting.md`: real bugs and their root causes. Match a symptom here before guessing.
- `docs/features.md`, `docs/codex.md`
- `config/superclaude.env.example`: every setting, with placeholders
- [references/maintenance-rules.md](references/maintenance-rules.md): safe-deploy rules and hard rules (read before any change)

Installed layout on the server: `server/voice-caller/` → `/srv/voice-caller/`, `server/lib/voice-*` → `/usr/local/lib/voice-*`, `server/bin` → `/usr/local/bin`, `server/sbin` → `/usr/local/sbin`, `server/systemd` → `/etc/systemd/system`, `server/nginx/voice.conf` → an nginx site. Mac scripts go in `~/bin` on the Mac.

## Installing for a new user
1. Read `docs/setup/00-overview.md` and confirm with the user which host they want: an Oracle/Linux server, or an always-on Mac.
2. Work through the setup docs in order. Do every command yourself. Stop only for the steps that need the user: account sign-ups and sign-ins (Oracle, Linphone, Google AI Studio, Tailscale, Apple ID, Telegram BotFather, Claude login), iPhone app settings and Shortcuts, and macOS permission prompts (Remote Login, Full Disk Access, Accessibility, Screen Recording). Give them one short instruction at a time.
3. Secrets go only in root-only env files on the server, never in the repo, chat logs or command lines that get echoed back.
4. Bring it up layer by layer and test each one before moving on: Docker stack → outbound test call (with the user's OK) → inbound call → text brain → Mac link → iMessage → Claude tasks → memory and reviewers → extras.

## Debugging
1. **Evidence first.** Run `agent-status`, then read the call log (`/var/lib/voicecaller/calls.jsonl`) and `journalctl -u voice-caller` / `-u voice-notify` for the time in question. Use `docker logs` for the SIP container (codec and SIP status codes).
2. Match the symptom to `docs/troubleshooting.md`. Find the root cause before changing anything.
3. Make the smallest fix that fits the existing patterns, and add or extend an offline test (`test_features.py`, `test_voice_memory.py`, `test_vn.py`).
4. Deploy with `deploy.sh`, which refuses while a call is live or a task is running.
5. Verify honestly: "offline tests pass" isn't "worked on a real call". Only the user can make a real test call, so ask them.
6. Add any new bug to `docs/troubleshooting.md`.

## Hard rules (never relax them)
- **Never ghost the user.** Every turn gets an answer. Keep the code guards (ReplyGuard, StallWatch) in place.
- **Never claim an action that no tool performed** (ClaimGuard).
- **Read back before sending**, and confirm the go-ahead in code before any email, text or message to someone else.
- **Private facts** (health, money, ID numbers and similar) stay on the Claude side and never go to Gemini.
- **Ask first** before payments, deleting, posting publicly, messaging anyone but the user, changing security settings, or deploying self-made code changes.
- Never place test calls or send test messages to the user without their OK. Never message anyone else.
- Never rebuild or re-sign the Mac wrapper apps (`ImsgAgent.app`, `MacRunWorker.app`): macOS would drop their permission grants.

## Extending
- A new voice tool goes in `agent.py`, following the existing tool pattern, with a test in `test_features.py`. Watch for top-level name clashes: a helper named `cli` once crash-looped the agent.
- A new proactive helper goes in `voice-extras` (timer-driven), and all Claude work it needs goes through the task queue.
- A new text ability goes in `brain.py` tools. Gemini never sends anything itself; sending goes to Claude with read-back gating.
- Settings are env vars read with defaults. Add each new one to `config/superclaude.env.example`.
