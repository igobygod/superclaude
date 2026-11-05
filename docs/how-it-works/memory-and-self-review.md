# Memory and self-review

## Memory (`voice-memory`)

Code: `server/lib/voice-memory/voice_memory.py`, CLI `voice-memory`. Data: `/var/lib/voice-memory/`, all plain JSON and Markdown.

| What | File |
|---|---|
| Facts about you (the canonical profile): each has a source (`said`, `email`, `inferred`), a confidence, optional expiry, optional private flag | `facts.json` |
| Journal of every call, task, Mac session, note, iMessage and Telegram chat | `journal.jsonl` + `journal/YYYY-MM.md` |
| Promises, goals, people, projects, proposals, questions, mistakes | `promises.json`, `goals.json`, `people.json`, `projects/`, ... |
| Rules learned from mistakes | `rules.md` |
| Lessons for the voice/text brains | `lessons.json` -> `/var/lib/voice-tasks/voice-lessons.md` |
| Archive (nothing is ever deleted) | `archive.jsonl` |

### Generated views

- `/var/lib/voice-tasks/profile.md`: **public** facts only, for Gemini.
- The helper's `notes/USER.md`: all facts including a "Private (Claude only)" section, up to 3000 chars.
- If you edit either view, `voice-memory-sync.path` imports the change within about a second.

**Private** facts (health, money, ID numbers and similar; found by a pattern check plus a nightly model check) never go to Gemini. Prompts only get a "PRIVATE:" marker, and the voice says "I have that, want me to have Claude handle it?".

### How the brains use it

- Every call and text prompt gets `voice-memory context`.
- Tools `recall "<question>"` (searches all history; uses a Haiku helper socket, about 2-4 s, with a plain-text search fallback) and `remember --fact ... --source said|email|inferred`.
- Facts heard on a call are saved as `said`, so mis-heard names can be spotted. Expired facts become "stale" and get a "still true?" check.
- Services without write access (the sandboxed voice agent) drop entries into `/var/lib/voice-tasks/memory-inbox`.
- Mac: the `voice-journal-hook` journals finished Mac Claude Code sessions through a restricted key (`voice-memory mac-ingest`).

### Scheduled jobs

- **Nightly 03:05:** journal catch-up from calls and tasks, Haiku extraction (summary, promises, people, proposed facts), de-duplicate (newest wins), expiry, mistakes -> `rules.md`, behaviour proposals, at most **one question a day** for you.
- **Weekly (Sunday 18:30):** a review sent to Telegram (private items are counted, not shown).

## Self-review (the agent grades itself)

`voice-memory-review.timer` runs every minute (`voice-memory review-pending`).

### Calls
Each answered call longer than 8 s is reviewed **once**, 2 minutes after it ends, by Claude Sonnet. Evidence: the call's events in `calls.jsonl`, the voice-caller journal turn log (heard/said/tools/input/watchdog), the transcript, and task results. Checklist:
1. answered every turn;
2. delegated instead of refusing;
3. didn't act on a mis-hearing;
4. read back before sending;
5. facts and names right;
6. length and speed;
7. followed style requests;
8. didn't over-save memory;
9. claimed a change without a tool (graded HIGH).

### Texts
iMessage/shortcut chats (from `vq.db`) and Telegram chats (from the helper's session logs) are reviewed once, after 15 minutes of quiet plus 2 minutes.

### What happens with the findings

- **Safe rules apply automatically** to `voice-lessons.md` (max 25, newest first, tagged `[call]` or `[text]`), with a Telegram note you can answer "undo L..." to.
- **Anything about safety, privacy, sending, payments, deleting or logins, and all code changes** become **proposals** that need your "approve P...".
- Problems in the pipeline itself go to `pipeline-issues.md`.
- Commands: `voice-memory lessons`, `voice-memory lessons undo|approve|reject ID`.

Learning never relaxes ask-first rules, privacy tags or send confirmations.
