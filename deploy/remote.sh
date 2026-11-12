#!/usr/bin/env bash
# The only thing the GitHub Actions key may run on this server (a forced command in
# root's authorized_keys). It takes one word, from the "Server" workflow:
#   deploy   pull main, rebuild and restart Nexus, then check it answers
#   health   is Nexus answering?
#   status   containers, memory, disk, last backup
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
SITE=$(grep -m1 '^SITE_ADDRESS=' .env | cut -d= -f2)

health() {
  for _ in $(seq 1 30); do
    if curl -fsS -m 5 "https://$SITE/healthz" >/dev/null 2>&1; then echo "healthy"; return 0; fi
    sleep 4
  done
  echo "NOT answering after 2 minutes"; return 1
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
  restart) docker compose restart app >/dev/null && health ;;
  *) echo "unknown action; use deploy, health, status or restart"; exit 2 ;;
esac
