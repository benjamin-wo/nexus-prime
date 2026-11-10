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

## Catching up after the move (one-off)

Use this if Railway's app kept serving users after the dump in step 3, so some expenses and edits exist only in Railway's database, and users have since written to the new server too. It copies the Railway rows that changed after the dump, and never overwrites a row that also changed here.

1. **Open Railway's database to the internet.** In Railway, open Postgres → **Settings** → **Networking** → **TCP proxy**, and add one. Build the URL from the Variables tab: `postgresql://postgres:<PGPASSWORD>@<host>:<port>/railway`. The host and port are the proxy's; `PGPASSWORD` is Postgres's password. Keep the Railway app stopped.
2. **Update the app, so its image has the tool.** From `/opt/kaya/deploy`, run `git pull && docker compose up -d --build`.
3. **Run it.**

   ```sh
   cd /opt/kaya/deploy && ./catch-up-from-railway.sh
   ```

   It shows the cutoff (the time of `/root/railway.dump` minus 10 minutes) for you to confirm, then reads the URL silently. It never saves the URL, and the URL never appears in `ps`.
4. **Read the dry run first.** It prints counts per table (inserted, updated, already identical, conflicts, possibly deleted on Railway), and for each conflict only the table, the primary key and a reason. It never prints row contents and writes nothing.
5. **Apply.** Type `yes` at the prompt. The script takes a fresh backup first (`/opt/kaya-backups/kaya-<today>.dump`, to roll back to), then writes everything in one transaction, in foreign-key order, and moves the id sequences up.
6. **Remove the TCP proxy** on Railway's Postgres.

What it does and doesn't do:

- It merges every user-data table. It skips caches, telemetry, public market data, login sessions and links, the job queue and LangGraph checkpoints (the reason for each is in `EXCLUDED_TABLES` in `src/nexus/infra/db/catch_up.py`).
- A row that changed on both sides after the cutoff is a **conflict**: the new server's version stays, and you sort it out by hand. The same goes for a row that would break a unique key.
- Rows missing on Railway but present here are only counted ("possibly deleted on Railway"). It never deletes anything.
- It connects as `postgres` on both sides, which bypasses row-level security. The app's own role would only see one user's rows.
- It is safe to run again: rows already copied show as identical.
- To run it by hand, put the Railway URL in `CATCH_UP_SOURCE_URL`, then run `docker compose exec -T -e CATCH_UP_SOURCE_URL app python -m nexus.infra.db.catch_up --since <ISO time with zone> [--apply]`. Without `--apply` it is a dry run.

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
