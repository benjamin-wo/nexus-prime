import asyncio
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Optional, Dict, Any
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.db import async_session_factory
from core.models import ScheduledJob, UserProfile, UserCredential

# 1-Hour Misfire Grace and Coalescing to survive server redeploys on Railway
scheduler = AsyncIOScheduler(
    job_defaults={
        "misfire_grace_time": 3600,
        "coalesce": True,
        "max_instances": 1,
    }
)

async def _execute_scheduled_job(job_id: int, user_id: int, instruction_prompt: str):
    """Callback executed when a cron job fires."""
    # In a full deployment, this triggers a notification or LangGraph run
    # For testing and logging, we record the trigger execution
    print(f"[SCHEDULER] Triggered job {job_id} for user {user_id}: {instruction_prompt}")


async def _scheduled_email_expense_sweep():
    """Daily sweep: scan Gmail for financial emails, auto-log expenses, notify the user."""
    from capabilities.expenses.tools import log_expenses_from_emails
    from capabilities.email.tools import search_email_messages

    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(UserCredential.provider == "gmail")
        )
        user_ids = list({cred.user_id for cred in result.scalars().all()})

    for user_id in user_ids:
        try:
            emails = await search_email_messages.ainvoke({"user_id": user_id})
            if not emails:
                continue
            expense_result = await log_expenses_from_emails.ainvoke(
                {"user_id": user_id, "emails": emails}
            )
            logged = expense_result.get("logged") or []
            if not logged:
                continue

            chat_id = None
            async with async_session_factory() as session:
                profile = (
                    await session.execute(
                        select(UserProfile).where(UserProfile.user_id == user_id)
                    )
                ).scalar_one_or_none()
                chat_id = profile.telegram_chat_id if profile else None
            if not chat_id:
                continue

            from app.ingress import send_telegram_message

            lines = [
                f"📬 Daily email sweep — auto-logged {len(logged)} expense"
                f"{'s' if len(logged) != 1 else ''}:"
            ]
            for item in logged[:8]:
                lines.append(f"• {item['currency']} {item['amount']:.2f} — {item['merchant']}")
            await send_telegram_message(chat_id, "\n".join(lines))
        except Exception as exc:  # noqa: BLE001 - one user's failure must not block the sweep
            print(f"[SWEEP] error for user {user_id}: {exc}")


async def start_scheduler():
    """Start the APScheduler instance and reconcile DB jobs."""
    if not scheduler.running:
        scheduler.start()
        await reconcile_jobs()
        try:
            scheduler.add_job(
                _scheduled_email_expense_sweep,
                trigger=CronTrigger.from_crontab(
                    "0 9 * * *", timezone=ZoneInfo("Asia/Singapore")
                ),
                id="email_expense_sweep",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
                max_instances=1,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[SCHEDULER] failed to register email expense sweep: {exc}")

async def shutdown_scheduler():
    """Shutdown APScheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)

async def schedule_proactive_task(
    user_id: int,
    job_name: str,
    cron_expression: str,
    instruction_prompt: str,
    timezone_str: str = "UTC",
    session: Optional[AsyncSession] = None,
) -> ScheduledJob:
    """Register a proactive cron job in Postgres and in-memory scheduler."""
    close_session = False
    if session is None:
        session = async_session_factory()
        close_session = True
    try:
        job = ScheduledJob(
            user_id=user_id,
            job_name=job_name,
            cron_expression=cron_expression,
            instruction_prompt=instruction_prompt,
            timezone=timezone_str,
            is_active=True,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        # Register in-memory
        _add_job_to_scheduler(job)
        return job
    finally:
        if close_session:
            await session.close()

def _add_job_to_scheduler(job: ScheduledJob):
    """Compile cron trigger with ZoneInfo and add to APScheduler."""
    try:
        tz = ZoneInfo(job.timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    trigger = CronTrigger.from_crontab(job.cron_expression, timezone=tz)
    scheduler.add_job(
        _execute_scheduled_job,
        trigger=trigger,
        args=[job.id, job.user_id, job.instruction_prompt],
        id=str(job.id),
        replace_existing=True,
    )

async def reconcile_jobs():
    """Watchdog task: reconcile PostgreSQL ScheduledJob rows with Uvicorn memory."""
    async with async_session_factory() as session:
        result = await session.execute(select(ScheduledJob).where(ScheduledJob.is_active == True))
        active_jobs = result.scalars().all()
        for job in active_jobs:
            _add_job_to_scheduler(job)

async def update_user_timezone(user_id: int, new_timezone: str) -> bool:
    """Update user timezone and recalculate next_run_time for all active jobs."""
    try:
        # Validate timezone string
        ZoneInfo(new_timezone)
    except Exception:
        return False

    async with async_session_factory() as session:
        # Update profile
        result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if profile:
            profile.current_timezone = new_timezone
            session.add(profile)

        # Update all active jobs for user
        job_res = await session.execute(
            select(ScheduledJob).where(ScheduledJob.user_id == user_id, ScheduledJob.is_active == True)
        )
        user_jobs = job_res.scalars().all()
        for job in user_jobs:
            job.timezone = new_timezone
            session.add(job)
            _add_job_to_scheduler(job)

        await session.commit()
        return True

async def list_active_jobs(user_id: int) -> List[Dict[str, Any]]:
    """Return local timestamps for next_run_time of active jobs."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ScheduledJob).where(ScheduledJob.user_id == user_id, ScheduledJob.is_active == True)
        )
        jobs = result.scalars().all()

        job_info_list = []
        for job in jobs:
            aps_job = scheduler.get_job(str(job.id))
            next_run = aps_job.next_run_time.isoformat() if (aps_job and aps_job.next_run_time) else None
            job_info_list.append({
                "job_id": job.id,
                "job_name": job.job_name,
                "cron_expression": job.cron_expression,
                "timezone": job.timezone,
                "next_run_time": next_run,
                "instruction_prompt": job.instruction_prompt,
            })
        return job_info_list

async def run_now(job_id: int) -> bool:
    """Dry-run testing: trigger any reminder on demand in 5 seconds."""
    async with async_session_factory() as session:
        result = await session.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return False

        run_time = datetime.now(dt_timezone.utc) + timedelta(seconds=5)
        scheduler.add_job(
            _execute_scheduled_job,
            trigger=DateTrigger(run_date=run_time),
            args=[job.id, job.user_id, job.instruction_prompt],
            id=f"run_now_{job.id}_{int(run_time.timestamp())}",
            replace_existing=True,
        )
        return True
