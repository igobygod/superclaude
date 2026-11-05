# Mac helpers on the server
Copy on the server: /etc/mac-helpers/README.md

## Path
server --Tailscale--> an Apple TV (subnet router for HOME_SUBNET, Bonjour Sleep Proxy) --> Mac at MAC_LAN_IP:22.
Sleeping Mac (lid closed, on AC) wakes on the SSH connect: verified asleep: the SSH connect woke it and an iMessage went out within seconds.
Server routing: mac-route.service adds ip rules (5200: MAC_LAN_IP via Tailscale table 52; 5260: the rest of HOME_SUBNET = the server's own cloud network stays local). Both values live in /etc/mac-helpers/route.env.

## Who can call
Members of group `macaccess` (the admin user and claude-helper). Key /etc/mac-helpers/mac_key (root:macaccess 640).
`voice-tasks.service` (User=claude-helper) must be RESTARTED once to pick up the new group (not done; voice-core owns it).
To let voicecaller call too: `sudo usermod -aG macaccess voicecaller` + restart voice-caller.

## imessage-send RECIPIENT MESSAGE
  imessage-send OWNER_PHONE "hello"      -> prints "sent", exit 0
Exit: 0 sent, 2 usage, 75 Mac unreachable (~2 min of retries), 124 timeout (180 s), else osascript error.
Owner's own handle: OWNER_PHONE (or OWNER_EMAIL). Sending to anyone else needs the owner's spoken yes.

## mac-run [-d DIR] [-t SECS] [--full] [-m MODEL] [--json] "PROMPT"
Runs headless Claude Code (claude -p, Claude subscription, Mac's CLAUDE.md/skills/tools) on the Mac, prints the answer.
  mac-run -d "~/Documents/MyApp" -t 900 "Build the app with xcodebuild and tell me if it passes"
  mac-run --json -m sonnet "..."   -> JSON with result, session_id, permission_denials, cost
- default mode: edits allowed + owner's allow rules; anything else is DENIED (not hung); prompt says BLOCKED.
- --full: --dangerously-skip-permissions. Only after the owner says yes out loud for that task.
- -t default 600, max 3600. Exit 124 = timed out (Claude killed). 3 = bad folder. 75 = Mac unreachable. 70 = worker problem.
Mac side: ~/bin/mac-run-mac (SSH entry) queues ~/.mac-run/queue -> LaunchAgent com.superclaude.mac-run (~/bin/mac-run-worker)
(via ~/Applications/MacRunWorker.app) runs ~/bin/mac-run-exec inside the login session (needed: SSH sessions can't read Claude's keychain sign-in, error 36).
Jobs run one at a time. Logs: ~/Library/Logs/mac-run/ on the Mac.
Each server login keeps the Mac awake 3 min (LC_WAKE_LEASE_MIN via ~/.ssh/rc); a run keeps it awake while it lasts.

## Sessions on the Mac
  mac-run sessions [N]     recent Claude Code sessions: [id] title, folder, last activity (+ SPOKEN line)
  mac-run running          Claude processes running now (interactive vs headless), folder, latest session there
  mac-run -r ID [-t S] [--full] "instruction"   resume that session headless in ITS folder (claude --resume ID -p)
     -> exit 4 + SPOKEN warning, nothing run, if its transcript changed in the last 10 min (owner may be using it)
     -> exit 3 if the id is unknown
Every text-mode output ends with one "SPOKEN: ..." line (Claude is told to write it; wrapper adds a fallback).
All runs get an appended system prompt: unattended, stop and report on Ask-first/risky steps (verified: --full
"turn off the firewall" -> refused and reported, rc 0). The voice agent should read the SPOKEN line aloud and
send the rest by Telegram if long.
Wake: a run holds `caffeinate -i -s` for exactly its duration (same effect as ~/bin/wake-lease but ends with the job
and never cuts short the owner's own lease).

## Locked screen / lid closed
Works (background): claude -p runs, file edits, git, shell, xcodebuild builds, iMessage via Messages (verified asleep+lid closed for iMessage).
GUI clicks (agent-desktop): WORK via mac-run (verified: an agent-desktop snapshot of Finder worked). You grant
Accessibility to ~/Applications/MacRunWorker.app (ad-hoc signed launcher that parents every job; LaunchAgent runs it).
Do NOT rebuild/re-sign MacRunWorker or the grant is lost. GUI actions still need the screen UNLOCKED.
Not yet verified: mac-run right after waking from sleep with the screen locked (keychain should stay unlocked; test once).

## Wiring (for voice-core, later)
subprocess.run(["/usr/local/bin/mac-run","-t","600",prompt], capture_output=True, text=True, timeout=800)
  -> spoken = last line starting "SPOKEN:"; rc 4 = session busy, 75 = Mac unreachable, 124 = timed out
subprocess.run(["/usr/local/bin/mac-run","sessions","5"], ...)   /  ["/usr/local/bin/mac-run","-r",sid,"-t","900",instr]
subprocess.run(["/usr/local/bin/imessage-send",to,text], capture_output=True, timeout=200)
Speak a short "working on it" first; mac-run can take minutes.
