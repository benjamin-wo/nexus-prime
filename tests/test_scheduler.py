import pytest
from core.scheduler import (
    start_scheduler,
    shutdown_scheduler,
    schedule_proactive_task,
    list_active_jobs,
    update_user_timezone,
    run_now,
    scheduler,
)
from core.db import async_session_factory
from core.models import UserProfile

@pytest.mark.asyncio
async def test_scheduler_lifecycle_and_jobs():
    await start_scheduler()
    try:
        # Create user profile first
        async with async_session_factory() as session:
            user = UserProfile(user_id=2001, telegram_chat_id=8001, current_timezone="UTC")
            session.add(user)
            await session.commit()

        job = await schedule_proactive_task(
            user_id=2001,
            job_name="morning_briefing",
            cron_expression="0 8 * * *",
            instruction_prompt="Good morning briefing",
        )
        assert job.id is not None

        jobs = await list_active_jobs(user_id=2001)
        assert len(jobs) >= 1
        assert any(j["job_name"] == "morning_briefing" for j in jobs)

        # Test dynamic timezone update
        tz_updated = await update_user_timezone(user_id=2001, new_timezone="America/New_York")
        assert tz_updated is True

        # Test run_now debug trigger
        db_job_id = jobs[0]["job_id"]
        triggered = await run_now(db_job_id)
        assert triggered is True
    finally:
        await shutdown_scheduler()
