# M3 cutover: old bot → nexus-app

The old database is never written to. The old service stays deployable, so every step up to "stop the old service" can be undone by pointing the webhook back.

Both databases are private (no public endpoint), so the import runs inside Railway's private network, from a shell in the `nexus-app` container.

## Before you start
- `nexus-app` is deployed from `main` with this milestone and is healthy.
- `nexus-app` has `LEGACY_DATABASE_URL=${{Postgres.DATABASE_URL}}`, a reference to the **old** database, and has been redeployed since it was added. The importer refuses to run if it points at the same database as `DATABASE_URL`.
- You have the Railway CLI, logged in and linked to the project.

## 1. Dry run the import
```bash
railway ssh --service nexus-app
python -m nexus.legacy
```
Nothing is written. For each user it prints:
- what would be imported and anything skipped, with the reason
- amounts rounded to 4 decimal places, and currencies it had to assume
- repayments it had to assume, where an IOU was marked paid with no repayment record
- old versus new row counts and totals per currency

It ends with `Result: OK`, or `TOTALS DO NOT MATCH`.

## 2. Import
```bash
python -m nexus.legacy --apply
```
Each user is written in one transaction, and only if their counts and totals match. The exit code is 1 if any user didn't match. It is safe to run again: rows already imported are skipped.

## 3. Move the webhook
```bash
python -m nexus.channels.telegram.register          # shows the current webhook
python -m nexus.channels.telegram.register --yes    # points it at nexus-app
```
Note the "current webhook" it prints first. That's the rollback address, and should be `https://acceptable-adaptation-production-63b6.up.railway.app/api/webhook`.

## 4. Check it in Telegram
Try each of these:
- `/start` shows the menu
- `coffee 1`, then press **Undo**
- **This month** shows your imported spending
- **Who owes me** shows open IOUs

## 5. Catch late rows
The old bot may have recorded something between step 2 and step 3. Run the import once more; it only adds rows it hasn't seen:
```bash
python -m nexus.legacy --apply
```

## 6. Stop the old service
The old service still runs its own scheduler and email sweep with the same bot token, so it could keep messaging you and filling the old database. In the Railway dashboard, open `acceptable-adaptation` → the active deployment → **Remove**. Leave the service and its database in place: redeploying that deployment is the rollback.

Email receipt scanning pauses until M6 brings it to the new app.

Then remove `LEGACY_DATABASE_URL` from `nexus-app`.

## Rollback
```bash
python -m nexus.channels.telegram.register --yes \
  --url https://acceptable-adaptation-production-63b6.up.railway.app/api/webhook
```
Then redeploy `acceptable-adaptation` if you removed it. Anything recorded in the new app since cutover stays in the new database.
