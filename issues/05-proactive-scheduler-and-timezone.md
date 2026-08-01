# 05 - Proactive Scheduler & Dynamic Timezone Adaptation Protocol

Status: resolved
Type: grilling
Blocked by: 01, 03

## Question

What is the exact specification for `schedule_proactive_task()`, the PostgreSQL `scheduled_jobs` table, the `/run_now` / dry-run testing suite, and the timezone auto-detection rules?

## Answer

1. **Conversational Scheduling & Storage**: Store dynamic cron jobs in a PostgreSQL `ScheduledJob` table (`job_name`, `cron_expression`, `instruction_prompt`, `timezone`, `is_active`). Expose conversational tools (`schedule_proactive_task`) and commands (`/jobs`, `/run_now <job_id>`) for on-the-go management and 5-second dry-run testing.
2. **5-Pillar Scheduler Guardrail System**: Guarantee reliability on Railway via: (a) initializing `AsyncIOScheduler()` inside FastAPI's official `lifespan` context manager; (b) setting `misfire_grace_time=3600` and `coalesce=True` to survive server redeployments; (c) installing `tzdata` in Docker and compiling triggers with `ZoneInfo`; (d) dual-registration in memory and PostgreSQL with a 60-second watchdog; and (e) `/jobs` and `/run_now` inspection.
3. **Dynamic Timezone Adaptation**: Store an IANA timezone in `user_profile.current_timezone`. Automatically update via conversational chat, Telegram location pins, or proactive flight arrival alerts from `EmailSubagent`. When timezone changes, automatically recalculate `next_run_time` for all active jobs.
