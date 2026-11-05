# Troubleshooting

Every row below is a real bug found while building the original assistant, with names and times removed. Format: **symptom | root cause | fix | how to detect it again**.

## First checks (read-only, in this order)

```
agent-status                                   # services, live call?, tasks, usage, failed units
agent-logs 2                                   # warnings/errors from the last 2 h, secrets redacted
agent-journal                                  # today's memory journal
sudo tail -n 20 /var/lib/voicecaller/calls.jsonl          # recent call events
sudo grep -c '"watchdog"' /var/lib/voicecaller/calls.jsonl
sudo journalctl -u voice-caller --since "-30min" | grep -E "turn |input |watchdog|ERROR|Traceback"
sudo journalctl -u voice-notify --since "-1h" | grep -E "timing|brain failed|ERROR"; voice-gemini-status
voice-usage status; voice-questions list --open
sudo kamcmd -s unix:/run/voice-sip-relay/kamailio_ctl uac.reg_info l_uuid <SERVER_SIP_USER>   # flags 20 = online
sudo docker logs voice-caller-sip-1 2>&1 | grep "using codecs" | tail -1
sudo journalctl -u voice-sip-relay | grep RELAY | tail
mac-ssh "pgrep -fl imessage-agent; tail -n 20 ~/.imessage-agent/*.log"
```
If `/var/lib/voice-tasks/STOP` exists, the kill switch is on. Reviewer output: `voice-memory lessons` and `/var/lib/voice-memory/pipeline-issues.md`.

## Debug recipe: "it ghosted me / bugged out / was slow"

1. `agent-status`: no failed units? Not in STOP?
2. Find the call id in `calls.jsonl` (newest `in-...` for inbound, `call-...` for outbound). Read its `turn <id>` and `input <id>` lines in `journalctl -u voice-caller`. Count `watchdog` events and their causes.
3. Silence while the phone was still sending audio -> stuck turn or deaf input (StallWatch). Narrowband codec in the sip logs -> mis-hearings.
4. Slow -> `voice-gemini-status` (text) or time to first audio (voice baseline about 1.0 s), `voice-usage status`, Gemini 429/503 cooldowns.
5. Said something false -> look for `false claim` events and the reviewer's grade (`voice-memory lessons`).
6. Fix the server copy, run the offline tests, deploy with `deploy.sh` when no call is live, and write the finding down.

## Safe deploy rules

