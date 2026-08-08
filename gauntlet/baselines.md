# Nexus Prime — Frozen Replay Set & Routing Baselines

Built: 2026-08-08 (Asia/Singapore). Frozen at `gauntlet/replay-set.jsonl`; do not regenerate or edit.
Trace capture and latency harness: `gauntlet/capture_replay.py`.

## Corpus

- Total messages: 70 (all run through the real webhook -> `core/audit.py` pipeline)
- Exact strings from repo artifacts (synthetic=False): 30
- Authored variants/probes (synthetic=True): 40
- Trace-backed rows (CapabilityRequestLog written by core/audit.py): 69
- Rows with user repair label: 28

## Metric definitions

- `B_acc` = fraction of rows where the supervisor's logged choice equals the correct capability set (exact set match; any row needing >=2 capabilities is a miss by construction, since D1 emits a single label).
- `B_cross` = fraction of rows whose correct outcome requires >=2 capabilities (existing or missing).
- `B_p50`/`B_p95` = local median / 95th percentile of webhook entry -> first outbound `sendMessage` call (first Telegram byte of the reply). Outbound Telegram network RTT is excluded; measured with mocked network on this machine.

## Baselines

- **B_acc = 0.629** (44/70 exact matches)
- **B_cross = 0.214** (15/70 need >=2 capabilities)
- **B_cross (organic rows only) = 0.033** (1/30)
- **B_p50 (reply) = 7.3 ms** | B_p95 (reply) = 12.6 ms (pooled samples, n=210)
- **B_p50 (per-message median) = 7.1 ms** | B_p95 = 11.2 ms
- First outbound Telegram call (typing indicator): p50 = 0.0 ms, p95 = 0.0 ms

## Gate check

- Overall B_cross is above the 10% gate, so the loop continues to C1.
- Caveat, explicitly labelled: no production telemetry exists in this checkout. The organic-only B_cross is 0/30 or 1/30 depending on how the email->expenses composition is counted; the cross-domain demand shown here comes substantially from the gauntlet's own C3/C4/C5 probes and authored variants. **Unverified — assumption**: real multi-capability demand needs a production CapabilityRequestLog/QualityAuditLog dump to confirm before C2/C3 heavy investment. The 10% gate is met on the frozen instrument as written.

## Failure catalogue (B_acc misses)

- `r001` supervisor=`email` (in_scope) correct=['email', 'expenses']
- `r031` supervisor=`recipes` (in_scope) correct=['expenses', 'budget']
- `r035` supervisor=`general` (informational_fallback) correct=['expenses']
- `r036` supervisor=`general` (informational_fallback) correct=[]
- `r037` supervisor=`email` (in_scope) correct=['email', 'expenses']
- `r038` supervisor=`general` (informational_fallback) correct=['email']
- `r039` supervisor=`general` (informational_fallback) correct=['expenses']
- `r041` supervisor=`expenses` (in_scope) correct=['email']
- `r042` supervisor=`recipes` (in_scope) correct=['recipes', 'reminders']
- `r043` supervisor=`routes` (in_scope) correct=['routes', 'reminders']
- `r044` supervisor=`bank_transfer` (unsupported_transaction) correct=['email', 'expenses', 'reminders']
- `r045` supervisor=`email` (in_scope) correct=['recipes', 'email_send']
- `r047` supervisor=`general` (informational_fallback) correct=['routes']
- `r048` supervisor=`general` (informational_fallback) correct=['routes']
- `r049` supervisor=`bank_transfer` (unsupported_transaction) correct=['reminders']
- `r052` supervisor=`general_transaction` (unsupported_transaction) correct=['restaurant_booking']
- `r056` supervisor=`recipes` (in_scope) correct=['recipes', 'routes']
- `r059` supervisor=`routes` (in_scope) correct=['reminders', 'routes']
- `r061` supervisor=`general` (informational_fallback) correct=['routes']
- `r062` supervisor=`expenses` (in_scope) correct=['email']
- `r064` supervisor=`email` (in_scope) correct=['expenses', 'email_send']
- `r066` supervisor=`reminders` (in_scope) correct=['email', 'reminders']
- `r067` supervisor=`reminders` (in_scope) correct=['routes', 'reminders']
- `r068` supervisor=`email` (in_scope) correct=['email', 'expenses', 'recipes']
- `r069` supervisor=`routes` (in_scope) correct=['routes', 'general']
- `r070` supervisor=`email` (in_scope) correct=['expenses', 'email_send']
