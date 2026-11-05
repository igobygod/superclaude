# Setup overview

This guide builds a personal assistant you can **phone**, **text on iMessage**, **message on Telegram**, and **trigger from iPhone Shortcuts**. A fast Gemini "front desk" answers right away. Real work goes to Claude Code, which runs without a screen on your own machine.

## What you are building

```
iPhone (Linphone app) --SIP--> Linphone servers --> your server: Kamailio relay -> livekit-sip -> LiveKit -> agent.py (Gemini Live)
iPhone (Messages)     --iMessage--> your Mac (signed in as the agent's Apple ID) --SSH--> server: voice-notify -> Gemini text brain -> Claude
iPhone (Shortcuts)    --HTTPS--> nginx on the server -> small local services
Telegram              --> Claude Code Telegram channel on the server
server --Tailscale--> Apple TV (subnet router, wakes the Mac) --> Mac (iMessage, mac-run, screen look)
```

## Pick where the "server" runs

| Option | What it is | Status in this project |
|---|---|---|
| **A. Oracle Cloud free ARM VM (Ubuntu)** | A free Linux machine in the cloud, always on. | This is what the original build ran on and what these docs verify. |
| **B. An always-on Mac** | Run the server parts on a Mac that never sleeps. | Not verified. See [12-always-on-mac-host.md](12-always-on-mac-host.md); most of it is marked as an assumption. |

A Mac is still needed for **iMessage** and **Mac control** in both options, because only macOS runs Messages. If you skip iMessage and Mac control, phone calls and Telegram work with the server alone.

## Order of steps (and why this order)

1. [01-server-oracle.md](01-server-oracle.md): get the machine and open the network ports. Everything else runs on it.
2. [02-docker-livekit-sip.md](02-docker-livekit-sip.md): LiveKit and livekit-sip carry the call audio. Calls cannot work without them.
3. [03-linphone.md](03-linphone.md): two free SIP accounts so the server can ring your iPhone and you can ring the server.
4. [04-gemini.md](04-gemini.md): the Gemini API key that powers the voice and the fast text replies.
5. [05-claude-code.md](05-claude-code.md): Claude Code logged in on the server for a dedicated user. This is the "brain" that does real work.
6. [06-tailscale-apple-tv-mac.md](06-tailscale-apple-tv-mac.md): a private network path from the server to your home Mac, which can also wake it.
7. [07-mac.md](07-mac.md): Mac permissions, keys and background helpers.
8. [08-apple-id-imessage.md](08-apple-id-imessage.md): a separate Apple ID for the agent, so texts don't echo.
9. [09-shortcuts.md](09-shortcuts.md): iPhone buttons (Call me, Ask Claude, Wake Claude, Text Claude, Force Wake).
10. [10-telegram-nginx-https.md](10-telegram-nginx-https.md): HTTPS for the shortcuts and dashboard, plus the Telegram bot.
11. [11-systemd-services.md](11-systemd-services.md): install and start every service and timer.

Steps 6 to 9 are only needed for iMessage, Shortcuts that wake the Mac, and Mac control.

## Settings

Personal values (your name, email, phone, host name, Mac user name, home subnet, time zone) are read from environment variables such as `OWNER_NAME`, `OWNER_EMAIL`, `OWNER_PHONE`, `OWNER_HANDLES`, `PUBLIC_HOST`, `MAC_USER`, `MAC_LAN_IP`, `HOME_SUBNET` and `AGENT_TZ` (the Linphone user names are `LINPHONE_PHONE_USER` / `LINPHONE_SERVER_USER` in the secrets file). The full list, with examples, is in `config/superclaude.env.example`. Secrets (API keys, passwords) go only in root-only files on the server (`/etc/voice-caller/secrets.env` and `/etc/voice-caller/livekit.env`, mode 640, owner `root:voicecaller`). Never commit them.

## What is free and what isn't

| Piece | Cost |
|---|---|
| Oracle Cloud "Always Free" ARM VM | Free (Oracle's free tier) |
| Docker, LiveKit, livekit-sip, Redis, Kamailio, nginx, Let's Encrypt | Free, open source |
| Linphone app and two `sip.linphone.org` accounts | Free |
| Gemini API (voice + text + video helpers) | Free tier, with daily limits (see [04-gemini.md](04-gemini.md)) |
| Tailscale | Free personal plan |
| Telegram bot | Free |
| Claude Code | Needs a paid Claude plan (the original used a Max plan; Pro may work with lower limits) |
| Claude API key for email triage (optional) | Pay per use; the original build described it as "pennies" |
| Apple TV (optional, used as the always-on home router and wake helper) | Hardware you may already own |
| Second Apple ID for the agent | Free |
