# Inbound call: you ring the agent

## Step by step

1. **You tap the "Claude" contact in Linphone.** Its address is the server's Linphone account, `sip:<SERVER_SIP_USER>@sip.linphone.org`.
2. **Linphone's servers look up that account.** It is online because the Kamailio relay (`voice-sip-relay.service`) keeps it registered: it registers over **TCP** from local port 5070, refreshing every 300 s.
   Why a relay: livekit-sip cannot register with a SIP provider. Because the relay keeps one outgoing TCP connection open, Linphone sends the call back down that same connection, so no inbound firewall port is needed.
3. **The relay checks the caller.** It only accepts an INVITE that is **from your phone account** (`LINPHONE_PHONE_USER`) **and** arrives from Linphone's own server addresses (resolved when the relay starts). Everything else gets **403**.
   Why: without this, anyone on the internet could call your agent and use your Claude.
4. **The relay hands the call to livekit-sip** on `127.0.0.1:5060`. Later messages in the same call flow back the same way (loopback -> Linphone over TCP, and Linphone -> livekit-sip).
5. **livekit-sip matches the inbound trunk `linphone-in`.** That trunk only allows `127.0.0.1` and your caller id, and requires SRTP.
6. **The dispatch rule `linphone-in` starts the agent** `pa-caller` in a new room named `in-...`, with metadata `{"inbound": true, "owner_initiated": true}`. Your phone is already in the room as participant `sip_<OWNER_SIP_USER>`. livekit-sip answers the SIP call once the agent subscribes to its audio.
7. **The agent skips dialing** (because `inbound` is set) and plays a **pre-recorded greeting** in its own voice: `greetings/inbound-<Voice>.ogg` ("Yes, sir? How may I help?"). If the clip is missing, the model says the line.
   Why a clip: Gemini sometimes rendered a short casual greeting in a different-sounding voice, and a clip is also instant.
8. **Talk** as in [during-a-call](during-a-call.md). Media: SRTP between the phone and livekit-sip on UDP 10000-10100. G722 (HD) is used when the phone offers it.
9. **Limits:** inbound calls are capped at 30 minutes (`INBOUND_MAX_MINUTES`). Silence rules also apply (240 s quiet -> "Are you still there?" -> hang up 45 s later).

## Turning it on and off

- On: `sudo voice-inbound-setup` (dispatch to `pa-caller`). `--show` prints the trunk and rule.
- Off: `sudo voice-inbound-setup --agent ""` (rings, no answer) or stop `voice-sip-relay`.

## Checks

- Registration: `sudo kamcmd -s unix:/run/voice-sip-relay/kamailio_ctl uac.reg_info l_uuid <SERVER_SIP_USER>` (flags 20 = online).
- Relay decisions: `sudo journalctl -u voice-sip-relay | grep RELAY | tail`.
