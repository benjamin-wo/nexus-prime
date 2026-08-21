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
async def test_reminders_plugin_one_minute_execution():
    """Verify ReminderPlugin.execute processes relative 1-minute reminders without NameError."""
    from orchestrator.router import ReminderPlugin
    from orchestrator.state import AssistantState
    from langchain_core.messages import HumanMessage

    plugin = ReminderPlugin()
    state = AssistantState(
        messages=[HumanMessage(content="can you remind me in one minute to take out the trash")],
        user_id=149917165,
        user_profile={"user_id": 149917165, "current_timezone": "Asia/Singapore"},
    )
    res = await plugin.execute(state)
    assert res.message is not None
    assert "Reminder set" in res.message.content
    assert "1 minute" in res.message.content or "take out the trash" in res.message.content

