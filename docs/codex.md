# Can SuperClaude run with OpenAI Codex?

Short answer: **the skill and the setup guide work in Codex today. The running assistant itself still uses Claude Code as its worker.** You could swap that worker for Codex, but nobody has built or tested that swap yet.

Researched on 2026-11-05 from OpenAI's official Codex docs (links at the bottom).

## What works in Codex as-is

| Piece | Works in Codex? | Why |
|---|---|---|
| The `superclaude` skill (`skills/superclaude/`) | Yes | Codex skills use the same open [Agent Skills](https://agentskills.io) format as Claude Code: a folder with a `SKILL.md` that has `name` and `description` front matter, plus optional `references/` and `scripts/`. |
| Finding the skill in this repo | Yes | Codex scans `.agents/skills/` from your working folder up to the repo root. This repo ships `.agents/skills/superclaude`, a symlink to `skills/superclaude`, and Codex follows symlinked skill folders. |
| Installing the skill for all your projects | Yes | Copy or symlink `skills/superclaude` into `$HOME/.agents/skills/` (Codex) or `~/.claude/skills/` (Claude Code). |
| Project instructions | Yes | Codex reads `AGENTS.md` before it does any work. This repo has an `AGENTS.md`, and `CLAUDE.md` imports the same file, so both tools follow the same rules. |
| Following the setup docs (SSH into the server, edit files, run `systemctl`, etc.) | Yes | That's ordinary shell and file work, which any coding agent can do. |

## What is Claude-specific today

The live assistant hands real work to **headless Claude Code**. These parts depend on Claude Code features:

| Where | What it uses | Codex equivalent (from the docs) | Status |
|---|---|---|---|
| `server/lib/voice-tasks/task_runner.py` | `claude -p --model … --permission-mode auto`, a pre-started "warm" Claude process, `--strict-mcp-config` | `codex exec "<task>" --sandbox workspace-write`, `--json` for a JSONL event stream, `-o` to save the final message | Not built, not tested |
| `ask_claude` socket (fast answers during a call) | One long-running Claude process in `stream-json` mode | No direct match was found in the docs. Each `codex exec` run is separate; `codex exec resume --last` continues one. | Not built |
| `mac-run` resuming Mac sessions | `claude --resume <id> -p` | `codex exec resume <SESSION_ID> "<instruction>"` | Not built |
| Telegram bot | The Claude Code Telegram channel | None found in the Codex docs | Use another bot bridge (assumption) |
| Usage meter (`voice-usage`) | Claude plan usage | Not researched | Not built |
| Connectors (Gmail, Calendar, Drive …) | Claude Code connectors / MCP servers | Codex supports MCP servers and plugins | Not tested |
| Sign-in | Claude Code login on the server (Pro/Max plan) | `codex login` (ChatGPT plan), or an API key with `printenv OPENAI_API_KEY \| codex login --with-api-key` | — |

The voice (Gemini Live), SIP and LiveKit, iMessage bridge, memory, dashboard and safety net don't care which coding agent you use.

## If you want to try a Codex worker

This is a plan, not something that has been tested:

1. Install Codex CLI on the server for the worker user and run `codex login`.
2. In `task_runner.py`, change the cold-start command from `claude -p …` to `codex exec --sandbox workspace-write --json -o <result file> "<prompt>"`. By default `codex exec` runs read-only, so the sandbox flag is needed for edits.
3. Turn off the warm-spare and `ask_claude` stream features, or rebuild them around `codex exec resume`.
4. Keep the safety rules: confirmed sends only, the kill switch, and timeouts. They live in the runner and don't depend on the model.
5. Run the offline tests, then try one real task.

## Sources
- OpenAI, *Build skills*: https://developers.openai.com/codex/skills
- OpenAI, *Custom instructions with AGENTS.md*: https://developers.openai.com/codex/guides/agents-md
- OpenAI, *Non-interactive mode* (`codex exec`): https://developers.openai.com/codex/noninteractive
- OpenAI, *Authentication*: https://developers.openai.com/codex/auth
