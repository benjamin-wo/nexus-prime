import pytest
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo
from capabilities.reminders.tools import parse_reminder_request, _regex_parse_reminder
from core.scheduler import schedule_one_shot_reminder, list_active_jobs, delete_scheduled_job


def test_regex_reminder_parser_relative_minutes():
    """Verify relative minute parsing."""
    res = _regex_parse_reminder("remind me in 1 minute to check the oven")
    assert res is not None
    assert res["action"] == "create"
    assert res["reminder_type"] == "once"
    assert res["delay_seconds"] == 60
    assert res["message"] == "check the oven"


def test_regex_reminder_parser_relative_short():
    """Verify short unit syntax."""
    res = _regex_parse_reminder("remind me in 5 mins to call mom")
    assert res is not None
    assert res["action"] == "create"
    assert res["reminder_type"] == "once"
    assert res["delay_seconds"] == 300
    assert res["message"] == "call mom"


def test_regex_reminder_parser_message_before_time():
    """Verify message placed before time expression."""
    res = _regex_parse_reminder("remind me to turn off stove in 10 minutes")
    assert res is not None
    assert res["action"] == "create"
    assert res["reminder_type"] == "once"
    assert res["delay_seconds"] == 600
    assert res["message"] == "turn off stove"


def test_regex_reminder_parser_recurring():
    """Verify recurring shortcut parsing."""
    res = _regex_parse_reminder("remind me to drink water every 2 hours")
    assert res is not None
    assert res["action"] == "create"
    assert res["reminder_type"] == "recurring"
    assert res["cron"] == "0 */2 * * *"


def test_regex_reminder_parser_list_and_delete():
    """Verify list and delete actions."""
    res_list = _regex_parse_reminder("show all my reminders")
    assert res_list is not None
    assert res_list["action"] == "list"

    res_del = _regex_parse_reminder("delete reminder 42")
    assert res_del is not None
    assert res_del["action"] == "delete"
    assert res_del["job_id"] == 42


def test_has_recurrence_keyword():
    """Only explicit repetition language permits eternal recurring jobs."""
    from capabilities.reminders.tools import has_recurrence_keyword

    assert has_recurrence_keyword("remind me to text my wife every day at 10am")
    assert has_recurrence_keyword("drink water every 2 hours")
    assert has_recurrence_keyword("stretch weekdays at 7am")
    assert has_recurrence_keyword("take pills each morning")
    assert not has_recurrence_keyword("remind me at 10:01 am to text my wife")
    assert not has_recurrence_keyword("give my friends entry to my condo")


def test_next_occurrence_delay_deterministic():
    """Absolute wall-clock times resolve to a sane one-shot delay."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from capabilities.reminders.tools import next_occurrence_delay_seconds

    tz = ZoneInfo("Asia/Singapore")
    now = datetime.now(tz)
    target = now.replace(hour=3, minute=33, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    expected = int((target - now).total_seconds())

    got = next_occurrence_delay_seconds("ping me at 3:33 am tomorrow-ish", "Asia/Singapore")
    assert got is not None
    assert abs(got - max(expected, 60)) <= 5


def test_downgrade_ghost_recurring():
    """LLM 'recurring' verdicts without repetition language must never become daily crons."""
    from capabilities.reminders.tools import _downgrade_ghost_recurring

    parsed = {
        "action": "create",
        "reminder_type": "recurring",
        "message": "text my wife",
        "cron": "1 10 * * *",
        "timezone": "Asia/Singapore",
    }
    downgraded = _downgrade_ghost_recurring(parsed, "remind me at 10:01 am to text my wife")
    assert downgraded["action"] == "create"
    assert downgraded["reminder_type"] == "once"
    assert downgraded["cron"] is None
    assert downgraded["delay_seconds"] >= 60

    dropped = _downgrade_ghost_recurring(parsed, "text my wife")
    assert dropped["action"] is None


@pytest.mark.asyncio
async def test_schedule_and_list_one_shot_reminder():
    """Verify scheduling a one-shot reminder via TaskItem and DateTrigger."""
    user_id = 99123
    run_date = datetime.now(dt_timezone.utc)
    task = await schedule_one_shot_reminder(
        user_id=user_id,
        message="Check oven timer",
        run_date=run_date,
        timezone_str="Asia/Singapore",
    )
    assert task.id is not None
    assert task.title == "Check oven timer"
    assert task.reminder_type == "once"

    # List active jobs
    jobs = await list_active_jobs(user_id=user_id)
    assert any(j["job_id"] == task.id and j["type"] == "once" for j in jobs)

    # Delete
    deleted = await delete_scheduled_job(task.id, user_id)
    assert deleted is True


@pytest.mark.asyncio
async def test_create_one_time_reminder_tool_execution():
    """orchestrator/router.py's ReminderPlugin (deleted) used to parse
    "in one minute" into delay_seconds itself via parse_reminder_request
    before calling schedule_one_shot_reminder -- the agent now does that
    parsing step itself and calls create_one_time_reminder directly with a
    structured delay_seconds, so this exercises the tool with that
    already-parsed input instead of the natural-language sentence."""
    from capabilities.reminders.tools import create_one_time_reminder

    reply = await create_one_time_reminder.ainvoke({
        "user_id": 149917165,
        "message": "take out the trash",
        "delay_seconds": 60,
        "timezone": "Asia/Singapore",
    })
    assert "Reminder set" in reply
    assert "1 minute" in reply or "take out the trash" in reply


@pytest.mark.asyncio
async def test_create_recurring_reminder_tool_execution():
    from capabilities.reminders.tools import create_recurring_reminder

    reply = await create_recurring_reminder.ainvoke({
        "user_id": 4005,
        "message": "drink water",
        "cron_expression": "0 9 * * *",
        "timezone": "Asia/Singapore",
    })
    assert "Recurring reminder set" in reply
    assert "drink water" in reply


@pytest.mark.asyncio
async def test_task_reminder_utc_reconcile_and_delivery(monkeypatch):
    """Verify that task reminders stored in UTC survive reconciliation and deliver without NameError."""
    from core.scheduler import _add_task_to_scheduler, _execute_task_reminder, scheduler
    from core.models import TaskItem
    from datetime import datetime, timedelta, timezone as dt_tz

    user_id = 149917165
    now_utc = datetime.now(dt_tz.utc)
    future_utc_naive = (now_utc + timedelta(minutes=5)).replace(tzinfo=None)

    task = TaskItem(
        id=99999,
        user_id=user_id,
        title="take out the trash",
        status="todo",
        priority="medium",
        reminder_type="once",
        reminder_time=future_utc_naive,
        timezone="Asia/Singapore",
        is_reminder_active=True,
    )

    from core.scheduler import start_scheduler, shutdown_scheduler
    from core.db import async_session_factory
    async with async_session_factory() as session:
        session.add(task)
        await session.commit()
        await session.refresh(task)

    await start_scheduler()
    try:
        # Reconcile/add task to scheduler
        _add_task_to_scheduler(task)
        job = scheduler.get_job(f"task_{task.id}")
        assert job is not None

        # Test delivery
        sent_messages = []
        async def mock_send(chat_id, text, reply_markup=None):
            sent_messages.append((chat_id, text))
            return True

        monkeypatch.setattr("app.ingress.send_telegram_message", mock_send)
        await _execute_task_reminder(task_id=task.id, user_id=user_id, is_test=True)
        assert len(sent_messages) == 1
        assert "take out the trash" in sent_messages[0][1]
    finally:
        scheduler.remove_job(f"task_{task.id}")
        await shutdown_scheduler()

