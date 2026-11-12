#!/usr/bin/env bash
# Copy the Railway database into this server's database. Run once, from /opt/kaya/deploy,
# with Nexus's app stopped. It asks for Railway's public database URL (Railway → Postgres →
# Variables → DATABASE_PUBLIC_URL); the URL is read silently and never saved.
set -euo pipefail
cd "$(dirname "$0")"

read -rsp "Paste Railway's DATABASE_PUBLIC_URL, then press Enter: " SRC; echo
[ -n "$SRC" ] || { echo "No URL given."; exit 1; }

echo "==> Stopping the app"
docker compose stop app || true
docker compose up -d db
until docker compose exec -T db pg_isready -U postgres -d kaya >/dev/null 2>&1; do sleep 2; done

echo "==> Dumping from Railway (this can take a minute)"
docker run --rm -e SRC="$SRC" postgres:18 sh -c 'pg_dump "$SRC" -Fc --no-owner' > /root/railway.dump
ls -lh /root/railway.dump

echo "==> Restoring into a fresh database"
docker compose exec -T db psql -U postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS kaya WITH (FORCE);" -c "CREATE DATABASE kaya;"
docker compose exec -T db psql -U postgres -d kaya -c \
  "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nexus_app') THEN CREATE ROLE nexus_app NOLOGIN; END IF; END \$\$; GRANT nexus_app TO postgres;"
docker compose exec -T db pg_restore -U postgres -d kaya --no-owner < /root/railway.dump \
  || echo "(pg_restore reported warnings above; usually harmless, check them)"

echo "==> Starting Nexus"
docker compose up -d --build
echo "Done. The Railway copy is kept at /root/railway.dump until you delete it."
