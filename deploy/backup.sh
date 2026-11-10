#!/usr/bin/env bash
# Dump the database to /opt/kaya-backups and keep the last 14 days.
set -euo pipefail
OUT=/opt/kaya-backups
mkdir -p "$OUT" && chmod 700 "$OUT"
cd "$(dirname "$0")"
docker compose exec -T db pg_dump -U postgres -d kaya -Fc > "$OUT/kaya-$(date +%F).dump"
find "$OUT" -name 'kaya-*.dump' -mtime +14 -delete
echo "$(date -Is) backup ok"
