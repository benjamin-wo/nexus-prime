#!/usr/bin/env bash
# Run Nexus locally for testing on a phone browser, the iOS Simulator or the Android Emulator.
#
#   scripts/dev-local.sh web       # backend + web app; open the printed address on your phone
#   scripts/dev-local.sh ios       # the same, plus the Expo shell in the iOS Simulator
#   scripts/dev-local.sh android   # the same, plus the Expo shell in the Android Emulator
#
# Everything is served on this Mac's Wi-Fi address (http://<ip>:5173), so a real phone, the
# simulator and the emulator all reach the same origin: the backend accepts requests from one
# origin only (WEB_ORIGIN), which this script sets to that address.
#
# Needs: Docker, uv, Node 22, a filled-in .env at the repo root (copy your own; this script
# never prints it). It always uses its own local database, a Docker container named
# nexus-local-db on port 5434 (DEV_DB_PORT; its data is kept in the nexus-local-pgdata
# volume between runs), whatever DATABASE_URL the .env says, so a Postgres installed on the
# Mac itself (often on 5432) can't get in the way. Background jobs are off, so nothing is
# sent on Telegram.
# Sign in with the demo account: open the address, then "Try the demo" (DEMO_ENABLED is on).
# Ctrl-C stops everything it started.
set -euo pipefail

MODE="${1:-web}"
case "$MODE" in web | ios | android) ;; *)
  echo "usage: $0 [web|ios|android]" >&2
  exit 2
  ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "No .env in $ROOT. Copy yours (cp ~/path/to/nexus-prime/.env .env) or start from .env.example." >&2
  exit 1
fi

IP="${DEV_IP:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)}"
if [[ -z "$IP" ]]; then
  echo "Couldn't find this Mac's Wi-Fi address. Set DEV_IP=... and try again." >&2
  exit 1
fi
ORIGIN="http://$IP:5173"

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

DB_PORT="${DEV_DB_PORT:-5434}"
echo "Starting the database on :$DB_PORT..."
if ! docker ps --format '{{.Names}}' | grep -qx nexus-local-db; then
  docker rm -f nexus-local-db >/dev/null 2>&1 || true
  docker run -d --name nexus-local-db -p "127.0.0.1:$DB_PORT:5432" \
    -e POSTGRES_USER=nexus -e POSTGRES_PASSWORD=nexus -e POSTGRES_DB=nexus \
    -v nexus-local-pgdata:/var/lib/postgresql/data postgres:16 >/dev/null
fi
for _ in $(seq 1 30); do
  docker exec nexus-local-db pg_isready -U nexus >/dev/null 2>&1 && break
  sleep 1
done

export ENVIRONMENT=dev
export DATABASE_URL="postgresql://nexus:nexus@localhost:$DB_PORT/nexus"
export WEB_ORIGIN="$ORIGIN"
export DEMO_ENABLED=true
export JOBS_ENABLED=false

echo "Migrating..."
uv run --quiet alembic upgrade head

echo "Starting the backend on :8000..."
uv run --quiet uvicorn --factory nexus.main:create_app --reload --port 8000 &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -fsS localhost:8000/healthz >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS localhost:8000/healthz >/dev/null 2>&1 || {
  echo "The backend didn't come up; see its output above." >&2
  exit 1
}

echo "Starting the web app on $ORIGIN..."
(cd web && { [[ -d node_modules ]] || npm ci; } && npm run dev -- --host 0.0.0.0 --port 5173 --strictPort) &
PIDS+=($!)

cat <<EOF

  Nexus is running at $ORIGIN/app
  On a phone: join the same Wi-Fi and open that address.
  Sign in: "Try the demo" on the login page (a private demo account with made-up data).

EOF

if [[ "$MODE" != web ]]; then
  cd mobile
  [[ -d node_modules ]] || npm ci
  echo "Opening the Expo shell in the ${MODE} $([[ $MODE == ios ]] && echo Simulator || echo Emulator)..."
  echo "(Expo Go asks you to sign in to Expo once: npx expo login.)"
  EXPO_PUBLIC_SITE_URL="$ORIGIN" npx expo start "--$MODE"
else
  wait
fi
