# 6. Tailscale + Apple TV: reaching (and waking) the home Mac

The server needs to SSH into your home Mac to send iMessages, run Claude there, and look at the screen. The Mac sits behind your home router and often sleeps. This step solves both.

## The path

```
server --Tailscale--> Apple TV at home (Tailscale subnet router) --home LAN--> Mac (MAC_LAN_IP, port 22)
```

Why an Apple TV and not Tailscale on the Mac:
- The Apple TV is always on, so the route to your home network always exists.
- An Apple TV on the home network acts as a **Bonjour Sleep Proxy**. When a connection arrives for a sleeping Mac, the Sleep Proxy wakes it. In the original build a sleeping Mac (lid closed, on power) woke on the SSH connect and sent an iMessage in about 2 s.
- `server/bin/mac-ssh` waits up to about 2 minutes for a sleeping Mac to answer (6 tries with a ping in between), then gives up with exit code 75.

## Steps

1. **Install Tailscale on the server** and sign in to your tailnet. Turn on route acceptance:
   ```
   sudo tailscale up --accept-routes
   ```
   Don't run this until you have read "Overlapping subnets" below if your home and cloud ranges match.
2. **Install Tailscale on the Apple TV** (App Store app), sign in to the same tailnet, and set it to **advertise your home subnet** (for example `HOME_SUBNET=10.0.0.0/24`). Then **approve the route** in the Tailscale admin console.
   Why: this is what lets the server reach the Mac's normal home IP.
3. **Give the Mac a fixed home IP** with a **DHCP reservation** on your home router, and put it in `MAC_LAN_IP`.
   Why: everything (routes, SSH host key, the server's settings) points at that address. The original Mac had a DHCP address, which was a known risk.
4. **Install `mac-route.service`** if your ranges overlap (see below), with `/etc/mac-helpers/route.env` containing `MAC_LAN_IP=...` and `HOME_SUBNET=...`.
5. Optional: Tailscale on the Mac itself is not required for this path.

## Overlapping subnets (important on Oracle)

Oracle's default cloud network is `10.0.0.0/24`. If your home LAN is also `10.0.0.0/24`, accepting the Apple TV's route would send the server's *own* cloud traffic into Tailscale and break its websites and networking.

`server/systemd/mac-route.service` fixes this with two policy-routing rules:

| Priority | Rule | Effect |
|---|---|---|
| 5200 | `to ${MAC_LAN_IP}/32 lookup 52` | Only the Mac's single address goes through Tailscale (table 52 is Tailscale's route table). |
| 5260 | `to ${HOME_SUBNET} lookup main` | The rest of that range stays on the cloud network. |

Install it, then `sudo systemctl enable --now mac-route`. If your home range is different from the cloud range, you don't need it.

## Check

- `ip rule` shows the 5200 and 5260 rules.
- `ping MAC_LAN_IP` from the server answers (through the Apple TV).
- Your other websites on the server still answer normally.
- After [07-mac.md](07-mac.md): `mac-ssh true` exits 0, even when the Mac was asleep.
