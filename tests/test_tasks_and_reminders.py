from datetime import datetime, timedelta, timezone as dt_timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlmodel import select

from app.main import app
from core.db import async_session_factory
from core.models import UserProfile, TaskItem
from core.scheduler import (
    start_scheduler,
    shutdown_scheduler,
    _add_task_to_scheduler,
    remove_task_reminder,
    snooze_task_reminder,
    trigger_task_alert_now,
    scheduler,
)
from app.ingress import TelegramIngress


@pytest.mark.asyncio
async def test_task_model_and_scheduler_lifecycle():
    await start_scheduler()
    try:
        async with async_session_factory() as session:
            user = UserProfile(user_id=3001, telegram_chat_id=9001, current_timezone="Asia/Singapore")
            session.add(user)
            await session.commit()

            # 1. Create task with recurring reminder
            task_recurring = TaskItem(
                user_id=3001,
                title="Review sprint metrics",
                description="Weekly KPI audit",
                status="todo",
                priority="high",
                reminder_type="recurring",
                cron_expression="0 9 * * 1",
                timezone="Asia/Singapore",
                is_reminder_active=True,
            )
            session.add(task_recurring)
            await session.commit()
            await session.refresh(task_recurring)

        _add_task_to_scheduler(task_recurring)
        job_id = f"task_{task_recurring.id}"
        aps_job = scheduler.get_job(job_id)
        assert aps_job is not None

        # 2. Test snoozing task
        snoozed = await snooze_task_reminder(task_recurring.id, user_id=3001, minutes=30)
        assert snoozed is True

        # 3. Test triggering alert immediately
        alert_sent = await trigger_task_alert_now(task_recurring.id, user_id=3001)
        assert alert_sent is True

        # 4. Test removing reminder
        remove_task_reminder(task_recurring.id)
        assert scheduler.get_job(job_id) is None
    finally:
        await shutdown_scheduler()


@pytest.mark.asyncio
async def test_telegram_callback_task_done_and_snooze():
    async with async_session_factory() as session:
        user = UserProfile(user_id=3002, telegram_chat_id=9002, current_timezone="Asia/Singapore")
        session.add(user)
        await session.commit()

        task = TaskItem(
            user_id=3002,
            title="Clean coffee machine",
            status="todo",
            priority="medium",
            reminder_type="once",
            reminder_time=datetime.now(dt_timezone.utc) + timedelta(hours=2),
            timezone="Asia/Singapore",
            is_reminder_active=True,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    ingress = TelegramIngress()

    # 1. Test snooze callback (ts:<id>)
    cb_snooze_payload = {
        "id": "cb_query_123",
        "from": {"id": 3002},
        "message": {"chat": {"id": 9002}},
        "data": f"ts:{task_id}",
    }
    snooze_res = await ingress.handle_callback_query(cb_snooze_payload)
    assert snooze_res["status"] == "ok"
    assert snooze_res["action"] == "task_snoozed"

    # 2. Test done callback (td:<id>)
    cb_done_payload = {
        "id": "cb_query_124",
        "from": {"id": 3002},
        "message": {"chat": {"id": 9002}},
        "data": f"td:{task_id}",
    }
    done_res = await ingress.handle_callback_query(cb_done_payload)
    assert done_res["status"] == "ok"
    assert done_res["action"] == "task_completed"

    # Verify DB state
    async with async_session_factory() as session:
        updated_task = (await session.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )).scalar_one()
        assert updated_task.status == "done"
        assert updated_task.is_reminder_active is False
        assert updated_task.completed_at is not None

    # 3. Test slash command /tasks
    slash_res = await ingress.handle_slash_command("/tasks", user_id=3002)
    assert slash_res is not None
    assert slash_res["status"] == "ok"


@pytest.mark.asyncio
async def test_dashboard_tasks_api():
    async with async_session_factory() as session:
        user = UserProfile(user_id=3003, telegram_chat_id=9003, current_timezone="Asia/Singapore")
        session.add(user)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /tasks (empty list initially)
        res_get = await client.get("/api/dashboard/tasks?user_id=3003")
        assert res_get.status_code == 200
        data_get = res_get.json()
        assert data_get["status"] == "ok"
        assert isinstance(data_get["tasks"], list)

        # 2. POST /tasks
        new_task_payload = {
            "title": "Buy concert tickets",
            "description": "Presale starts at 10am",
            "priority": "high",
            "due_at": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            "reminder_type": "once",
            "reminder_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "timezone": "Asia/Singapore",
            "user_id": 3003,
        }
        res_create = await client.post("/api/dashboard/tasks", json=new_task_payload)
        assert res_create.status_code == 200
        data_create = res_create.json()
        assert data_create["status"] == "ok"
        task_id = data_create["task"]["id"]
        assert data_create["task"]["title"] == "Buy concert tickets"
        assert data_create["task"]["priority"] == "high"

        # 3. PATCH /tasks/{id} (toggle status to done)
        res_patch = await client.patch(f"/api/dashboard/tasks/{task_id}", json={"status": "done"})
        assert res_patch.status_code == 200
        data_patch = res_patch.json()
        assert data_patch["task"]["status"] == "done"
        assert data_patch["task"]["completed_at"] is not None

        # 4. POST /tasks/{id}/test_alert
        res_alert = await client.post(f"/api/dashboard/tasks/{task_id}/test_alert")
        assert res_alert.status_code == 200
        assert res_alert.json()["status"] == "ok"

        # 5. POST /tasks/{id}/snooze
        res_snooze = await client.post(f"/api/dashboard/tasks/{task_id}/snooze?minutes=30")
        assert res_snooze.status_code == 200
        assert res_snooze.json()["snoozed"] is True

        # 6. DELETE /tasks/{id}
        res_del = await client.delete(f"/api/dashboard/tasks/{task_id}")
        assert res_del.status_code == 200
        assert res_del.json()["deleted_id"] == task_id
