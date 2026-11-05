# Dashboard, usage meter and safety net

## Job dashboard

- `voice-dashboard.service` (user `claude-helper`, 127.0.0.1:7893) behind nginx at `https://PUBLIC_HOST/jobs/<DASH_TOKEN>/`. The secret link is only ever sent to you on Telegram.
- Shows every voice task and helper job: queued, running, succeeded, failed, timed out, cancelled; progress (`UPDATE:`) lines, duration and result.
- Buttons: **Stop** (one job), **Stop all** (the kill switch), **Resume**.
- `voice-sweep.timer` (every minute) marks stuck jobs as failed. `voice-dash-collect.timer` (every 30 s, as root) copies recent calls for the page, because the call log itself is private.

## Usage meter (Claude plan)

```
voice-usage status [--json] [--refresh]     # e.g. "5h: 78%, week: 83%"
```

- Source: the same usage numbers Claude Code's `/usage` shows, read with the helper's own Claude login. This endpoint isn't documented, so it could change.
- Fallback if the login has expired: one tiny Haiku `claude -p` call (at most once per 30 min), whose rate-limit event carries the same two percentages and refreshes the login.
- Last resort: an estimate from recorded runs, clearly labelled ESTIMATE.
- `voice-usage-poll.timer` (every 2 min) saves `latest.json` and `history.jsonl` in `/var/lib/voice-usage/` and sends **one** Telegram warning when a window reaches 80% and **one** when it drops back.
- At 90% or more, the voice agent asks before hard tasks or Mac jobs.
- The plan is shared with Claude Code on your Mac.

## Safety net

| Piece | What it does |
|---|---|
| `voice-health.timer` (5 min) | Checks `voice-caller`, `voice-watcher`, `voice-tasks`, the 3 containers, `trunk_id`, disk over 90%, free memory under 300 MB. Alerts on Telegram after 2 bad runs in a row (one per problem), one "recovered" message. State: `/var/lib/voice-safety/health.json`. |
| `voice-alert@.service` | Instant Telegram alert when voice-caller, voice-watcher, voice-tasks or the SIP relay fails (`OnFailure=`). |
| `voice-backup.timer` (03:30) | `/var/backups/voice-agent/voice-agent-*.tar.gz`, mode 600, 7 days, skipped if free disk is less than 3x the size + 1 GB. Contains secrets: root-only. Restore with `tar -xzf` as root. |
| `voice-summary.timer` (21:00) | Daily summary on Telegram. |
| Kill switch | `/var/lib/voice-tasks/STOP` (see [task-delegation](task-delegation.md)). |
| Approved installer | The helper can't install software itself. `voice-install-ask request` texts you on Telegram the exact package list plus a random 6-digit code. Only after you reply "yes CODE" may the helper run `voice-install-ask run ID CODE`; `voice-install-spool.path` then runs the root installer `voice-install`. Only plain apt packages, pip (into its own venv under `/opt/voice-tools/<name>`, wheels only) or global npm. Log: `/var/log/voice-install.log`. |
| Code self-changes | Proposed by the reviewers, go live only after your Telegram yes. |

Not covered: a whole-server outage (there is no outside heartbeat).

## One-tap admin commands

For your admin user (they use sudo themselves; code in `server/lib/voice-safety/agent-cli`):

| Command | Does |
|---|---|
| `agent-status` | Services, live call or not, tasks, usage, failed units. |
| `agent-stop` / `agent-resume` | Create / remove the STOP file. |
| `agent-restart [--dry-run] [--force]` | Restarts voice-caller/watcher/tasks; refuses during a live call or running tasks unless `--force`. |
| `agent-journal [--sys]` | Today's memory journal (or the systemd journal). |
| `agent-usage` | The usage meter. |
| `agent-logs [hours]` | Warnings and errors with secrets redacted. |

Safe deploys: `server/deploy.sh agent|watcher|runner` backs up the old file, copies the new one and restarts only that part, and refuses if a call is live (its LiveKit room exists) or, for the runner, if tasks are running.
