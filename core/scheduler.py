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
from core.models import ScheduledJob, UserProfile, UserCredential, TaskItem

# 1-Hour Misfire Grace and Coalescing to survive server redeploys on Railway
scheduler = AsyncIOScheduler(
    job_defaults={
        "misfire_grace_time": 3600,
        "coalesce": True,
        "max_instances": 1,
    }
)

_watchdog_task: Optional[asyncio.Task] = None


async def _watchdog_loop():
    """60-second watchdog: reconcile Postgres job rows with in-memory APScheduler."""
    while True:
        await asyncio.sleep(60)
        try:
            await reconcile_jobs()
        except Exception as exc:  # noqa: BLE001
            print(f"[SCHEDULER] watchdog reconcile error: {exc}")

async def _execute_scheduled_job(job_id: int, user_id: int, instruction_prompt: str):
    """Callback executed when a cron job fires: notify the user on Telegram."""
    print(f"[SCHEDULER] Triggered job {job_id} for user {user_id}: {instruction_prompt}")
    try:
        chat_id = None
        tz_name = "Asia/Singapore"
        async with async_session_factory() as session:
            profile = (
                await session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                )
            ).scalar_one_or_none()
            chat_id = profile.telegram_chat_id if (profile and profile.telegram_chat_id != 999999) else None
            if not chat_id and settings.admin_telegram_chat_id:
                try:
                    chat_id = int(settings.admin_telegram_chat_id)
                except Exception:
                    pass
            tz_name = profile.current_timezone if profile and profile.current_timezone else tz_name
        if not chat_id:
            print(f"[SCHEDULER] Cannot deliver scheduled job {job_id}: no valid telegram chat_id found for user {user_id}")
            return

        from core.ambient import should_deliver
        from datetime import datetime, timezone as dt_timezone

        trigger = {
            "kind": "scheduled_job",
            "trigger_id": f"job-{job_id}",
            "job_id": job_id,
            "message": instruction_prompt,
            "instruction_prompt": instruction_prompt,
        }
        deliver, reason = should_deliver(trigger, datetime.now(dt_timezone.utc), tz_name)
        if not deliver:
            print(f"[AMBIENT] suppressed job {job_id}: {reason}")
            return

        from app.ingress import send_telegram_message

        await send_telegram_message(
            chat_id,
            f"⏰ *Reminder* (#{job_id}):\n{instruction_prompt}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[SCHEDULER] failed to deliver job {job_id}: {exc}")


