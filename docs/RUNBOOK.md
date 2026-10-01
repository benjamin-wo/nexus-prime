# Runbook

What to do when something goes wrong with Nexus in production. For how it's configured, see [`OPERATIONS.md`](OPERATIONS.md); for the security model, [`SECURITY.md`](SECURITY.md).

## What runs where

| Railway service | What | Notes |
|---|---|---|
| `nexus-app` | The app: Telegram webhook, web app and API, job runner | One instance. Builds from the `Dockerfile` on `main`; pre-deploy runs `alembic upgrade head`; health check `/healthz` |
| `Postgres-xYMg` | The database (Postgres 18) | Private network only, volume at `/var/lib/postgresql/data` |
| `Postgres` | The **old** bot's database | Read-only archive. Never write to it, restore over it or delete it |
| bucket | Receipt photos | Private; reached through presigned links |

Everything below assumes the Railway CLI, logged in and linked to the project (`railway link`). The database has no public endpoint. App commands (`python -m nexus...`) run from a shell in the app container, `railway ssh --service nexus-app`; SQL, dumps and restores run from a shell in the database's own container, `railway ssh --service Postgres-xYMg`, which has `psql`, `pg_dump` and `pg_restore` at the server's version and `PG*` variables that connect to it (the app image has no Postgres client). Never paste credentials into chat, tickets or the repo.

## First look

1. **Is it up?** `curl https://<domain>/healthz` returns `{"status":"ok"}` only when the app can reach the database.
2. **Ask the bot** "are you working?": it answers from the kernel without the model, and names the model in use.
3. **Logs:** Railway → `nexus-app` → Deployments → the active one → Logs (or `railway logs --service nexus-app`). Logs never carry message text, tokens or URLs with secrets; HTTP client logging is held to warnings.
4. **Recent deploys:** a problem that started with a deploy is fixed fastest by rolling back (below).

## The bot doesn't reply

| Check | Means | Do |
|---|---|---|
| `/healthz` fails or times out | The app is down or can't reach Postgres | See the database section; check the deploy logs for a crash at startup (a missing or malformed variable stops startup on purpose, and the log names it) |
| Health is fine, no log line for the message | Telegram isn't delivering | `python -m nexus.channels.telegram.register` (in the app shell) shows the webhook URL and Telegram's last delivery error. `--yes` points it back here. A wrong `TELEGRAM_WEBHOOK_SECRET` shows as 401s in the logs |
| Log shows the update, no reply | Usually the model | See below |
| The user gets "give me a minute" | The rate limit (20 a minute, 400 a day per user) | Expected for a stuck client; it clears by itself. A restart also clears it |
| Only one person is affected | Allowlist | They must be the owner or in `TELEGRAM_ALLOWED_USER_IDS` |

## The model is failing

With `LLM_PROVIDER=openrouter`, `OPENROUTER_FALLBACK_MODELS` are tried in order when `OPENROUTER_MODEL` fails, so a single provider outage shouldn't be visible.

