#!/usr/bin/env bash
# The only thing the GitHub Actions key may run on this server (a forced command in
# root's authorized_keys). It takes one word, from the "Server" workflow:
#   deploy   pull main, rebuild and restart Nexus, then check it answers
#   health   is Nexus answering?
#   status   containers, memory, disk, last backup
#   telegram is Telegram delivering messages to Nexus, and how did the app fare today?
#   restart  restart the app container
# Its output lands in public GitHub Actions logs, so it never prints app logs,
# settings or anyone's data: only counts, names and statuses.
set -euo pipefail
# "deploy" pulls a new copy of this file, so run from a copy that won't change under us.
if [ -z "${KAYA_REMOTE_COPY:-}" ]; then
  cp "$0" /tmp/kaya-remote.sh
  KAYA_REMOTE_COPY=1 exec bash /tmp/kaya-remote.sh
fi
DIR=/opt/kaya
cd "$DIR/deploy"
# Read the address the way docker compose does: the last SITE_ADDRESS line wins (an old one
# can be left higher up after moving to a new domain), without surrounding quotes, spaces or
# a Windows line ending (SITE_ADDRESS="nexus-prime.app" is a valid .env line).
SITE=$(grep '^SITE_ADDRESS=' .env | tail -n 1 | cut -d= -f2- | tr -d "\"' \r")

health() {
  for _ in $(seq 1 30); do
    if curl -fsS -m 5 "https://$SITE/healthz" >/dev/null 2>&1; then echo "healthy (https://$SITE)"; return 0; fi
    sleep 4
  done
  echo "NOT answering at https://$SITE/healthz after 2 minutes"; return 1
}

case "${SSH_ORIGINAL_COMMAND:-}" in
  deploy)
    git -C "$DIR" pull --ff-only --quiet
    echo "code at $(git -C "$DIR" log -1 --format='%h %s')"
    docker compose up -d --build --quiet-pull 2>&1 | grep -E 'Built|Started|Running|Error' || true
    health ;;
  health) health ;;
  status)
    docker compose ps --format '{{.Service}}: {{.Status}}'
    free -m | awk 'NR==2{print "memory: "$3" MB used of "$2" MB"}'
    df -h / | awk 'NR==2{print "disk: "$3" used of "$2" ("$5")"}'
    echo "last backup: $(ls -1t /opt/kaya-backups 2>/dev/null | head -1 || echo none)"
    echo "app errors in the last hour: $(docker compose logs --since 1h app 2>/dev/null | grep -ciE '"level": "error"|traceback' || true)" ;;
  telegram)
    # What Telegram says about delivering messages to the webhook, asked from inside the app
    # container (it holds the bot token, which is never printed: a failed request names only
    # its error type). Telegram's last error text is an HTTP status or a network failure.
    # Then the last 24 hours of the app: errors, failed Telegram updates, and the error
    # types seen (class names only, never messages).
    docker compose exec -T app python - "$SITE" <<'PY' || echo "telegram: the check could not run in the app container"
import json, os, sys, time, urllib.parse, urllib.request

site = sys.argv[1]
token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    print("telegram: no bot token set")
    raise SystemExit(0)
try:
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    with urllib.request.urlopen(url, timeout=15) as response:
        info = json.load(response).get("result") or {}
except Exception as error:
    print(f"telegram: could not ask the Bot API ({type(error).__name__})")
    raise SystemExit(0)


def ago(stamp):
    minutes = int((time.time() - stamp) // 60)
    if minutes < 120:
        return f"{minutes} min ago"
    if minutes < 2880:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} days ago"


hook = info.get("url") or ""
if not hook:
    print("webhook: NOT SET (Telegram has nowhere to send messages)")
elif hook == f"https://{site}/telegram/webhook":
    print("webhook: set to this server")
else:
    print(f"webhook: points elsewhere ({urllib.parse.urlsplit(hook).hostname})")
print(f"messages waiting at Telegram: {info.get('pending_update_count', 0)}")
if info.get("last_error_date"):
    message = str(info.get("last_error_message", ""))[:120]
    print(f"last delivery error: {ago(info['last_error_date'])}: {message}")
else:
    print("last delivery error: none")
if info.get("last_synchronization_error_date"):
    print(f"last Telegram-side sync error: {ago(info['last_synchronization_error_date'])}")
PY
    logs=$(docker compose logs --since 24h app 2>/dev/null || true)
    echo "app errors in the last 24 hours: $(grep -ciE '"level": "error"|traceback' <<<"$logs" || true)"
    echo "telegram updates that failed in the last 24 hours: $(grep -c 'failed to handle telegram update' <<<"$logs" || true)"
    echo "error types in the last 24 hours:"
    grep -oE '\b[A-Z][A-Za-z0-9_]*(Error|Exception|Timeout)\b' <<<"$logs" | sort | uniq -c | sort -rn | head -8 || true ;;
  restart) docker compose restart app >/dev/null && health ;;
  *) echo "unknown action; use deploy, health, status, telegram or restart"; exit 2 ;;
esac
