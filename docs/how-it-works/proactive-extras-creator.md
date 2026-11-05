# Proactive extras, creator tools and media

All of these are **optional**. They run as `claude-helper`; any Claude work goes through the task queue; proactive items respect quiet hours and at most 3 proactive calls a day.

## voice-extras (scheduler)

`voice-extras-tick.timer` runs `server/lib/voice-extras/tick.py` every minute: due reminders plus scheduled jobs from `/var/lib/voice-extras/config.json` (defaults are in `common.py`; times are in `AGENT_TZ`).

| Extra | Default | What it does | CLI |
|---|---|---|---|
| Reminders | on | "remind me at 5" -> text (or Telegram) at that time. WHEN: `+30m`, `+2h`, `17:00`, `tomorrow 09:00`, a date. | `voice-remind add WHEN "text" [--telegram]`, `list`, `cancel ID` |
| Morning briefing | 08:00 Mon-Fri | Claude gathers the day; Telegram gets the full text, a call gets the short spoken part. | `voice-briefing-now` |
| Mail watch | 09:00 | Scans Gmail (read-only) for promises you made, people waiting on a reply, deadlines and deliveries. Drafts only, never sends. | `voice-mailwatch-now` |
| Patch radar | every 6 h (reviews: every 3 h) | Steam news for the games you list, and App Store reviews for apps you list (free feeds, no key). First run sets a baseline; then Telegram on new items. | |
| Build watch | off | Runs an Xcode build on the Mac through mac-run (`xcodebuild`); calls only on failure. Needs `Bash(xcodebuild:*)` allowed in the Mac's Claude settings. | `voice-buildwatch-now` |
| Gym log | | Sets, protein, rest timer. | `voice-gym set EXERCISE WEIGHT REPS`, `protein G`, `rest [S]`, `today`, `undo` |
| Clip/idea vault | | Save and search ideas. | `voice-vault add "idea" [--tag X]`, `list`, `search`, `random` |
| Job-search digest | 07:20, only if `JOB_SEARCH_DIR` is set | Read-only: reads a job-search folder on the Mac through mac-run, summarises it into the briefing, and asks you (as `jobsearch:*` questions) what that system is waiting on. | `voice-scout-now` |
| Job answers | every 5 min | When you answer a `jobsearch:*` question, finishes that application using the existing job-search process. | |
| Apply to a link | | You ask to apply to a posting; uses the same process, with a duplicate check. | `voice-apply LINK [notes]` |

Note from the build: a helper Claude once overwrote `config.json` when asked to "turn it on". Keep a backup before editing it.

## Creator tools (optional)

Code: `server/lib/voice-creator/`. Channels to watch: `CREATOR_CHANNELS` (see `config/superclaude.env.example`).

- **Upload monitor** (every 10 min): reads your channels' public YouTube RSS. Videos first seen within 2 h of upload are tracked; views are saved at 1 h, 24 h and 7 days and compared with the median of your earlier videos (needs 3+). At 2x or more: "pin a comment?". At 0.5x or less at 24 h / 7 d: "want 3 new thumbnail/title options?". Suggestions only, by `voice-notify --level info`. RSS has no click-through rate.
- **Weekly report** (Sunday 18:00): uploads this week vs usual, what to make next, best posting slots.
- **`voice-video-review FILE [--best|--check|-q ...]`**: shrinks the video to 480p, uploads it to Gemini through the `voice-gemini` socket, asks, deletes the upload.
- **`voice-video-edit trim|silence|shorts|preview`**: trim; cut silences (needs `auto-editor`); make a 1080x1920 short with optional Gemini captions burned in (`--fit crop|blur`); send a preview to Telegram. Heavy jobs go to the Mac via mac-run.

## Media inbox

- Shared inbox: `/var/lib/voice-media/inbox/<date>/` + `index.jsonl`, from iMessage, Telegram and the Ask Claude shortcut.
- `voice-media latest|save|keep|prune|telegram-sync`.
- Kept 7 days unless marked keep or named in the journal (`voice-media-prune.timer`, 04:10).
- On a call, `look_at_sent_media` lets the agent look at what you just sent (vision model `gemini-3.8-flash`, with a lighter fallback; Claude reads images if Gemini is busy).
