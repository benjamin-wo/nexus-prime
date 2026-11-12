#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 24.04 server. Run as root:
#   curl -fsSL https://raw.githubusercontent.com/benjamin-wo/nexus-prime/main/deploy/setup.sh | bash
set -euo pipefail

REPO=https://github.com/benjamin-wo/nexus-prime.git
DIR=/opt/kaya

echo "==> Updates and Docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq ca-certificates curl git ufw unattended-upgrades
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

echo "==> 2 GB swap (the web build needs headroom on a 2 GB server)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Firewall: SSH and web only"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443
ufw --force enable

echo "==> Code in $DIR"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi

ENV="$DIR/deploy/.env"
if [ ! -f "$ENV" ]; then
  IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
  {
    echo "# Nexus server settings. Never commit or share this file."
    echo "SITE_ADDRESS=${IP//./-}.sslip.io"
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo
    echo "# Paste the rest of your settings below this line (see deploy/README.md)."
  } > "$ENV"
  chmod 600 "$ENV"
fi

echo "==> Nightly database backup at 03:15 (keeps 14 days in /opt/kaya-backups)"
cat > /etc/cron.d/kaya-backup <<CRON
15 3 * * * root $DIR/deploy/backup.sh >> /var/log/kaya-backup.log 2>&1
CRON

echo
echo "Done. Next: add your settings with   nano $ENV"
echo "then start Nexus with   cd $DIR/deploy && docker compose up -d --build"
