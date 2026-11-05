# Instructions for coding agents (Codex, Claude Code, others)

This repo is SuperClaude, a self-hosted always-on personal assistant. To install, debug or extend it, use the `superclaude` skill in `skills/superclaude/` (Codex finds it through `.agents/skills/`).

Rules:
- Never commit secrets, real phone numbers, emails, IPs, hostnames, Apple IDs or account IDs. Use the placeholders from `config/superclaude.env.example`.
- New settings are env vars read with a safe default. Document each one in `config/superclaude.env.example`.
- Keep the safety guards (reply guard, stall watch, claim guard, read-back before send, ask-first list).
- Run the offline tests before you call a change done: `server/voice-caller/test_features.py`, `server/lib/voice-memory/test_voice_memory.py`, `server/lib/voice-notify/test_vn.py`. Some of them need the server's Python packages (LiveKit) installed.
- Add every new real bug to `docs/troubleshooting.md` (symptom, root cause, fix, how to detect it).
