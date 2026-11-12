#!/usr/bin/env bash
# One-off: bring rows written on Railway AFTER the dump into this server's database, without
# overwriting anything changed here since. Run from /opt/kaya/deploy after rebuilding the app
# (git pull && docker compose up -d --build) so the app image has nexus.infra.db.catch_up.
#
# It asks for Railway's public database URL (read silently, never echoed or saved, passed to
# the app container through an environment variable, so it never appears in `ps`), then:
#   1. shows a dry run (counts only, nothing written);
#   2. on "yes", takes a fresh backup and applies the same thing in one transaction.
# The cutoff defaults to the time of /root/railway.dump minus 10 minutes (override: SINCE=...).
set -euo pipefail
cd "$(dirname "$0")"

DUMP=/root/railway.dump
SINCE="${SINCE:-}"
if [ -z "$SINCE" ]; then
  [ -f "$DUMP" ] || { echo "No $DUMP here; set SINCE=<ISO time with zone>, e.g. SINCE=2026-11-10T12:30:00Z"; exit 1; }
  SINCE=$(date -u -d "@$(( $(stat -c %Y "$DUMP") - 600 ))" +%Y-%m-%dT%H:%M:%SZ)
fi
echo "Cutoff (dump time minus 10 minutes): $SINCE"
read -rp "Press Enter to use it, or type another ISO time (with zone): " OTHER
SINCE="${OTHER:-$SINCE}"

read -rsp "Paste Railway's public database URL, then press Enter: " CATCH_UP_SOURCE_URL; echo
[ -n "$CATCH_UP_SOURCE_URL" ] || { echo "No URL given."; exit 1; }
export CATCH_UP_SOURCE_URL

run() {
  # -e NAME (no value) passes the variable through from this shell, not through argv.
  # </dev/null: otherwise docker reads this script's stdin and swallows the answers to
  # the prompts after it (a piped "yes" never reached the Apply question).
  docker compose exec -T -e CATCH_UP_SOURCE_URL app python -m nexus.infra.db.catch_up --since "$SINCE" "$@" </dev/null
}

echo "==> Dry run (nothing is written)"
run

read -rp "Apply this? Type yes to take a backup and write it: " ANSWER
[ "$ANSWER" = "yes" ] || { echo "Nothing applied."; exit 0; }

echo "==> Backing up the new database first"
./backup.sh
echo "Rollback copy: /opt/kaya-backups/kaya-$(date +%F).dump"

echo "==> Applying"
run --apply
echo "Done. Now remove the TCP proxy on Railway's Postgres (Settings -> Networking)."
