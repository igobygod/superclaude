# shared helpers (sourced). Reads Telegram creds from root-only env; never prints them.
set -a; . /etc/voice-caller/secrets.env; set +a
tg() { # usage: tg "text"
  curl -fsS -m 20 -o /dev/null "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" 2>&1 | sed 's/bot[0-9A-Za-z:_-]*/bot***/g' >&2
}
