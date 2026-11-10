# Running Kaya on one server

This runs Kaya on one small Ubuntu 24.04 server, such as a US$12/month DigitalOcean Droplet with 2 GB RAM. The server runs three things:

- the app;
- Postgres 18;
- Caddy, which adds free HTTPS.

The free address is `https://<ip-with-dashes>.sslip.io`.

## 1. Set up the server (once)

As root on the server, run:

```sh
curl -fsSL https://raw.githubusercontent.com/benjamin-wo/nexus-prime/main/deploy/setup.sh | bash
```

This script:

1. installs Docker;
2. turns on the firewall, allowing only SSH, 80 and 443;
3. adds 2 GB swap;
4. clones the code to `/opt/kaya`;
5. writes `/opt/kaya/deploy/.env` with the site address and a random database password;
6. schedules a nightly database backup to `/opt/kaya-backups`, keeping 14 days.

## 2. Add your settings

1. In Railway, open the app service → **Variables** → **Raw Editor**, and copy everything.
2. On the server, run `nano /opt/kaya/deploy/.env`.
3. Paste below the last line. Save with Ctrl+O, Enter, then exit with Ctrl+X.

`DATABASE_URL`, `WEB_ORIGIN` and `PORT` are set by `docker-compose.yml`. Any copies you paste are ignored. Never commit or share `.env`.

## 3. Copy the data from Railway and start

```sh
cd /opt/kaya/deploy && ./import-from-railway.sh
```

The script asks for Railway's `DATABASE_PUBLIC_URL`. You'll find it under Railway → Postgres → Variables, and it only appears once the database has a TCP proxy. The URL is read silently and never saved. The script then:

1. dumps the Railway database;
2. restores it here;
3. builds and starts Kaya.

To start without Railway data instead, run `docker compose up -d --build`.

## 4. Point Telegram and Google at the new address

- **Telegram webhook:** this points it at `https://<site>/telegram/webhook` (from `WEB_ORIGIN`). Run it without `--yes` first to see the change.

  ```sh
  docker compose exec app python -m nexus.channels.telegram.register --yes
  ```

- **BotFather:** set the Mini App URL to `https://<site>/`.
- **Google Cloud console:** add `https://<site>/…` to the OAuth client's redirect URIs. Use the same path as the Railway one, on the new host.

## Everyday

| Task | Command (from `/opt/kaya/deploy`) |
| --- | --- |
| Update to the latest code | `git pull && docker compose up -d --build` |
| Logs | `docker compose logs -f app` |
| Restart | `docker compose restart app` |
| Back up now | `./backup.sh` |

## Running actions from GitHub (optional)

The **Server** workflow (Actions tab → Server → Run workflow) runs one of `health`, `status`, `deploy` or `restart` on the server over SSH. Its key can run only `deploy/remote.sh`, which is enforced on the server as a forced command. Workflow logs are public on a public repo, so the script prints statuses and counts only, never app logs or data.

One-time setup, as root on the server:

```sh
ssh-keygen -t ed25519 -N '' -C github-actions -f /root/gh-actions
echo "command=\"/opt/kaya/deploy/remote.sh\",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $(cat /root/gh-actions.pub)" >> /root/.ssh/authorized_keys
ssh-keyscan -t ed25519 <server-ip> 2>/dev/null   # → secret DROPLET_KNOWN_HOSTS
cat /root/gh-actions                              # → secret DROPLET_SSH_KEY, then: rm /root/gh-actions
```

Then in GitHub, go to Settings → Secrets and variables → Actions and add three repository secrets:

- `DROPLET_HOST`: the server's IP address.
- `DROPLET_SSH_KEY`: the private key printed above.
- `DROPLET_KNOWN_HOSTS`: the `ssh-keyscan` line.
