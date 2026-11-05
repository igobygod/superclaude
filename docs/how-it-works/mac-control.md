# Mac control

The server controls the home Mac with three commands (in `server/bin/`, usable by the `macaccess` group). Every output ends with a `SPOKEN:` line that the voice reads aloud; the rest can go to Telegram if long.

## The path

server -> Tailscale -> Apple TV (subnet router + Sleep Proxy) -> Mac SSH (`MAC_LAN_IP`). A sleeping Mac wakes on the connect. Each login sets `LC_WAKE_LEASE_MIN=3`, so the Mac stays awake 3 minutes. See [setup/06](../setup/06-tailscale-apple-tv-mac.md) and [setup/07](../setup/07-mac.md).

## Commands

| Command | What it does | Exit codes |
|---|---|---|
| `mac-ssh CMD...` | Runs a command on the Mac. Tries 6 times over about 2 minutes while the Mac wakes. | 75 = Mac unreachable |
| `imessage-send RECIPIENT "text"` | Sends an iMessage from the agent's Apple ID. Prints "sent". Anyone other than you needs your spoken yes. | 0 sent, 2 usage, 75 unreachable, 124 timeout (180 s) |
| `mac-run [-d DIR] [-t SECS] [--full] [-m MODEL] [--json] "PROMPT"` | Runs headless Claude Code on the Mac with the Mac's own CLAUDE.md, skills and tools. `-t` default 600, max 3600. | 124 timed out, 3 bad folder, 75 unreachable, 70 worker problem |
| `mac-run sessions [N]` | Lists recent Mac Claude sessions (id, title, folder, last activity). | |
| `mac-run running` | Claude processes running now (interactive vs headless). | |
| `mac-run -r ID "instruction"` | Resumes that session headless in its own folder. Refuses if the session was active in the last 10 minutes (you may be using it). | 4 busy, 3 unknown id |

## How a mac-run job flows

1. Server `mac-run` -> SSH -> Mac `~/bin/mac-run-mac` (the SSH entry point).
2. `mac-run-mac` queues the job in `~/.mac-run/queue` and waits.
3. The LaunchAgent `com.superclaude.mac-run` runs `mac-run-worker` inside `MacRunWorker.app`, in your logged-in session, which runs `mac-run-exec`.
   Why: SSH sessions can't read Claude Code's sign-in from the keychain (error 36), but the login session can. The app wrapper also holds Accessibility and Screen Recording.
4. Jobs run one at a time. While a job runs, `caffeinate -i -s` keeps the Mac awake for exactly that long.
5. Every run gets an extra system prompt: unattended, stop and report on ask-first or risky steps. (Tested: even with `--full`, "turn off the firewall" was refused and reported.)

## Permissions

- Default: edits allowed + your own allow rules in the Mac's Claude settings; anything else is **denied** (not stuck) and reported as BLOCKED.
- `--full` (skip permissions) only after a spoken yes for that task.

## Look at the screen

`look_at_mac_screen` runs `~/bin/mac-look.py` through mac-run: checks whether the screen is locked, takes one screenshot scaled to 1280 px, lets the model describe it, and deletes it. Needs Screen Recording on `MacRunWorker.app`.

## Steering Mac sessions from a call

`list_mac_sessions`, `live_mac_sessions`, `resume_mac_session`, `send_to_session` (a send, so it needs read-back + yes).

## What works when

- Asleep / lid closed / locked: `claude -p`, file edits, git, shell, builds, iMessage (verified).
- GUI clicks: work, but the screen must be **unlocked**.
