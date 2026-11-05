# 2. Docker: LiveKit + livekit-sip + Redis

LiveKit is an open-source real-time audio server. `livekit-sip` turns a normal SIP phone call into a LiveKit "room" that the Python agent can join. Redis stores LiveKit's state (SIP trunks and dispatch rules).

## Files

`server/voice-caller/` installs to `/srv/voice-caller/`:

| File | What it does |
|---|---|
| `docker-compose.yml` | Three containers on the host network: `redis` (127.0.0.1:6379, `--appendonly yes`, volume `redis-data`), `livekit` (`livekit/livekit-server`), `sip` (`livekit/sip`). Logs capped at 10 MB x 3. |
| `livekit.yaml` | LiveKit on `127.0.0.1:7880` only, Redis at 127.0.0.1:6379. |
| `sip.yaml` | livekit-sip: `sip_port: 5060`, `rtp_port: 10000-10100`, `use_external_ip: true`. |

## Steps

1. **Copy `server/voice-caller/` to `/srv/voice-caller/`.**
2. **Create the LiveKit API key pair:**
   ```
   docker run --rm livekit/livekit-server generate-keys
   ```
   Put the pair in the `keys:` section of `livekit.yaml` and the `api_key`/`api_secret` of `sip.yaml`, and also in `/etc/voice-caller/livekit.env` as `LIVEKIT_URL=ws://127.0.0.1:7880`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (root:voicecaller, mode 640).
   Why: the agent, the SIP bridge and the server must share the same key, and the key must never be in Git.
   Assumption: the exact variable names in `livekit.env` follow the LiveKit Python SDK defaults (`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`); the sources only name the file.
3. **Start the stack:**
   ```
   cd /srv/voice-caller && sudo docker compose up -d
   ```
   The compose project is named `voice-caller`, so the containers are `voice-caller-redis-1`, `voice-caller-livekit-1`, `voice-caller-sip-1`.
4. **Create the Python venv** for the agent: `python3 -m venv /srv/voice-caller/venv`, then install the LiveKit Agents framework with the Google (Gemini) plugin, and `pyrnnoise` for noise removal.
   Assumption: there is no pinned `requirements.txt` in this repo; install the current `livekit-agents`, `livekit-plugins-google` and `livekit-api` packages and fix any import error you see.
5. **Outbound trunk.** You don't create it by hand: `voice-caller.service` runs `call.py --setup-trunk` before every start (see [11-systemd-services.md](11-systemd-services.md)). It (re)creates the outbound trunk named `linphone` and writes its id to `/var/lib/voicecaller/trunk_id`.
   Why: the trunk lives in Redis. If Redis data is ever lost, the next service start puts it back.
6. **Inbound trunk and dispatch rule** (only if you want to call the agent): after [03-linphone.md](03-linphone.md), run `inbound_setup.py` as root (the original wraps it as `sudo voice-inbound-setup`). It creates an inbound trunk and a dispatch rule, both named `linphone-in`, that start the agent `pa-caller`. Options: `--show` prints them; `--agent ""` turns inbound answering off (calls ring unanswered).

## Why the trunk forces encryption

Linphone's servers refuse plain audio. The outbound trunk uses SDES-SRTP with `SIP_MEDIA_ENCRYPT_REQUIRE` (setting `LINPHONE_MEDIA_ENCRYPTION`, default `REQUIRE`) and TCP transport (`LINPHONE_TRANSPORT`, default `TCP`). Without encryption the phone answers with SIP 488.

## Check

- `sudo docker ps` shows 3 containers running.
- `cat /var/lib/voicecaller/trunk_id` prints an id after voice-caller has started once.
- During a call: `sudo docker logs voice-caller-sip-1 2>&1 | grep "using codecs" | tail -1` shows which codec was picked (you want `G722/8000`).

## Never do this during a call

Restarting the containers, the relay or `voice-caller` while a call is live drops the call. A call is live while its LiveKit room exists. `server/deploy.sh` checks this for you.
