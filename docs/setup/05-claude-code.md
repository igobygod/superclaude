# 5. Claude Code on the server

Claude Code does the real work: emails, research, files, building things, and controlling the Mac. It runs headless (`claude -p`) as a dedicated user, `claude-helper`.

## Why a dedicated user

- The helper has **no sudo** (its services run with `NoNewPrivileges`). It reaches root-only things only through narrow doors: Unix sockets, spool folders, and one sudo rule for the approved installer (`voice-install`).
- Its work folder is `~claude-helper/assistant`, with its own `CLAUDE.md` rules and a `notes/` memory folder. Every task the voice or text side delegates runs there.

## Steps

1. **Install Claude Code** for `claude-helper` (Node.js + the `claude` CLI).
2. **Sign in once with your Claude subscription** as that user: open a shell as `claude-helper`, run `claude`, and complete the sign-in in the browser.
   Why a subscription and not an API key: the original ran everything on a **Max** plan login, with no API key, so heavy use costs a flat fee. A **Pro** plan should also work but hits its limits much sooner. Assumption: the exact sign-in command (`claude` then `/login`, or `claude setup-token`) isn't recorded in the sources; use whichever your Claude Code version offers.
   The plan is shared with any Claude Code you use on your Mac. The usage meter (see [dashboard-usage-safety](../how-it-works/dashboard-usage-safety.md)) reads the same login.
3. **Connect the Claude connectors** you want (for example Gmail and Google Calendar) in your Claude account settings, so that `claude -p` on the server can use them.
   Why: the task runner gives Gmail **send** tools to a task only when you confirmed the send. Everything else uses whatever connectors your account has.
   `voice-capabilities.timer` writes the real list of connectors, skills and Mac helpers to `/var/lib/voice-tasks/capabilities.md` every day at 05:15 and at boot, so the agent never claims "Claude can't do that" when it can.
4. **Write the helper's `CLAUDE.md`** in `~claude-helper/assistant`. The original had sections named Phone calls, Memory and log, Learning skills, Self-learning, Your memory, Installing tools, and "use the owner's Claude limit carefully". The repo ships skills for the helper in `skills/`.
5. **Test headless mode** as `claude-helper`:
   ```
   cd ~/assistant && claude -p --model sonnet "say hi"
   ```
   The task runner uses `claude -p --model sonnet|opus --permission-mode auto` (see [task-delegation](../how-it-works/task-delegation.md)).

## Telegram channel (optional but recommended)

The original also ran an interactive Claude Code session for `claude-helper` with the **Telegram channel** (Claude Code's Telegram plugin), inside `tmux`, under its own systemd service. You message a Telegram bot and that Claude session answers.

Why: Telegram is the fallback when the Mac is asleep, and the place where alerts, call notes, review notes and install approvals arrive.

1. Create a bot with Telegram's BotFather and keep the bot's secret only in the plugin's own config file under the helper's Claude folder (`channels/telegram/.env`). Limit access to an allowlist of one account: yours.
2. Put the same bot secret and your chat id in `/etc/voice-caller/secrets.env` as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, so alerts and call notes can be sent without Claude.
3. Assumption: the helper's own service and launcher script are **not** in this repo; you need a small systemd unit that starts `claude` with the Telegram channel in a `tmux` session as `claude-helper`.

See [10-telegram-nginx-https.md](10-telegram-nginx-https.md) for the rest.

## Optional: Claude API key for email triage

`voice-watcher` uses a Claude **API** key (`ANTHROPIC_API_KEY`, Haiku model) to decide whether an email is urgent enough to call you. It needs a separate email sorter that drops kept emails into the JSONL file named by `EMAIL_QUEUE` (default `/var/lib/voice-email/kept-for-caller.jsonl`, one JSON email per line, readable by the `voicecaller` group); that sorter is **not** part of this repo. Leave the key empty to skip email calls.