async def _execute_task_reminder(task_id: int, user_id: int, is_test: bool = False):
    """Callback executed when a task reminder fires: send rich Telegram alert with 1-tap buttons."""
    print(f"[SCHEDULER] Triggered task reminder for task {task_id} (user {user_id}, is_test={is_test})")
    try:
        chat_id = None
        task = None
        async with async_session_factory() as session:
            task = (
                await session.execute(
                    select(TaskItem).where(TaskItem.id == task_id)
                )
            ).scalar_one_or_none()
            if not task or (not is_test and (task.status == "done" or not task.is_reminder_active)):
                return

            profile = (
                await session.execute(
                    select(UserProfile).where(UserProfile.user_id == task.user_id)
                )
            ).scalar_one_or_none()
            chat_id = profile.telegram_chat_id if (profile and profile.telegram_chat_id != 999999) else None
            if not chat_id and settings.admin_telegram_chat_id:
                try:
                    chat_id = int(settings.admin_telegram_chat_id)
                except Exception:
                    pass

            # For normal one-time reminder, mark reminder as triggered / inactive
            if not is_test and task.reminder_type == "once":
                task.is_reminder_active = False
                session.add(task)
                await session.commit()

        if not chat_id or not task:
            print(f"[SCHEDULER] Cannot deliver task reminder {task_id}: no valid telegram chat_id found")
            return

        priority_icons = {
            "high": "🔴 High",
            "medium": "🟡 Medium",
            "low": "🟢 Low",
        }
        p_badge = priority_icons.get(task.priority, "🟡 Medium")

        tz_name = (profile.current_timezone if profile and profile.current_timezone else None) or task.timezone or "Asia/Singapore"
        due_str = ""
        if task.due_at:
            try:
                import zoneinfo
                from datetime import timezone
                dt_utc = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=timezone.utc)
                local_dt = dt_utc.astimezone(zoneinfo.ZoneInfo(tz_name))
                due_str = f"\n📅 Due: {local_dt.strftime('%a, %b %d, %I:%M %p')}"
            except Exception:
                due_str = f"\n📅 Due: {task.due_at.strftime('%Y-%m-%d %H:%M')}"

        desc_str = f"\n*{task.description}*" if task.description else ""

        message_text = (
            f"⏰ **Task Reminder** (#{task.id})\n"
            f"**{task.title}**"
            f"{desc_str}\n"
            f"Priority: {p_badge}{due_str}"
        )

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Mark Done", "callback_data": f"td:{task.id}"},
                    {"text": "⏰ Snooze 1h", "callback_data": f"ts:{task.id}"},
                ]
            ]
        }

        from app.ingress import send_telegram_message
        await send_telegram_message(
            chat_id,
            message_text,
            reply_markup=reply_markup,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[SCHEDULER] failed to deliver task reminder {task_id}: {exc}")


def _add_task_to_scheduler(task: TaskItem):
    """Compile trigger for TaskItem and add to APScheduler."""
    if not task.is_reminder_active or task.status == "done" or task.reminder_type == "none":
        return

    job_id = f"task_{task.id}"
    try:
        tz = ZoneInfo(task.timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(dt_timezone.utc)

    if task.reminder_type == "once" and task.reminder_time:
        rem_time = task.reminder_time
        if rem_time.tzinfo is None:
            rem_time = rem_time.replace(tzinfo=tz)
        if rem_time > now:
            trigger = DateTrigger(run_date=rem_time)
            scheduler.add_job(
                _execute_task_reminder,
                trigger=trigger,
                args=[task.id, task.user_id],
                id=job_id,
                replace_existing=True,
            )
    elif task.reminder_type == "recurring" and task.cron_expression:
        try:
            trigger = CronTrigger.from_crontab(task.cron_expression, timezone=tz)
            scheduler.add_job(
                _execute_task_reminder,
                trigger=trigger,
                args=[task.id, task.user_id],
                id=job_id,
                replace_existing=True,
            )
        except Exception as exc:
            print(f"[SCHEDULER] Invalid cron expression for task {task.id}: {exc}")


def remove_task_reminder(task_id: int):
    """Remove a task's reminder from APScheduler."""
    job_id = f"task_{task_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def snooze_task_reminder(task_id: int, user_id: int, minutes: int = 60) -> bool:
    """Snooze a task reminder by N minutes."""
    async with async_session_factory() as session:
        task = (
            await session.execute(
                select(TaskItem).where(TaskItem.id == task_id, TaskItem.user_id == user_id)
            )
        ).scalar_one_or_none()
        if not task:
            return False

        now = datetime.now(dt_timezone.utc)
        snoozed_time = now + timedelta(minutes=minutes)
        task.reminder_type = "once"
        task.reminder_time = snoozed_time
        task.is_reminder_active = True
        session.add(task)
        await session.commit()

        # Schedule immediate DateTrigger
        job_id = f"task_{task.id}"
        scheduler.add_job(
            _execute_task_reminder,
            trigger=DateTrigger(run_date=snoozed_time),
            args=[task.id, task.user_id],
            id=job_id,
            replace_existing=True,
        )
        return True


async def trigger_task_alert_now(task_id: int, user_id: int) -> bool:
    """Trigger a task reminder immediately (e.g. for testing)."""
    async with async_session_factory() as session:
        task = (
            await session.execute(
                select(TaskItem).where(TaskItem.id == task_id)
            )
        ).scalar_one_or_none()
        if not task:
            return False

    asyncio.create_task(_execute_task_reminder(task_id, task.user_id, is_test=True))
    return True


async def schedule_one_shot_reminder(
    user_id: int,
    message: str,
    run_date: datetime,
    timezone_str: str = "Asia/Singapore",
) -> TaskItem:
    """Schedule a one-off reminder via TaskItem and DateTrigger."""
    async with async_session_factory() as session:
        task = TaskItem(
            user_id=user_id,
            title=message[:200],
            description=None,
            status="todo",
            priority="medium",
            due_at=run_date,
            reminder_type="once",
            reminder_time=run_date,
            timezone=timezone_str,
            is_reminder_active=True,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        job_id = f"task_{task.id}"
        scheduler.add_job(
            _execute_task_reminder,
            trigger=DateTrigger(run_date=run_date),
            args=[task.id, task.user_id],
            id=job_id,
            replace_existing=True,
        )
        return task


async def delete_scheduled_job(job_id: int, user_id: int) -> bool:
    """Deactivate and remove a scheduled job or task reminder owned by the user."""
    deleted = False
    async with async_session_factory() as session:
        # 1. Check ScheduledJob
        result = await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.id == job_id,
                ScheduledJob.user_id == user_id,
            )
        )
        job = result.scalar_one_or_none()
        if job:
            job.is_active = False
            session.add(job)
            deleted = True
            if scheduler.get_job(str(job.id)):
                scheduler.remove_job(str(job.id))

        # 2. Check TaskItem
        t_res = await session.execute(
            select(TaskItem).where(
                TaskItem.id == job_id,
                TaskItem.user_id == user_id,
            )
        )
        task = t_res.scalar_one_or_none()
        if task:
            task.is_reminder_active = False
            session.add(task)
            deleted = True
            remove_task_reminder(task.id)

        if deleted:
            await session.commit()
        return deleted


async def _scheduled_email_expense_sweep():
    """Recurring sweep: scan Gmail for financial emails, auto-log expenses, notify the user."""
    from capabilities.expenses.tools import log_expenses_from_emails
    from capabilities.email.tools import search_email_messages

    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(UserCredential.provider == "gmail")
        )
        user_ids = list({cred.user_id for cred in result.scalars().all()})

        # Auto-cleanup any legacy transactions where merchant matched email footer disclaimers
        try:
            from core.models import ExpenseTransaction
            from sqlmodel import or_
            bogus_merchants = ["receiving this", "receiving this email", "receiving this email and any", "this email and any"]
            b_res = await session.execute(
                select(ExpenseTransaction).where(or_(*[ExpenseTransaction.merchant.ilike(f"%{bm}%") for bm in bogus_merchants]))
            )
            bogus_txs = b_res.scalars().all()
            for btx in bogus_txs:
                btx.merchant = "Email Receipt"
                session.add(btx)
            if bogus_txs:
                await session.commit()
        except Exception as clean_err:
            print(f"[SWEEP] disclaimer cleanup error: {clean_err}")

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
    global _watchdog_task
    if not scheduler.running:
        scheduler.start()
        await reconcile_jobs()
        try:
            scheduler.add_job(
                _scheduled_email_expense_sweep,
                trigger=CronTrigger.from_crontab(
                    "*/10 * * * *", timezone=ZoneInfo("Asia/Singapore")
                ),
                id="email_expense_sweep",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
                max_instances=1,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[SCHEDULER] failed to register email expense sweep: {exc}")
    if _watchdog_task is None or _watchdog_task.done():
        _watchdog_task = asyncio.create_task(_watchdog_loop())

async def shutdown_scheduler():
    """Shutdown APScheduler."""
    global _watchdog_task
    if _watchdog_task is not None:
        _watchdog_task.cancel()
        try:
            await asyncio.gather(_watchdog_task, return_exceptions=True)
        except Exception:  # noqa: BLE001
            pass
        _watchdog_task = None
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
    """Watchdog task: reconcile PostgreSQL ScheduledJob and TaskItem rows with Uvicorn memory."""
    async with async_session_factory() as session:
        result = await session.execute(select(ScheduledJob).where(ScheduledJob.is_active == True))
        active_jobs = result.scalars().all()
        for job in active_jobs:
            _add_job_to_scheduler(job)

        task_result = await session.execute(
            select(TaskItem).where(
                TaskItem.is_reminder_active == True,
                TaskItem.status == "todo",
            )
        )
        active_tasks = task_result.scalars().all()
        for task in active_tasks:
            _add_task_to_scheduler(task)

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
    """Return local timestamps for next_run_time of active jobs and task reminders."""
    job_info_list = []
    async with async_session_factory() as session:
        # 1. Scheduled recurring jobs
        result = await session.execute(
            select(ScheduledJob).where(ScheduledJob.user_id == user_id, ScheduledJob.is_active == True)
        )
        jobs = result.scalars().all()
        for job in jobs:
            aps_job = scheduler.get_job(str(job.id))
            aps_next = getattr(aps_job, "next_run_time", None) if aps_job else None
            next_run = aps_next.isoformat() if aps_next else None
            job_info_list.append({
                "job_id": job.id,
                "job_name": job.job_name,
                "cron_expression": job.cron_expression,
                "timezone": job.timezone,
                "next_run_time": next_run,
                "instruction_prompt": job.instruction_prompt,
                "type": "recurring",
            })

        # 2. One-time task reminders
        t_res = await session.execute(
            select(TaskItem).where(
                TaskItem.user_id == user_id,
                TaskItem.is_reminder_active == True,
                TaskItem.status == "todo",
            )
        )
        tasks = t_res.scalars().all()
        for task in tasks:
            job_key = f"task_{task.id}"
            aps_job = scheduler.get_job(job_key)
            aps_next = getattr(aps_job, "next_run_time", None) if aps_job else None
            next_run = aps_next.isoformat() if aps_next else (task.reminder_time.isoformat() if task.reminder_time else None)
            job_info_list.append({
                "job_id": task.id,
                "job_name": task.title,
                "cron_expression": "once",
                "timezone": task.timezone,
                "next_run_time": next_run,
                "instruction_prompt": task.title,
                "type": "once",
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
