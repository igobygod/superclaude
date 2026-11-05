# 1. The server (Oracle Cloud free ARM VM)

The original build runs on an Oracle Cloud "Always Free" ARM virtual machine with Ubuntu. Any always-on Ubuntu machine with a public IP should work the same way.

## Steps

1. **Create an Oracle Cloud account and an Ampere (ARM) VM with Ubuntu.**
   Why: the assistant must be reachable 24/7 so it can ring you and answer texts, and the free ARM shape costs nothing.
2. **Note the public IP and pick a host name.** Put the host name in `PUBLIC_HOST` (for example `voice.example.com`).
   Why: the iPhone shortcuts and the dashboard reach the server over HTTPS at that name, and Let's Encrypt needs a name, not an IP.
   Any DNS name that points at your IP works.
3. **Create the service users and groups** (as root):
   - users: `voicecaller` (runs the voice agent and the Gemini key proxies), `claude-helper` (runs Claude Code and the task runner), `kamailio` (created by the Kamailio package);
   - groups: `voicetasks` (shared task queue and sockets: add `voicecaller` and `claude-helper`), `macaccess` (may use the Mac SSH key: add `claude-helper` and your admin user).
   Why: each part only gets the files it needs. The helper that runs Claude has no `sudo` at all; the Gemini key is held by `voicecaller` and only shared through a socket.
4. **Open the network ports.** Only these are needed for the voice parts:

   | Port | Protocol | Why |
   |---|---|---|
   | 10000-10100 | UDP | Call audio (RTP/SRTP) between your phone and livekit-sip. |
   | 80 | TCP | Let's Encrypt certificate checks and the redirect to HTTPS. |
   | 443 | TCP | HTTPS for the Shortcuts endpoints and the dashboard. |
   | 22 | TCP | Your own SSH admin access (Oracle opens it by default). |

   On the VM the original opened the UDP range in iptables and saved it with `netfilter-persistent`:
   ```
   sudo iptables -I INPUT -p udp --dport 10000:10100 -j ACCEPT
   sudo netfilter-persistent save
   ```
   Assumption: on a fresh Oracle VM you must also add the same UDP range (and 80/443) as ingress rules in the VCN security list in the Oracle web console; the sources only record the iptables change.

   **Not needed:** SIP port 5060 is *not* opened to the internet. livekit-sip is reached only from the local relay (loopback) and its own outgoing connections. The Kamailio relay keeps an *outgoing* TCP connection to Linphone (source port 5070), and Linphone sends calls back over that same connection, so no inbound port is needed for it either. LiveKit's own ports (7880, 6379 for Redis) are bound to `127.0.0.1` only.
5. **Install base packages:** Docker with the compose plugin, Python 3 with `venv`, `ffmpeg`, nginx, certbot, Kamailio (the original used Kamailio 5.7 from Ubuntu's packages) and `netfilter-persistent`.
   Why: Docker runs LiveKit; Python runs every service; ffmpeg converts audio; nginx and certbot give HTTPS; Kamailio relays inbound calls.

## Watch out: overlapping private subnets

Oracle's default VCN uses `10.0.0.0/24`. Many home routers use the same range. If yours does, read the subnet fix in [06-tailscale-apple-tv-mac.md](06-tailscale-apple-tv-mac.md) before you turn on Tailscale routes, or the server can lose its own network.

## Check

- `ip addr` shows the VM's private IP; `curl -4 ifconfig.me` shows the public IP.
- `sudo iptables -L INPUT -n | grep 10000:10100` shows the UDP rule.
