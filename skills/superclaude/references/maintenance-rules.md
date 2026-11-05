# Maintenance rules (learned the hard way)

## Safe deploy
1. **No restarts during a live call.** Don't restart `voice-caller`, `voice-watcher`, `voice-tasks`, the Docker containers or the SIP relay while a call is live. A call is live while its LiveKit room exists. Check `agent-status` first.
2. Deploy with `deploy.sh agent|watcher|runner`, which refuses during live calls or running tasks. Use `agent-restart --dry-run` before `agent-restart`, and `--force` only on purpose.
3. **Back up before editing** any server file: `sudo cp FILE /root/FILE.bak-<topic>-<date>`.
4. **Run the offline tests first, and never weaken a test.**
   - `python3 /srv/voice-caller/test_features.py`
   - `cd /tmp && python3 /usr/local/lib/voice-memory/test_voice_memory.py`
   - `python3 /usr/local/lib/voice-notify/test_vn.py`
5. **systemd:** prefer drop-ins in `<unit>.service.d/`, then `daemon-reload`. Voice settings (model, voice, silence timing) live in `voice-caller.service.d/model.conf`.
6. **nginx:** only add locations to the SuperClaude site. Run `nginx -t` before every reload, and check afterwards that the user's other sites still respond.
7. **Keys:** never print them. Write them into the root-only env files without echoing them back.
8. **Mac listener:** restart it with `pkill -f bin/imessage-agent` (the script takes over stale instances), not only `launchctl kickstart`. Afterwards, confirm exactly one process with a fresh start time. A stale listener once ran for hours and hid every fix.
9. **Docker/SIP:** restart only with no live call. The outbound trunk is recreated by `voice-caller`'s ExecStartPre; check `/var/lib/voicecaller/trunk_id` afterwards.

## Settings that must stay
- Keep `SPEED_UP=off` in model.conf. Swapping the audio output stage after start stops the agent from ever speaking.
- Keep a `GEMINI_LIVE_MODEL` drop-in: the code default is an older, slower model. When you change `GEMINI_VOICE`, generate a matching greeting clip.
- Leave affective dialog and proactive audio off on the live model. They were rejected, or let the model choose not to answer.
- Linphone on the phone: SRTP, with G722 enabled above PCMU/PCMA. Narrowband audio causes mis-hearings.

## Free first
Explain any paid option and its cost, and wait for a yes.
