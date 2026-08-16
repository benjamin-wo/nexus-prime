import pytest
from datetime import datetime
from sqlmodel import select
from core.db import async_session_factory, init_db
from core.models import UserProfile, WhiteboardProject, WhiteboardBlock, TaskItem, ExpenseTransaction
from app.dashboard_api import (
    list_whiteboards,
    create_whiteboard,
    get_whiteboard_details,
    update_block,
    escalate_block_to_task,
    escalate_block_to_expense,
    whiteboard_ai_copilot,
    CreateWhiteboardRequest,
    CreateBlockRequest,
    UpdateBlockRequest,
    EscalateBlockTaskRequest,
    EscalateBlockExpenseRequest,
    WhiteboardAiPromptRequest,
)
from app.ingress import TelegramIngress


@pytest.fixture(autouse=True)
async def ensure_db():
    await init_db()


@pytest.mark.asyncio
async def test_whiteboard_models_and_seeding():
    async with async_session_factory() as session:
        user = UserProfile(user_id=7001, telegram_chat_id=17001, current_timezone="Asia/Singapore")
        session.add(user)
        await session.commit()

    # 1. Test auto-seeding on empty list
    res = await list_whiteboards(user_id=7001)
    assert res["status"] == "ok"
    assert len(res["projects"]) >= 3
    
    trip_proj = next(p for p in res["projects"] if p["category"] == "trip")
    assert "Tokyo" in trip_proj["title"]

    # 2. Test fetching details & blocks
    detail = await get_whiteboard_details(trip_proj["id"])
    assert detail["status"] == "ok"
    blocks = detail["blocks"]
    assert len(blocks) >= 4

    types = {b["block_type"] for b in blocks}
    assert "comparison" in types
    assert "checklist" in types
    assert "itinerary" in types
    assert "budget" in types


@pytest.mark.asyncio
async def test_whiteboard_template_creation_and_block_crud():
    # 1. Create a party planner board from template
    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(
            title="Summer Yacht Party",
            emoji_icon="🛥️",
            category="event",
            summary="Weekend sunset cruise celebration",
            template="event",
        ),
        user_id=7001,
    )
    assert create_res["status"] == "ok"
    proj_id = create_res["project"]["id"]

    # Verify template populated blocks
    detail = await get_whiteboard_details(proj_id)
    assert len(detail["blocks"]) >= 2
    comp_block = next(b for b in detail["blocks"] if b["block_type"] == "comparison")
    assert "Venue" in comp_block["title"]

    # 2. Update block option winner
    options = comp_block["content_payload"]["options"]
    options[0]["is_winner"] = False
    options[1]["is_winner"] = True
    update_res = await update_block(
        block_id=comp_block["id"],
        payload=UpdateBlockRequest(
            content_payload={"options": options},
        ),
    )
    assert update_res["status"] == "ok"


@pytest.mark.asyncio
async def test_whiteboard_escalation_to_task_and_expense():
    # Create test project and blocks
    async with async_session_factory() as session:
        proj = WhiteboardProject(
            user_id=7001,
            title="Bali Getaway",
            emoji_icon="🌴",
            category="trip",
            summary="Villa & beach retreat",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(proj)
        await session.commit()
        await session.refresh(proj)

        b_task = WhiteboardBlock(
            project_id=proj.id,
            section_name="Accommodations",
            block_type="comparison",
            title="Seminyak Villa Booking",
            content_payload={"options": []},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        b_exp = WhiteboardBlock(
            project_id=proj.id,
            section_name="Budget",
            block_type="budget",
            title="Villa Deposit",
            content_payload={"currency": "SGD", "items": [{"name": "Deposit", "cost": 450}]},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add_all([b_task, b_exp])
        await session.commit()
        await session.refresh(b_task)
        await session.refresh(b_exp)

    # 1. Escalate to Task
    esc_task_res = await escalate_block_to_task(
        block_id=b_task.id,
        payload=EscalateBlockTaskRequest(
            title="Book Seminyak Villa before promotion ends",
            due_at="2026-08-25T18:00:00Z",
            reminder_type="once",
            priority="high",
        ),
    )
    assert esc_task_res["status"] == "ok"
    assert esc_task_res["task_id"] is not None

    async with async_session_factory() as session:
        created_task = (await session.execute(
            select(TaskItem).where(TaskItem.id == esc_task_res["task_id"])
        )).scalar_one()
        assert created_task.title == "Book Seminyak Villa before promotion ends"
        assert created_task.priority == "high"

    # 2. Escalate to Expense
    esc_exp_res = await escalate_block_to_expense(
        block_id=b_exp.id,
        payload=EscalateBlockExpenseRequest(
            merchant="Seminyak Luxury Villas",
            amount=450.0,
            category="Travel",
            currency="SGD",
        ),
    )
    assert esc_exp_res["status"] == "ok"
    assert esc_exp_res["amount"] == 450.0

    async with async_session_factory() as session:
        created_exp = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == esc_exp_res["expense_id"])
        )).scalar_one()
        assert created_exp.merchant == "Seminyak Luxury Villas"
        assert created_exp.amount == 450.0


@pytest.mark.asyncio
async def test_whiteboard_ai_copilot_and_telegram_ingress():
    # Create project
    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(
            title="Tokyo Coffee Tour",
            emoji_icon="☕",
            category="trip",
            template="blank",
        ),
        user_id=7001,
    )
    proj_id = create_res["project"]["id"]

    # 1. Test AI copilot generation
    ai_res = await whiteboard_ai_copilot(
        project_id=proj_id,
        payload=WhiteboardAiPromptRequest(
            prompt="Shortlist 3 specialty coffee roasters in Shibuya",
            section_name="☕ Cafe Shortlist",
        ),
    )
    assert ai_res["status"] == "ok"
    gen_block = ai_res["generated_block"]
    assert gen_block["block_type"] == "comparison"
    assert "Shortlist" in gen_block["title"]

    # 2. Test Telegram /boards slash command
    ingress = TelegramIngress()
    slash_res = await ingress.handle_slash_command("/boards", user_id=7001)
    assert slash_res is not None
    assert slash_res["status"] == "ok"
    assert len(slash_res["projects"]) >= 1

    # 3. Test Telegram pb: (pin to board) callback query
    cb_res = await ingress.handle_callback_query({
        "id": "cb_query_wb_1",
        "from": {"id": 7001},
        "message": {"chat": {"id": 17001}},
        "data": f"pb:{proj_id}",
    })
    assert cb_res["status"] == "ok"
    assert cb_res["action"] == "pinned_to_whiteboard"