- **Everything fails:** check [OpenRouter's status](https://status.openrouter.ai) and the account's credits. An invalid or exhausted key fails every model.
- **Switch model:** set `OPENROUTER_MODEL` (or the fallback list) on `nexus-app`; Railway redeploys with it. Choose from models that have been scored with `python -m nexus.evals` (see [`EVALS.md`](EVALS.md)), and keep OpenRouter's privacy setting that excludes providers who train on prompts.
- **Receipt photos only:** `OPENROUTER_VISION_MODEL`.
- **Memory only:** failed `memory.update` jobs don't affect replies; the job is retried. `MEMORY_MODEL` can point it elsewhere.

## Background jobs

Alerts, reminders, check-ins, email sweeps and memory run from the `jobs` table inside the app. Each job has 90 seconds; up to 5 run at once (one user's in order); a job that fails backs off and stops after 5 attempts. A runner that dies holds its jobs for up to 20 minutes (the lease), then they are retried.

From the database shell (`psql`):

```sql
-- What's waiting, running and failed, by kind
select kind, status, count(*), min(run_at) from jobs
where status <> 'done' group by 1, 2 order by 1, 2;

-- Why recent ones failed
select kind, attempts, last_error, finished_at from jobs
where status = 'failed' order by finished_at desc limit 20;
```

- **A backlog that isn't shrinking:** check that `JOBS_ENABLED` isn't off and the logs show the runner. Measured capacity is far above our load (below), so a backlog means jobs are failing or the runner is stopped, not that it's slow.
- **A job failed for good** after a fix is deployed: requeue it with `update jobs set status = 'pending', attempts = 0, run_at = now() where id = ...;`. Recurring sweeps don't need this; the next slot runs anyway.
- **Messages arriving late at night** don't happen by design: Telegram messages wait out 22:00–08:00 in the user's timezone.

**Measured capacity** (M10, `scripts/load_jobs.py` on a throwaway local database):

| Run | Throughput | Ran twice |
|---|---|---|
| 2,000 quick jobs, 1 runner, before M10 | 2.0 a second | 0 |
| 2,000 quick jobs, 1 runner | 172 a second | 0 |
| 2,000 quick jobs, 3 runners (as during a deploy overlap) | 103 a second | 0 |
| 500 two-second jobs, 1 runner | 2.5 a second | 0 |

The sweeps over 100 seeded users took: budgets 0.64 s, bills 0.66 s, payday 0.21 s, Telegram updates 0.31 s, subscriptions 0.38 s. To repeat:

```bash
TEST_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/postgres \
  uv run python scripts/load_jobs.py --jobs 2000 --runners 3 --work-ms 20
```

## Deploys

- **Roll back:** Railway → `nexus-app` → Deployments → a previous successful one → Redeploy. This is safe when the bad deploy added no migration. If it did, see "a migration failed" first: the old code may not run on the new schema.
- **A deploy that never goes live** usually failed its pre-deploy step or health check. The previous deployment keeps serving until the new one is healthy, so users aren't affected; read the deploy's logs, fix forward, and push.

### A migration failed

The pre-deploy `alembic upgrade head` runs the pending migrations in one transaction, so a failure leaves the schema where it was, and the old deployment keeps serving. Fix the migration and deploy again. Don't edit `alembic_version` by hand.

If a migration succeeded but the new code is wrong: fix forward. Downgrading needs care, because some migrations move data (0014–0016 regroup categories) and their downgrades don't put it back. When in doubt, take a backup first (below).

## Secrets

All secrets are Railway variables on `nexus-app`; none live in the repo. Changing a variable redeploys the service.

| Secret | To rotate |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/revoke`, set the new token. Existing web sessions keep working; new sign-ins are checked with the new token |
| `TELEGRAM_WEBHOOK_SECRET` | Set a new random value, then run `python -m nexus.channels.telegram.register --yes` so Telegram sends it |
| `OPENROUTER_API_KEY` | Create a new key in OpenRouter, set it, then delete the old key |
| `TOKEN_ENCRYPTION_KEY` | Put a new Fernet key **first**, keeping the old one after a comma; new tokens use the first and old ones still decrypt. Remove the old key only after every mailbox has reconnected or refreshed |
| `GOOGLE_CLIENT_SECRET` | Add a secret in Google Cloud, set it, delete the old one |
| `AGENTMAIL_API_KEY` | New key in AgentMail, set it, delete the old one |
| Bucket credentials | Reset them on the bucket in Railway; the reference variables pick them up |
| Web sessions | To sign everyone out: `delete from web_sessions;` (they sign in again with Telegram) |

If a secret may have leaked, rotate first and investigate after.

## Backups and restore

### What exists

- **Railway volume backups** of `Postgres-xYMg`: snapshots of the whole volume, taken on a schedule (daily kept 6 days, weekly kept a month, monthly kept 3 months) or by hand, from the database service's **Backups** tab. Turn on at least daily and weekly.
- **Point-in-time recovery** (optional, Railway Postgres images): archives every write so the database can be put back to any moment in about the last four weeks. Worth turning on if losing up to a day of entries isn't acceptable.
- **A logical dump** (`pg_dump`) before risky work, such as a migration that moves data. See below.

### Restore a volume backup

1. In `Postgres-xYMg` → **Backups**, find the backup by date and click **Restore**.
2. Railway stages the change: a new volume from the backup is mounted in place and the current one is kept, detached. Review the staged change and click **Deploy**.
3. The database restarts on the restored data; `nexus-app` reconnects by itself. Check `/healthz` and ask the bot "are you working?".
4. Anything written after the backup is gone: tell users which day they may need to re-enter from. Jobs re-run from whatever the backup had queued, and their dedupe keys keep them from running twice.
5. Keep the detached volume until you're sure; it's the way back.

Make sure it's `Postgres-xYMg`, never the old `Postgres` service.

### Take and restore a logical dump

From the database shell:

```bash
pg_dump --format=custom --no-owner --no-acl -f /tmp/nexus.dump
pg_restore --list /tmp/nexus.dump | head   # readable?
```

`pg_dump` must be at least the server's major version (18), which the database container's own is. `/tmp` there is outside the volume and is lost on restart; that's fine for a dump taken just before risky work. The dump contains every user's records: never put it in the repo, a chat or an unencrypted share, and delete it when done.

To restore, create an empty database and restore into it, then point `nexus-app`'s `DATABASE_URL` at it; never restore over the live database in place:

```bash
createdb nexus_restored
pg_restore --no-owner --no-acl --exit-on-error -d nexus_restored /tmp/nexus.dump
```

### The drill

`scripts/backup_drill.py` proves a dump restores to the same data: it seeds made-up users into a throwaway database, dumps it, restores into another, and compares every table's row count and a checksum of its contents, and the schema version.

```bash
TEST_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/postgres \
  PYTHONPATH=src uv run python scripts/backup_drill.py --users 200
```

M10 result (Postgres 16, local): 32 tables, 14,411 rows, a 615 KiB dump in 0.2 s and a restore in 0.3 s, every table identical, schema at 0018. With `--source <url>` it dumps an existing database instead (read only) and restores it into a scratch one; run that only where the restore server is as private as the source.

Repeat the drill when the schema changes a lot, and test a Railway volume restore once a year, on a copy of the environment rather than production.
