# 11. systemd services and timers

Every server part runs as a systemd unit, so it starts at boot, restarts on crashes, and logs to `journalctl`.

## Install

1. Copy the code to the paths the units expect:
   - `server/voice-caller/` -> `/srv/voice-caller/`
   - `server/lib/voice-*/` -> `/usr/local/lib/voice-*/` (owned by root, so services can't change their own code)
   - `server/bin/*` -> `/usr/local/bin/`, `server/sbin/*` -> `/usr/local/sbin/`
   - `server/systemd/*` (units and the `*.service.d/` drop-in folders) -> `/etc/systemd/system/`
2. Create the secret and settings files in `/etc/voice-caller/` (see `config/superclaude.env.example`) and `/etc/mac-helpers/route.env` if you use `mac-route`.
3. **Set the server's time zone.** The timers have no zone written in `OnCalendar=`, so they run on the server's local time. Set it to the same zone as `AGENT_TZ`: `sudo timedatectl set-timezone America/New_York` (use your own zone).
4. `sudo systemctl daemon-reload`, then enable and start the services and timers you want: `sudo systemctl enable --now voice-caller voice-watcher voice-tasks ...` and `sudo systemctl enable --now voice-health.timer ...`.

Why drop-ins (`*.service.d/*.conf`): settings and extra rules are added *next to* the unit instead of editing it, so updates don't wipe your settings. After editing a drop-in run `daemon-reload`; restart the unit only if needed, and never during a live call.

## Long-running services

| Unit | Runs as | What it does |
|---|---|---|
| `voice-caller.service` | voicecaller | The voice agent (`agent.py start`, agent name `pa-caller`). Before each start it runs `call.py --setup-trunk` to recreate the outbound SIP trunk. Reads `livekit.env` and `secrets.env`. |
| `voice-watcher.service` | voicecaller | `watcher.py`: calendar calls, urgent-email calls, snoozes, missed-call retry, call requests, the "Call me" endpoint (127.0.0.1:7891), marks calls ended when their room is gone. |
| `voice-sip-relay.service` | kamailio | Kamailio relay for inbound calls. `gen.py` builds its runtime config in `/run/voice-sip-relay/` from the secrets at each start; the config is checked (`kamailio -c`) before it starts. |
| `voice-tasks.service` | claude-helper | `task_runner.py`: the task queue to headless Claude, the warm spare, the `ask.sock` socket, the kill switch. |
| `voice-notify.service` | claude-helper | Text brain daemon: incoming iMessages / Ask Claude, outgoing notifications, escalation, open questions. |
| `voice-ask.service` | claude-helper | The Ask Claude / Wake / Force / heartbeat endpoint (127.0.0.1:7894). |
| `voice-gemini-chat.service` | voicecaller | Holds the Gemini key for the text brain; socket `/run/voice-gemini-chat/chat.sock`. |
| `voice-gemini.service` | voicecaller | Holds the Gemini key for video review and captions; socket `/run/voice-gemini/gemini.sock`. |
| `voice-memory-llm.service` | claude-helper | A Claude Haiku helper socket so other users (like the sandboxed voice agent) can run memory recall. |
| `voice-dashboard.service` | claude-helper | The private job dashboard (127.0.0.1:7893). Copies `DASH_TOKEN` from `secrets.env` into a private runtime file before starting. |
| `mac-route.service` | root (oneshot, stays "active") | Adds the two ip rules that route only the Mac's address through Tailscale. |

## Timers (scheduled jobs)

| Timer | When | What its service does |
|---|---|---|
| `voice-health.timer` | every 5 min (3 min after boot) | Checks the 3 voice services, the 3 containers, `trunk_id`, disk over 90%, free memory under 300 MB. Telegram alert after 2 bad runs in a row, one "recovered" message. |
| `voice-backup.timer` | daily 03:30 | Backup to `/var/backups/voice-agent/*.tar.gz` (mode 600, kept 7 days; skipped if disk is short). Contains secrets, so root-only. |
| `voice-summary.timer` | daily 21:00 | Daily summary to Telegram. |
| `voice-capabilities.timer` | daily 05:15 and 3 min after boot | Writes the real list of Claude connectors, skills and Mac helpers. |
| `voice-memory-sync.timer` | every 10 min | Safety-net merge of profile edits (the `.path` unit below normally does it within a second). |
| `voice-memory-nightly.timer` | daily 03:05 | Journal catch-up, Haiku extraction, de-duplication, mistakes to rules, behaviour proposals, one question a day. |
| `voice-memory-weekly.timer` | Sunday 18:30 | Weekly review to Telegram. |
| `voice-memory-review.timer` | every minute | Reviews each finished call/chat once and writes lessons. |
| `voice-sweep.timer` | every minute | Marks stuck jobs as failed. |
| `voice-dash-collect.timer` | every 30 s | Copies recent calls for the dashboard (runs as root because the call log is private). |
| `voice-usage-poll.timer` | every 2 min | Reads Claude plan usage; one Telegram warning at 80% and one on recovery. |
| `voice-extras-tick.timer` | every minute | Due reminders and scheduled extras (briefing, digests, mail watch...). |
| `voice-creator-monitor.timer` | every 10 min | Checks your channel's new uploads (optional). |
| `voice-creator-weekly.timer` | Sunday 18:00 | Weekly channel report (optional). |
| `voice-media-telegram.timer` | every 15 s | Copies Telegram photos/voice notes into the media inbox. |
| `voice-media-prune.timer` | daily 04:10 | Deletes inbox media older than 7 days unless kept. |

## Path units (run when a file appears or changes)

| Unit | Watches | Runs |
|---|---|---|
| `voice-memory-sync.path` | `/var/lib/voice-tasks/profile.md` and the helper's `notes/USER.md` | `voice-memory sync` (imports your edits to either view) |
| `voice-install-spool.path` | `/var/lib/voice-install/inbox/*.json` | `voice-install spool` as root (the approved installer) |

## Alerts and drop-ins

- `voice-alert@.service`: sends an instant Telegram alert naming the failed unit.
- `onfailure-alert.conf` drop-ins on `voice-caller`, `voice-watcher` and `voice-tasks` add `OnFailure=voice-alert@%N.service`.
- `voice-caller.service.d/model.conf`: `GEMINI_LIVE_MODEL=gemini-3.8-live`, `SILENCE_MS=300`, `GEMINI_VOICE=Puck`, `SPEED_UP=off`. Keep `SPEED_UP=off` (the code default `on` broke speech).
- `helper-paths.conf` on voice-caller and voice-watcher: `ReadWritePaths=/var/lib/voice-memory /var/lib/voice-questions`, because those services run with a read-only system (`ProtectSystem=strict`).
- `umask.conf`: `UMask=0007`, so files they create are readable by the shared group.

## State folders to create

Create these before the first start (owner:group in brackets, as in the original): `/var/lib/voicecaller` (voicecaller), `/var/lib/voice-tasks` and its `queue running done jobs call-requests watches memory-inbox` subfolders (claude-helper:voicetasks), `/var/lib/voice-memory` and `/var/lib/voice-questions` (claude-helper or root : voicetasks, mode 2770), `/var/lib/voice-usage`, `/var/lib/voice-extras`, `/var/lib/voice-creator`, `/var/lib/voice-media`, `/var/lib/voice-gemini-chat`, `/var/lib/voice-safety`, `/var/lib/voice-install/inbox`.
Assumption: there is no install script that creates them for you; check each service's journal on first start for "No such file" or "Permission denied" and fix the folder.