1. Never restart voice-caller, voice-watcher, voice-tasks or the containers during a live call (a call is live while its LiveKit room exists). Use `server/deploy.sh agent|watcher|runner` or `agent-restart --dry-run` first.
2. Back up a file before editing it.
3. Run the offline tests first: `server/voice-caller/test_features.py`, `server/lib/voice-memory/test_voice_memory.py` (run from `/tmp`), `server/lib/voice-notify/test_vn.py`. Never weaken a test.
4. systemd: change drop-ins, then `daemon-reload`; only restart if needed. Voice knobs go in `voice-caller.service.d/model.conf`.
5. nginx: `sudo nginx -t` before every reload; then check your other sites still answer.
6. Never test by calling a real phone from an automated worker; use empty-room smoke tests.
7. Never print secrets. Never name a top-level helper `cli` in `agent.py` (it shadowed LiveKit's `cli` and caused a 40 s crash loop).
8. Mac: never rebuild or re-sign `ImsgAgent.app` or `MacRunWorker.app`. Restart the listener with `pkill -f bin/imessage-agent`.
9. After a Docker/SIP restart, check `/var/lib/voicecaller/trunk_id`.

## Texting / iMessage

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| Your own text echoed back as a grey bubble; a "Yes" ran twice | Apple self-chat duplication: the Mac sent as your own Apple ID to your own number; `chat.db` stores each self text as two rows, and both were forwarded | De-duplicate rows; the real fix is a **separate Apple ID** for the agent | One row per message in `chat.db`; `sent.log` has no texts from you; a round trip shows 1 out, 1 in |
| Listener changes had no effect; a photo arrived as text only | `launchctl kickstart -k` killed only the app wrapper; the orphaned Python kept the lock and kept running for hours; new copies exited at once | The listener now reads its `pid` file, stops the stale copy and waits for the lock; restart with `pkill -f bin/imessage-agent` | `pgrep -fl imessage-agent` shows one process with a recent start time (`ps -o lstart`) |
| Short replies ("yes", "which?") answered wrongly | Thread history too short, no record of what other parts had sent | Thread memory of 20 messages with times, including texts sent by any part, plus open and recently answered questions | Reviewer lessons; test through the real pipeline |
| A text said "saved your yes" / "draft saved" when nothing happened | The model claimed actions without tool proof; the confirm window had expired | Code guard: done/saved/set/sent claims without a successful tool result become "On it, sir." and are delegated | `journalctl -u voice-notify`; the text reviewer flags false claims |
| Wrong time of day in replies | Prompts used the server's UTC clock | Local time from `AGENT_TZ` injected into the text and Claude prompts | Ask "what time is it?" |
| A late result looked like a reply to a different message | No link between result and request | Results start with `Re: "<first 50 chars>" —` | Read the thread |
| Reply cut off mid-sentence | Gemini's MAX_TOKENS finish was accepted | Treated as a failure; falls to the Claude path | `timing route=` log lines |
| Same answer stored twice in memory | Two code paths both recorded it | Record once | Reviewer sees duplicate rows |
| "brain failed ... gemini socket: No such file" | `voice-gemini-chat` was restarting or stopped | Brain retries 3 times over 4 s, then Claude (never unanswered) | `systemctl status voice-gemini-chat` |

## Gemini quota / models

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| Texts take about 25 s; frequent Claude fallback | Gemini 429 (quota), 503 (busy), timeouts; one fixed model kept failing; `gemini-2.5-*` gave 404 for new keys | `voice-gemini-chat` orders models by recent speed among those not cooling down (429 -> 15 min or Google's delay, 503/timeout -> 90 s, 404 -> 12 h), 2.5 s per try (8 s with a picture), max 2 tries, shorter prompts, own budget 300/day | `voice-gemini-status [--json]`; `journalctl -u voice-notify \| grep timing` |
| Voice slow to start talking (about 2.5 s) | The code's default native-audio model is slow | `GEMINI_LIVE_MODEL=gemini-3.8-live` in `model.conf` (about 1.0 s) | `systemctl cat voice-caller \| grep GEMINI` |
| Error 1007 from the live model | `gemini-3.8-live` doesn't support affective dialog or a thinking budget | Leave them off; proactive audio also off on purpose | Don't enable |
| Looking at a sent picture fails with 503/429 | Text and vision share the key's quota | Fallback chain to a lighter model; Claude reads images | `look_at_sent_media` log |

## Voice: turn-taking and silence

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| Agent cuts you off / answers half-sentences | End of turn detected too early | END HIGH with SILENCE_MS 300, START LOW, PREFIX 200; prompt: answer a fragment with "go on" | `turn <call> +Ns heard/said` lines |
| Ghosting: no reply after you spoke | No end-of-turn event, or the model dropped its reply | ReplyGuard (2.0 s, forced reply, then "Sorry, say that again?", max 3); new session on session errors (max 2) | `grep '"watchdog"' calls.jsonl` |
| ReplyGuard false alarm: agent repeated itself | The Google plugin reports "user speaking" when the agent starts on its own; late transcripts | Your turn only arms the guard if the agent didn't start speaking after it began; late transcripts within 6 s of agent speech ignored | 0 watchdog events on a healthy call |
| Call went silent for over a minute | Gemini kept you "speaking" on quiet input and never ended the turn | StallWatch stuck-turn rule (15 s speaking, no final transcript, last 2.5 s quiet -> forced reply; reconnect after 5 s) | watchdog `input stalled` / stuck turn; `input <call>` lines every 10 s |
| Gemini stopped hearing you though phone audio kept flowing | Not proven (narrowband audio, no errors logged) | StallWatch deaf-input rule replaces the session: "Sorry, I lost you for a second, go ahead." | Same logs |
| StallWatch reconnected twice for nothing | It fired after the phone hung up | Recovery does nothing once the phone has left the room | No reconnect lines after `ended` |
| Mis-hearings of names and short words | 8 kHz PCMA/PCMU audio; the phone didn't offer G722 | Turn **G722 on** (above PCMA/PCMU) in Linphone; RNNoise was tested and doesn't hurt speech | sip logs must say `G722/8000`; optional raw capture via the flag file `/var/lib/voice-tasks/CAPTURE` (delete the captures afterwards) |
| Late first reply | Slow work on the audio event loop (memory subprocess about 370 ms, SSL CA load, imports) | Subprocess calls moved off the audio loop; imports pre-warmed | Journal timing near call start |
| A call never gets `ended` | The phone kept sending audio until hung up | Session close always logs `ended`; idle check; 30-min inbound cap; watcher marks calls "room gone" | `calls.jsonl` answered without ended + LiveKit room list |
| Inbound rings but nobody answers | Dispatch rule had no agent / agent lacked the inbound branch / 404 = phone app signed out | `sudo voice-inbound-setup`; agent skips dialing when `inbound` is set | `sudo voice-inbound-setup --show` |
| Phone cancels after 1 s (SIP 486) | You hung up or the app had an issue | None | `calls.jsonl` cause |

## Voice: honesty and confirmations

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| "Stop everything" fired on a garbled sentence | Tool triggered on a fragment | Runs only if your last 2 lines ask to stop/cancel everything, or after "Stop all tasks?" + yes | Dashboard shows STOP; `ls /var/lib/voice-tasks/STOP` |
| "I changed it" claims (speed, voice, pronunciation) | Model claimed success with no tool; the speed tool did nothing | Honesty rule + ClaimGuard; `talking_speed` says when it's at the limit; reviewer check 9 is HIGH | `grep "false claim"` |
| An email was sent without a valid confirmation | `owner_confirmed` was trusted from the model | Code check: a read-back question earlier, then a go-ahead in your next lines (waits 1.2 s for the rest of the sentence); same for texts and session messages | Reviewer; task text "confirmed" |
| No read-back, duplicate email, follow-up questions spawning new tasks | Early prompt gaps | Read back, one task per goal, no sends before success wording; only confirmed tasks get send tools | Task `done` json `ok=false` |
| An explicit resend was blocked | The 30-minute duplicate rule was too strict | Task text says you explicitly asked to send it again | Result says "duplicate" |
| The agent read your email address aloud | Prompt | Says "your Gmail" | Reviewer |
| Pronunciation loop ("like this?") and wrong saves | Narrowband audio + endless retries | Try once, then send numbered options to Telegram; `set_pronunciation` needs read-back + yes | `/var/lib/voice-tasks/pron-options.json` |
| Greeting sounded like a different voice | Gemini renders short casual lines in a default-like voice | Pre-recorded greeting clip per voice | `ls /var/lib/voice-tasks/greetings` after changing `GEMINI_VOICE` |
| An "ask" task never got a result | STOP skipped writing the result | STOP-blocked asks always write a "Cancelled" result | `ls queue running done` |
| Mac "close an app" failed | `osascript` isn't allowed in mac-run's safe mode | Your decision: allow it in the Mac's Claude settings, or not | mac-run log "requires approval" |
| Build watch blocked | `Bash(xcodebuild:*)` missing from the Mac's allow list | Allow it in the Mac's Claude settings | Mac `settings.json` allow list |
| "Claude can't log in / can't do that" | No real list of capabilities | Daily `capabilities.md`; prompt says delegate instead of refusing; logins are done by you | `/var/lib/voice-tasks/capabilities.md` |

## Sound and speech

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| Short sound blips | Quick tools started a thinking sound after 0.15 s and cut it soon after | Sounds start after 1.0 s of continuous work, 80 ms fade-out | Listen; journal tool durations |
| Agent never speaks after a speed-up change | Swapping the audio output for a time-stretch stage after start breaks this LiveKit version | `SPEED_UP=off` in `model.conf` (code default is on) | `systemctl cat voice-caller \| grep SPEED_UP` |
| Can't make the voice faster | Gemini Live has no rate setting | Prompt-only pace (about 13% faster at most); no percentages promised | n/a |
| Voice changed unexpectedly | Code default voice vs the drop-in | Set `GEMINI_VOICE` in `model.conf`; matching greeting clip | as above |

## SIP / network / server

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| SIP 488 on outbound calls | Plain RTP offered; Linphone requires encryption | Trunk uses `SIP_MEDIA_ENCRYPT_REQUIRE` (SDES-SRTP) | sip container logs |
| SIP 404 | Linphone app on the phone isn't signed in | Open Linphone | sip logs |
| Outbound calls fail after a container restart | The trunk lives in Redis; data lost or `trunk_id` stale | `call.py --setup-trunk` runs before every voice-caller start; Redis append-only with a volume; health check watches `trunk_id`; recreate inbound with `voice-inbound-setup` | `cat /var/lib/voicecaller/trunk_id`; health alert |
| livekit-sip can't REGISTER | Not supported by livekit-sip | Kamailio relay registers the server account | `kamcmd uac.reg_info` |
| Strangers or spoofed calls reaching the agent | Open relay risk | Relay accepts only your account from Linphone's addresses, else 403; trunk allow-list loopback + your caller id | 403 in the RELAY log |
| Server networking breaks after accepting Tailscale routes | Home LAN and cloud network both `10.0.0.0/24` | `mac-route.service`: only the Mac's /32 via Tailscale's table 52, the rest via main | `ip rule`; other sites still answer |
| Helper can't use sudo | Services run with `NoNewPrivileges` | Sockets and spool folders, plus one sudo rule for `voice-install` | n/a |
| "Read-only file system" inside voice-caller | `ProtectSystem=strict` | `helper-paths.conf` `ReadWritePaths`; otherwise spool to `memory-inbox` | journal |
| Mac unreachable | Mac asleep/off, or its wake lease expired | Apple TV Sleep Proxy wakes it; each login gets a 3-min lease; texts fall back to Telegram | `mac-ssh true` |
| Usage meter stuck or shows ESTIMATE | Helper login expired, or the undocumented endpoint changed | Fallback Haiku call refreshes the login (max once per 30 min) | `voice-usage status --refresh` |
| Claude plan nearly used up | Shared with Mac sessions | Ask first at 90%; warning at 80% | `voice-usage status` |

## Memory / reviewers

| Symptom | Root cause | Fix | Detect |
|---|---|---|---|
| Wrong facts from mis-heard names | Saving from garbled audio | Save with source `said` vs `inferred`; retire bad facts (status, not delete); stale facts get a "still true?" check | `voice-memory recall` |
| `voice-memory journal --source imessage` rejected | Early source list was call/task/mac/note only | Now accepts imessage and telegram | exit code 0 |
| Extras `config.json` overwritten by "turn it on" | A helper Claude rewrote the file with no backup | Keep a backup before config edits; check defaults afterwards | `cat /var/lib/voice-extras/config.json` |
| A draft claimed but not in Gmail; duplicate reminders | Test leftovers | `voice-remind cancel`; check drafts in Gmail | `voice-remind list` |

## Files vanished after a sync

If you sync skill or note files to the server and the server runs a safety scanner, the scanner may quarantine files that *look* like they contain secrets (a word like key or token next to send/upload, or a path into the SSH folder). A two-way sync then deletes them on the other side too. Fix: reword the lines, restore from backup, and run the same checks before syncing.
