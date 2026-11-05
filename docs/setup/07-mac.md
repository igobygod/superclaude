# 7. The Mac

The Mac does three jobs: it is the agent's iMessage phone, it runs Claude Code jobs that need your Mac (builds, files, apps), and it can take a screenshot for "look at my screen". The Mac-side scripts are in `mac/bin/` and go in `~/bin` on the Mac.

## 1. Turn on Remote Login

System Settings > General > Sharing > **Remote Login** on, for your user only.
Why: the server reaches the Mac only over SSH. This is a security setting, so do it yourself and limit it to your user.

## 2. SSH keys (each one does one job)

| Key | Direction | Locked down by | Used for |
|---|---|---|---|
| Server-to-Mac key (on the server at `/etc/mac-helpers/mac_key`, root:macaccess 640) | server -> Mac | A `from="<home subnet>,100.64.0.0/10"` option on its line in the Mac's `authorized_keys`, so it only works from your LAN or your tailnet | `mac-ssh`, `imessage-send`, `mac-run`, wake requests |
| iMessage forward key | Mac -> server | `restrict,command="..."` on the server so it can only hand messages to `imsg-receive` | The Mac listener forwarding your texts |
| Journal key | Mac -> server | `restrict,command="/usr/local/bin/voice-memory mac-ingest"` in `claude-helper`'s `authorized_keys` | The Mac Claude Code hook that journals finished sessions |

Why separate keys: if one leaks, it can only do its one job.
The server also pins the Mac's host key in `/etc/mac-helpers/known_hosts` (`StrictHostKeyChecking=yes`), so it never talks to an impostor.
Assumption: the exact forced command on the iMessage forward key isn't recorded; point it at `/usr/local/bin/imsg-receive`.

## 3. A short wake lease for every server login

`mac-ssh` sends `LC_WAKE_LEASE_MIN=3`. On the Mac, a small `rc` file in your SSH folder reads that value and runs `~/bin/wake-lease 3`, which keeps the Mac awake for 3 minutes.
Why: after the Sleep Proxy wakes the Mac, it would fall asleep again in the middle of a job.
`~/bin/wake-lease [minutes]` (default 30) runs `caffeinate -i -s` for that long, replaces any older lease, and logs to `~/.wake-lease.log`.
Assumption: the `rc` file itself is not in this repo; it needs to call `wake-lease "$LC_WAKE_LEASE_MIN"` when that variable is set, and the Mac's SSH server must accept `LC_*` variables (macOS does by default, as far as we know).

## 4. The two app wrappers (permissions)

macOS gives privacy permissions to an **app**, not to a script. So each long-running script is started by a tiny app wrapper that holds the permission:

| Wrapper | Runs | Permission (System Settings > Privacy & Security) | Why |
|---|---|---|---|
| `~/Applications/ImsgAgent.app` | `~/bin/imessage-agent` (LaunchAgent `com.superclaude.imessage-agent`) | **Full Disk Access** | To read the Messages database (`chat.db`) and attachments, read-only. |
| `~/Applications/MacRunWorker.app` | `~/bin/mac-run-worker` (LaunchAgent `com.superclaude.mac-run`) | **Accessibility** and **Screen & System Audio Recording** | GUI clicks for Mac jobs, and screenshots for "look at my screen". |

**Never rebuild or re-sign these two apps.** macOS ties the permission to the app's signature. A rebuilt app silently loses Full Disk Access / Accessibility / Screen Recording, and things stop working with no clear error.
Assumption: the app wrappers themselves (small ad-hoc signed launchers) are not in this repo; you create them once.

## 5. LaunchAgents

- `com.superclaude.imessage-agent`: runs the iMessage listener forever, inside ImsgAgent.app.
- `com.superclaude.mac-run`: runs the job worker inside MacRunWorker.app, in your logged-in session.

Assumption: the LaunchAgent plist files are not in this repo; each one should run its app wrapper at login with `KeepAlive` on.

  Why a worker instead of running Claude straight from SSH: an SSH session cannot read Claude Code's sign-in from the macOS keychain (error 36). So `mac-run-mac` (the SSH entry point) puts the job in `~/.mac-run/queue`, and the worker runs `mac-run-exec` inside the login session. Jobs run one at a time; logs are in `~/Library/Logs/mac-run/`.

To restart the iMessage listener, use `pkill -f bin/imessage-agent` (launchd starts a fresh one). `launchctl kickstart -k` alone once killed only the wrapper and left the old Python process running for hours. The listener now also takes over from a stale copy by itself (it reads its `pid` file and stops the old one).

## 6. Claude Code on the Mac

`mac-run` runs `claude -p` on the Mac in safe mode (edits allowed, plus your own allow rules in the Mac's `~/.claude/settings.json`). Anything else is **denied**, not left hanging, and reported as BLOCKED. Example: `osascript` was not allowed, so "close an app" failed until the owner decides to allow it. `--full` (skip permissions) is used only after a spoken yes for that one task.

Optional hook: add `~/bin/voice-journal-hook` as a **Stop** and **SessionEnd** hook in the Mac's Claude settings. It journals finished Mac sessions to the server's memory (throttled to once per 10 min per session). Back up `settings.json` first.

## Locked screen and lid closed

Verified working while asleep or locked: `claude -p`, file edits, git, shell, builds, sending iMessages. GUI actions need the screen **unlocked**. Not verified: `mac-run` right after a wake with the screen locked.
