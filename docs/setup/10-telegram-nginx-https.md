# 10. Telegram, nginx and HTTPS

## HTTPS with nginx

The shortcuts and the dashboard reach small local services through one nginx site. The services themselves only listen on `127.0.0.1`.

1. **Point `PUBLIC_HOST` at the server** (DNS A record).
2. **Copy `server/nginx/voice.conf`** to `/etc/nginx/sites-available/voice`, replace every `PUBLIC_HOST` in it with your host (`sudo sed -i "s/PUBLIC_HOST/voice.yourdomain.com/g" /etc/nginx/sites-available/voice`), and link it into `sites-enabled`.
   Note: until the certificate exists, nginx will refuse the HTTPS block. Get the certificate first (step 3) using a temporary HTTP-only site, or comment out the HTTPS server block until then. *Assumption: the original server already had nginx and certbot set up for other sites.*
3. **Get a certificate** with certbot in webroot mode (the site serves `/.well-known/acme-challenge/` from `/var/www/certbot`):
   ```
   sudo certbot certonly --webroot -w /var/www/certbot -d voice.yourdomain.com
   ```
   Why webroot: it doesn't need to stop nginx, so other sites on the same server keep running. Certbot's timer renews it.
4. **Test, then reload:** `sudo nginx -t && sudo systemctl reload nginx`.
   Why test first: a broken nginx config stops *every* site on the server, not just this one.

### What the site exposes

| Path | Goes to | Allowed methods | Used by |
|---|---|---|---|
| `/call/<secret>` | `voice-watcher` 127.0.0.1:7891 | GET, POST | "Call me" shortcut |
| `/jobs/<secret>/` | `voice-dashboard` 127.0.0.1:7893 | GET, POST | Job dashboard |
| `/ask/<secret>` | `voice-ask` 127.0.0.1:7894 (body up to 15 MB) | POST | "Ask Claude" shortcut |
| `/wake/`, `/force/`, `/beat/` | `voice-ask` 127.0.0.1:7894 | POST | Wake shortcuts, Mac heartbeat |
| anything else | 404 | | |

HTTP redirects to HTTPS. Access logging is off, so the secret paths never land in log files.

## Telegram

Telegram is used in three ways:
1. **Chat with Claude:** the Claude Code Telegram channel in the `claude-helper` session (see [05-claude-code.md](05-claude-code.md)). From there you can ask for a call, stop or resume all tasks, pick a pronunciation, and approve installs.
2. **Alerts and notes without Claude:** services send messages straight through the Telegram Bot API using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from `/etc/voice-caller/secrets.env`: health alerts, failure alerts, call notes after each call, review notes, the daily summary, the weekly review, usage warnings.
3. **Fallback:** when the Mac can't be reached, texts that would go by iMessage go to Telegram instead.

Steps:
1. Create a bot with BotFather and get its secret.
2. Find your own chat id (send the bot a message, then read it from the Bot API's `getUpdates`).
3. Put both in `secrets.env`, and in the Telegram plugin's config for the helper session (access allowlist: your account only).
4. Media: the Telegram plugin saves photos and voice notes you send into the helper's Claude folder (`channels/telegram/inbox`). `voice-media-telegram.timer` copies new files from there into the shared media inbox every 15 s.

Check: `systemctl start voice-summary` should send you a summary message on Telegram.
