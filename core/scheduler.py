import asyncio
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Optional, Dict, Any
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.background import fire_and_forget
from core.config import settings
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
        job_name = ""
        async with async_session_factory() as session:
            profile = (
                await session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                )
            ).scalar_one_or_none()
            chat_id = profile.telegram_chat_id if (profile and profile.telegram_chat_id and profile.telegram_chat_id != 999999) else None
            if not chat_id and user_id and user_id > 1000 and user_id != 999999:
                chat_id = user_id
            if not chat_id and getattr(settings, "admin_telegram_chat_id", None):
                try:
                    chat_id = int(settings.admin_telegram_chat_id)
                except Exception:
                    pass
            tz_name = profile.current_timezone if profile and profile.current_timezone else tz_name
            job_row = (
                await session.execute(
                    select(ScheduledJob).where(ScheduledJob.id == job_id)
                )
            ).scalar_one_or_none()
            job_name = job_row.job_name if job_row else ""
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

        if job_name == "daily_briefing":
            from capabilities.scheduled_content_delivery.tools import build_daily_briefing

            try:
                briefing = await build_daily_briefing()
            except Exception as exc:  # noqa: BLE001
                print(f"[SCHEDULER] briefing build failed for job {job_id}: {exc}")
                briefing = None
            if not briefing:
                print(f"[SCHEDULER] empty briefing for job {job_id}; skipping delivery")
                return
            await send_telegram_message(chat_id, f"📰 *Morning Briefing*\n\n{briefing}")
            return

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
            chat_id = profile.telegram_chat_id if (profile and profile.telegram_chat_id and profile.telegram_chat_id != 999999) else None
            if not chat_id and task.user_id and task.user_id > 1000 and task.user_id != 999999:
                chat_id = task.user_id
            if not chat_id and getattr(settings, "admin_telegram_chat_id", None):
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
        # In DB, reminder_time is stored as UTC naive timestamp
        if rem_time.tzinfo is None:
            rem_time = rem_time.replace(tzinfo=dt_timezone.utc)
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
        snoozed_time_utc = now + timedelta(minutes=minutes)
        db_snooze = snoozed_time_utc.replace(tzinfo=None)
        task.reminder_type = "once"
        task.reminder_time = db_snooze
        task.is_reminder_active = True
        session.add(task)
        await session.commit()

        # Schedule immediate DateTrigger
        job_id = f"task_{task.id}"
        scheduler.add_job(
            _execute_task_reminder,
            trigger=DateTrigger(run_date=snoozed_time_utc),
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

    fire_and_forget(_execute_task_reminder(task_id, task.user_id, is_test=True))
    return True


async def schedule_one_shot_reminder(
    user_id: int,
    message: str,
    run_date: datetime,
    timezone_str: str = "Asia/Singapore",
) -> TaskItem:
    """Schedule a one-off reminder via TaskItem and DateTrigger."""
    # Convert run_date to naive UTC for safe DB storage in TIMESTAMP WITHOUT TIME ZONE
    from datetime import timezone as dt_tz
    if run_date.tzinfo is not None:
        db_dt = run_date.astimezone(dt_tz.utc).replace(tzinfo=None)
    else:
        db_dt = run_date

    async with async_session_factory() as session:
        task = TaskItem(
            user_id=user_id,
            title=message[:200],
            description=None,
            status="todo",
            priority="medium",
            due_at=db_dt,
            reminder_type="once",
            reminder_time=db_dt,
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


EMAIL_DIGEST_START_HOUR = 9
EMAIL_DIGEST_END_HOUR = 21


def _utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize a stored timestamp to naive UTC for PostgreSQL timestamp columns."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(dt_timezone.utc).replace(tzinfo=None)
    return value


def _format_digest_transaction_date(value: datetime, tz: ZoneInfo) -> str:
    """Render a stored UTC transaction timestamp in the user's local timezone."""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=dt_timezone.utc)
    return aware.astimezone(tz).strftime("%a, %d %b %Y at %I:%M %p")


async def _send_daily_email_expense_digest(
    user_id: int,
    now_utc: Optional[datetime] = None,
) -> bool:
    """Send at most one consolidated expense digest per local day.

    The ingestion sweep remains frequent for freshness, but this boundary keeps
    routine polling activity out of Telegram and prevents overnight alerts.
    """
    from core.models import ExpenseTransaction
    from app.ingress import send_telegram_message

    now_utc = now_utc or datetime.now(dt_timezone.utc)
    now_naive = now_utc.replace(tzinfo=None)

    async with async_session_factory() as session:
        profile = (
            await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        if not profile or not profile.telegram_chat_id:
            return False

        try:
            user_tz = ZoneInfo(profile.current_timezone or "Asia/Singapore")
        except Exception:
            user_tz = ZoneInfo("Asia/Singapore")
        local_now = now_utc.astimezone(user_tz)

        # Never send routine summaries overnight. If the app missed 09:00,
        # the first sweep before 21:00 still delivers that day's digest.
        if not (EMAIL_DIGEST_START_HOUR <= local_now.hour < EMAIL_DIGEST_END_HOUR):
            return False

        last_digest = profile.last_email_digest_at
        last_digest_utc = (
            last_digest.replace(tzinfo=dt_timezone.utc)
            if last_digest and last_digest.tzinfo is None
            else last_digest
        )
        if last_digest_utc and last_digest_utc.astimezone(user_tz).date() >= local_now.date():
            return False

        if last_digest_utc:
            since = _utc_naive(last_digest_utc)
        else:
            local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            since = local_start.astimezone(dt_timezone.utc).replace(tzinfo=None)

        transactions = (
            await session.execute(
                select(ExpenseTransaction)
                .where(
                    ExpenseTransaction.user_id == user_id,
                    ExpenseTransaction.logged_at.is_not(None),
                    ExpenseTransaction.logged_at > since,
                    ExpenseTransaction.logged_at <= now_naive,
                )
                .order_by(ExpenseTransaction.logged_at, ExpenseTransaction.id)
                .limit(50)
            )
        ).scalars().all()
        if not transactions:
            # Do not mark an empty digest as sent: a transaction arriving later
            # that same day should still be included.
            return False

        chat_id = profile.telegram_chat_id

    lines = [
        f"📬 **Daily expense digest — {local_now.strftime('%a, %d %b')}**",
        f"Auto-logged {len(transactions)} expense{'s' if len(transactions) != 1 else ''} from email:",
    ]
    high_value_buttons = []
    for tx in transactions:
        lines.append(
            f"• {tx.currency} {tx.amount:.2f} — {tx.merchant}"
            f" ({_format_digest_transaction_date(tx.date, user_tz)})"
        )
        if tx.amount >= 50.0:
            high_value_buttons.append([
                {
                    "text": f"👥 Split {tx.currency} {tx.amount:.2f} — {tx.merchant}",
                    "callback_data": f"sb:{tx.id}",
                }
            ])
    if len(transactions) == 50:
        lines.append("…showing the first 50; use /expenses for the complete list.")
    if high_value_buttons:
        lines.append("\n💡 Split a group expense with the buttons below.")

    sent = await send_telegram_message(
        chat_id,
        "\n".join(lines),
        reply_markup={"inline_keyboard": high_value_buttons} if high_value_buttons else None,
    )
    if not sent:
        return False

    # Mark only after Telegram accepts the message. The timestamp is persisted
    # so a process restart cannot send the same digest again.
    async with async_session_factory() as session:
        profile = (
            await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        if profile:
            profile.last_email_digest_at = now_naive
            session.add(profile)
            await session.commit()
    return True


async def _scheduled_email_expense_sweep():
    """Recurring sweep: scan connected mailboxes (Gmail + Outlook) for financial emails, auto-log expenses, notify the user."""
    from capabilities.expenses.tools import log_expenses_from_emails
    from capabilities.email.tools import search_email_messages
    from capabilities.email.providers import PROVIDER_REGISTRY

    email_providers = list(PROVIDER_REGISTRY.keys())

    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(UserCredential.provider.in_(email_providers))
        )
        email_creds = list(result.scalars().all())
        user_ids = sorted({cred.user_id for cred in email_creds})

        # Environment-configured Outlook mailbox (no per-user credential row):
        # still sweep it under the admin/primary user so those receipts get logged.
        if settings.outlook_email and settings.outlook_app_password:
            has_outlook_cred = any(cred.provider == "outlook" for cred in email_creds)
            if not has_outlook_cred and getattr(settings, "admin_telegram_chat_id", None):
                try:
                    user_ids.append(int(settings.admin_telegram_chat_id))
                except (TypeError, ValueError):
                    pass
        user_ids = sorted(set(user_ids))

        # Auto-cleanup any legacy bogus transactions (ref numbers, years, footer disclaimer merchants)
        try:
            from core.models import ExpenseTransaction
            from sqlmodel import or_
            # 1. Purge absurd numbers (ref IDs, phone numbers, years logged as prices)
            bogus_res = await session.execute(
                select(ExpenseTransaction).where(
                    or_(
                        ExpenseTransaction.amount >= 100000.0,
                        (ExpenseTransaction.amount.in_([2024.0, 2025.0, 2026.0, 2027.0]) & ExpenseTransaction.merchant.in_(["Apple", "PayLah! Alerts", "Email Receipt", "Unknown"])),
                        (ExpenseTransaction.merchant == "PayLah! Alerts") & (ExpenseTransaction.amount == 21.0),
                    )
                )
            )
            for bad_tx in bogus_res.scalars().all():
                await session.delete(bad_tx)

            # 2. Fix legacy disclaimer words in merchant field
            bogus_merchants = ["receiving this", "receiving this email", "receiving this email and any", "this email and any"]
            b_res = await session.execute(
                select(ExpenseTransaction).where(or_(*[ExpenseTransaction.merchant.ilike(f"%{bm}%") for bm in bogus_merchants]))
            )
            for btx in b_res.scalars().all():
                btx.merchant = "Email Receipt"
                session.add(btx)

            await session.commit()
        except Exception as clean_err:
            print(f"[SWEEP] legacy transaction cleanup error: {clean_err}")

    for user_id in user_ids:
        try:
            emails = await search_email_messages.ainvoke({"user_id": user_id})
            # Ingestion is silent. A single local-time digest consolidates
            # everything logged since the previous digest.
            if emails:
                await log_expenses_from_emails.ainvoke(
                    {"user_id": user_id, "emails": emails, "notify": False}
                )
            await _send_daily_email_expense_digest(user_id)
        except Exception as exc:  # noqa: BLE001 - one user's failure must not block the sweep
            print(f"[SWEEP] error for user {user_id}: {exc}")


# A turn is deliberately unbounded (see agent_loop.MAX_TOOL_ROUNDS), so this
# is not a limit -- nothing is cancelled. It is the point past which a still-
# running turn is better explained by a wedge than by real work, and is worth
# raising as an incident.
WEDGED_CHAT_SECONDS = 300.0


async def _run_operations_health_sweep():
    """Every 15 minutes, probe service health and record failures as GitHub issues.

    Detects the same 'operational rot' (missing provider credentials, unreachable
    DB, broken integrations) over and over, but `record_operation_event` dedups by
    fingerprint so a failing probe only keeps one open issue with recurrence comments.
    """
    from core.audit import record_operation_event

    probes: List[Dict[str, Any]] = []

    # 1. OAuth provider credential presence (the "Outlook not configured" class)
    provider_envs = {
        "gmail": ("google_client_id", "google_client_secret"),
        "outlook": ("microsoft_client_id", "microsoft_client_secret"),
        "maps": ("google_maps_api_key",),
        "lta": ("lta_account_key",),
    }
    for name, keys in provider_envs.items():
        missing = [k for k in keys if not getattr(settings, k, None)]
        if missing:
            probes.append({
                "subsystem": name,
                "severity": "P3",
                "error_context": f"Provider {name} OAuth credentials are not configured (missing: {', '.join(missing)}).",
                "detection_source": "operations_health",
                "fingerprint": f"env_missing_{name}_credentials",
            })

    # 2. Database reachability
    try:
        async with async_session_factory() as session:
            await session.execute(select(ScheduledJob).limit(1))
    except Exception as exc:  # noqa: BLE001
        probes.append({
            "type": "database",
            "severity": "P1",
            "error_context": f"Database unreachable during operations health sweep: {type(exc).__name__}: {exc}",
            "detection_source": "operations_health",
            "fingerprint": "db_unreachable",
        })

    # 3. Scheduler status
    if not (scheduler.running if hasattr(scheduler, "running") else False):
        probes.append({
            "subsystem": "scheduler",
            "severity": "P1",
            "error_context": "APScheduler is not running.",
            "detection_source": "operations_health",
            "fingerprint": "scheduler_not_running",
        })

    # 4. Wedged chats -- a turn holding its per-chat lock far longer than any
    #    real turn should. This is the probe that would have caught the
    #    silent-reply outage: every config check below stayed green while the
    #    bot answered nobody, because they check whether the service is
    #    CONFIGURED, never whether it is WORKING.
    #    Imported lazily: app.ingress imports from this module.
    try:
        from app.ingress import TelegramIngress

        for wedged in TelegramIngress.wedged_chats(WEDGED_CHAT_SECONDS):
            probes.append({
                "subsystem": "agent_loop",
                "severity": "P1",
                "error_context": (
                    f"Chat {wedged['chat_id']} has held its turn lock for "
                    f"{wedged['held_seconds']:.0f}s. Its turn is wedged and every "
                    "subsequent message from that chat is queued behind it."
                ),
                "detection_source": "operations_health",
                "fingerprint": f"wedged_chat_{wedged['chat_id']}",
            })
    except Exception as exc:  # noqa: BLE001 - a probe must never kill the sweep
        print(f"[OPS SWEEP] wedged-chat probe failed: {exc}")

    # 5. Telegram bot token presence (the ingress can't start at all without it)
    if not settings.telegram_bot_token or settings.telegram_bot_token == "test_bot_token":
        probes.append({
            "subsystem": "telegram",
            "severity": "P1",
            "error_context": "TELEGRAM_BOT_TOKEN is not configured (or still the local test default).",
            "detection_source": "operations_health",
            "fingerprint": "env_missing_telegram_bot_token",
        })

    for probe in probes:
        try:
            await record_operation_event(
                subsystem=probe.get("subsystem", probe.get("type", "operations")),
                error_context=probe["error_context"],
                detection_source=probe.get("detection_source", "operations_health"),
                fingerprint=probe.get("fingerprint"),
                severity=probe.get("severity", "P2"),
            )
        except Exception as exc:  # noqa: BLE001 - a probe failure must not kill the sweep
            print(f"[OPS SWEEP] failed to record probe: {exc}")

    print(f"[OPS SWEEP] completed with {len(probes)} issue(s) recorded.")


async def start_scheduler():
    """Start the APScheduler instance and reconcile DB jobs."""
    global _watchdog_task
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if scheduler.running and getattr(scheduler, "_eventloop", None) is not None:
        if getattr(scheduler, "_eventloop", None).is_closed() or (current_loop and getattr(scheduler, "_eventloop", None) != current_loop):
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass

    if not scheduler.running:
        if current_loop:
            scheduler._eventloop = current_loop
        scheduler.start()
        await reconcile_jobs()
        for name, cron, func in (
            ("email_expense_sweep", "*/10 * * * *", _scheduled_email_expense_sweep),
            ("operations_health_sweep", "*/15 * * * *", _run_operations_health_sweep),
        ):
            try:
                scheduler.add_job(
                    func,
                    trigger=CronTrigger.from_crontab(cron, timezone=ZoneInfo("Asia/Singapore")),
                    id=name,
                    replace_existing=True,
                    misfire_grace_time=3600,
                    coalesce=True,
                    max_instances=1,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[SCHEDULER] failed to register {name}: {exc}")
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
