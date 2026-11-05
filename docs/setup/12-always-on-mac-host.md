# 12. Running the server parts on an always-on Mac (instead of Oracle)

**Read this first:** the original assistant ran on a Linux server. Nothing on this page was tested on a Mac host. Each point below says whether it is a **fact from the original build** or an **Assumption**. Expect to fix things.

## What carries over unchanged (fact)

- The **Mac-side parts** (`mac/bin/`, the iMessage listener, `mac-run`, the two app wrappers and their permissions, the separate Apple ID) are the same.
- Linphone, Gemini, Claude Code login, Telegram and the Shortcuts work the same way; they only need the host to be reachable.
- The Python code is plain Python 3 plus the LiveKit Agents SDK.

## What changes

| Linux piece | Mac replacement | Status |
|---|---|---|
| Docker Engine (LiveKit, livekit-sip, Redis) | Docker Desktop or OrbStack | **Assumption.** The compose file uses `network_mode: host`. On macOS, host networking inside Docker Desktop/OrbStack behaves differently from Linux; SIP and the RTP range 10000-10100/udp may need explicit `ports:` mappings instead, and livekit-sip must learn the right external IP. Test a call early. |
| systemd services and timers | launchd LaunchDaemons/LaunchAgents | **Assumption.** Each `.service` becomes a plist with `KeepAlive`; each `.timer` becomes `StartInterval` or `StartCalendarInterval`; `.path` units become `WatchPaths`. `OnFailure=` alerts and drop-ins have no direct equivalent: run the alert script from a wrapper. |
| Separate users (`voicecaller`, `claude-helper`, `kamailio`) and groups | macOS users/groups, or one user | **Assumption.** The file permissions (2770 group folders, root-only secrets) assume Linux. On a single-user Mac you lose some of the isolation between the voice agent, the Gemini key and Claude. |
| `ProtectSystem`, `NoNewPrivileges`, `ReadWritePaths` sandboxing | none built in | **Assumption.** The hardening is lost. |
| Kamailio (apt) | Kamailio from Homebrew or built from source | **Assumption.** Not tested. |
| nginx + certbot | nginx + certbot from Homebrew | **Assumption.** You also need ports 80/443 forwarded from your home router to the Mac, or a tunnel. |
| Public IP for RTP | Your home IP + router port forwarding of UDP 10000-10100 | **Assumption.** A home IP that changes will break calls until livekit-sip sees the new one. |
| Tailscale + Apple TV + `mac-route` | Not needed if the server *is* the Mac | **Assumption.** `mac-ssh` would then SSH to `localhost` (set `MAC_LAN_IP` to `127.0.0.1`), or you call the Mac scripts directly. The overlapping-subnet fix is Oracle-specific and not needed. |
| Paths `/srv`, `/usr/local/lib`, `/var/lib`, `/etc/voice-caller`, `/run/...` | Same paths can exist on macOS, but `/run` does not | **Assumption.** Socket paths under `/run/...` must be moved (for example to `/usr/local/var/run/...`) and changed in the code. |

## Things that get easier

- No wake path needed: an always-on Mac never needs the Sleep Proxy or wake leases (set it to never sleep in System Settings > Energy).
- iMessage sending and `mac-run` are local, so they are faster.

## Things that get harder

- Your Mac must never sleep, restart for updates, or lose power, or the phone line goes down.
- Home internet upload speed and router NAT affect call audio.
- The Mac's Claude Code plan usage and the assistant's usage are the same login, as they were in the original.

If you try this, please write down what you had to change, so the next person doesn't have to guess.
