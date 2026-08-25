import json
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


@pytest.mark.asyncio
async def test_whiteboard_cover_endpoint_and_lifecycle():
    from app.dashboard_api import get_whiteboard_cover, delete_whiteboard, _cover_file_path, _build_imagen_prompt
    import os

    # 1. Create a board
    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(
            title="Kyoto Zen Gardens",
            emoji_icon="⛩️",
            category="trip",
            template="blank",
        ),
        user_id=8001,
    )
    proj_id = create_res["project"]["id"]
    assert create_res["project"]["cover_ready"] is False

    # 2. Query cover before file exists -> returns 202 {"status": "generating"}
    cover_res = await get_whiteboard_cover(project_id=proj_id)
    assert cover_res.status_code == 202

    # 3. Simulate cover file written to disk -> returns 200 FileResponse
    cover_path = _cover_file_path(proj_id)
    os.makedirs(os.path.dirname(cover_path), exist_ok=True)
    with open(cover_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake-cover-bytes")

    cover_res_ready = await get_whiteboard_cover(project_id=proj_id)
    assert cover_res_ready.media_type == "image/png"
    assert "max-age=86400" in cover_res_ready.headers.get("cache-control", "")
    assert "ETag" in cover_res_ready.headers

    prompt = _build_imagen_prompt("Kyoto Zen Gardens", "trip", "Autumn temple walk")
    assert "16:9" in prompt
    assert "260x150px" in prompt
    assert "not create a portrait poster" in prompt

    # 4. Delete board -> cover file is cleaned up
    del_res = await delete_whiteboard(project_id=proj_id)
    assert del_res["status"] == "ok"
    assert not os.path.exists(cover_path)


@pytest.mark.asyncio
async def test_whiteboard_llm_copilot_structured_generation(monkeypatch):
    """LLM-backed copilot creates validated structured cards and tracks sections."""
    from app import dashboard_api

    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(
            title="Lisbon Food Crawl",
            emoji_icon="🐙",
            category="trip",
            template="blank",
        ),
        user_id=7101,
    )
    proj_id = create_res["project"]["id"]

    llm_block = {
        "block_type": "checklist",
        "section_name": "Pastel de Nata Quest",
        "title": "Best natas in Alfama",
        "content_payload": {
            "items": [
                {"text": "Manteigaria — Chiado counter"},
                {"text": "Pasteis de Belem — the original"},
                {"text": "Fábrica da Nata"},
            ]
        },
    }

    async def fake_llm_generate(prompt, context):
        assert "Lisbon" in str(context.get("title"))
        return dashboard_api._validate_generated_block(llm_block)

    monkeypatch.setattr(dashboard_api, "_llm_generate_block_json", fake_llm_generate)

    ai_res = await whiteboard_ai_copilot(
        project_id=proj_id,
        payload=WhiteboardAiPromptRequest(prompt="find me the best pastel de nata"),
    )
    assert ai_res["status"] == "ok"
    assert ai_res["engine"] == "llm"
    gen = ai_res["generated_block"]
    assert gen["block_type"] == "checklist"
    assert gen["section_name"] == "Pastel de Nata Quest"
    assert all(item["checked"] is False for item in gen["content_payload"]["items"])
    assert gen["position_order"] > 0  # appended after existing blocks

    # New section must be tracked in the board's section order
    detail = await get_whiteboard_details(proj_id)
    assert "Pastel de Nata Quest" in detail["project"]["section_order"]


@pytest.mark.asyncio
async def test_whiteboard_copilot_explicit_research_creates_research_card(monkeypatch):
    """An explicit research request executes web search and stores structured findings."""
    from app import dashboard_api

    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(
            title="Bali Planning Research",
            emoji_icon="🌴",
            category="trip",
            template="blank",
        ),
        user_id=7111,
    )
    proj_id = create_res["project"]["id"]

    async def fake_research(prompt, context):
        assert "Bali Planning Research" in context["title"]
        return {
            "section_name": "🔍 Research",
            "block_type": "note",
            "title": "Research: fitness clubs in Canggu",
            "content_payload": {
                "topics": [{
                    "query": "fitness clubs in Canggu",
                    "summary": "Three current options with day passes.",
                    "sources": [{"title": "Canggu Fitness Guide", "url": "https://example.com/canggu"}],
                }],
                "markdown": "**fitness clubs in Canggu**\nSummary: Three current options with day passes.",
            },
        }

    monkeypatch.setattr(dashboard_api, "_research_whiteboard_prompt", fake_research)
    result = await whiteboard_ai_copilot(
        project_id=proj_id,
        payload=WhiteboardAiPromptRequest(prompt="Help me research fitness clubs in Canggu"),
    )

    assert result["engine"] == "research"
    generated = result["generated_block"]
    assert generated["section_name"] == "🔍 Research"
    assert generated["block_type"] == "note"
    assert generated["content_payload"]["topics"][0]["sources"][0]["url"] == "https://example.com/canggu"


@pytest.mark.asyncio
async def test_whiteboard_research_normalizes_source_images(monkeypatch):
    """Research search output includes compact source snippets and moodboard images."""
    from app import dashboard_api
    from capabilities.general import tools as general_tools

    class FakeSearchTool:
        async def ainvoke(self, payload):
            assert payload["include_images"] is True
            return (
                "Summary: Current options with practical day-pass details.\n"
                "- Official Bali Guide (https://example.com/guide): A useful overview.\n"
                "Image: https://images.example.com/guide.jpg"
            )

    monkeypatch.setattr(dashboard_api.settings, "tavily_api_key", "test-tavily-key")
    monkeypatch.setattr(general_tools, "search_web", FakeSearchTool())
    result = await dashboard_api._research_whiteboard_prompt(
        "research fitness clubs in Canggu",
        {
            "title": "Bali Planning",
            "category": "trip",
            "summary": "Friday daytime activity",
            "existing_sections": ["Day Plans"],
        },
    )

    assert result is not None
    topic = result["content_payload"]["topics"][0]
    assert topic["summary"] == "Current options with practical day-pass details."
    assert topic["sources"][0]["snippet"] == "A useful overview."
    assert topic["sources"][0]["image_url"] == "https://images.example.com/guide.jpg"


def test_validate_generated_block_rejects_garbage():
    """Malformed LLM output never reaches the board."""
    from app.dashboard_api import _validate_generated_block

    assert _validate_generated_block(None) is None
    assert _validate_generated_block("nope") is None
    assert _validate_generated_block({"block_type": "bogus", "title": "x", "content_payload": {}}) is None
    assert _validate_generated_block({"block_type": "comparison", "title": "x", "content_payload": {"options": []}}) is None
    # Multiple winners collapse to exactly one
    fixed = _validate_generated_block({
        "block_type": "comparison",
        "title": "Options",
        "content_payload": {
            "options": [
                {"name": "A", "is_winner": True},
                {"name": "B", "is_winner": True},
            ]
        },
    })
    assert fixed is not None
    winners = [o for o in fixed["content_payload"]["options"] if o["is_winner"]]
    assert len(winners) == 1


@pytest.mark.asyncio
async def test_whiteboard_section_ops_and_reorder():
    """Sections can be added, renamed, deleted; block/section order persists."""
    from app.dashboard_api import (
        add_block,
        add_section,
        rename_section,
        delete_section,
        reorder_whiteboard,
        SectionOpRequest,
        SectionRenameRequest,
        ReorderWhiteboardRequest,
        SectionReorderEntry,
    )

    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(title="Reorder Test Board", category="general", template="blank"),
        user_id=7201,
    )
    proj_id = create_res["project"]["id"]

    # 1. Add an empty section
    sec_res = await add_section(project_id=proj_id, payload=SectionOpRequest(name="Wishlist"))
    assert sec_res["status"] == "ok"
    assert "Wishlist" in sec_res["section_order"]

    # Duplicate section rejected
    from fastapi import HTTPException as _HTTPException
    with pytest.raises(_HTTPException) as exc_info:
        await add_section(project_id=proj_id, payload=SectionOpRequest(name="Wishlist"))
    assert exc_info.value.status_code == 409

    # 2. Add cards into two sections (auto-tracks new sections)
    b1 = await add_block(project_id=proj_id, payload=CreateBlockRequest(
        section_name="Ideas", block_type="note", title="First idea", content_payload={"markdown": "one"}))
    b2 = await add_block(project_id=proj_id, payload=CreateBlockRequest(
        section_name="Ideas", block_type="note", title="Second idea", content_payload={"markdown": "two"}))
    b3 = await add_block(project_id=proj_id, payload=CreateBlockRequest(
        section_name="Wishlist", block_type="note", title="Wish item", content_payload={"markdown": "wish"}))

    # 3. Reorder: move b2 before b1 and reorder sections
    reorder_res = await reorder_whiteboard(
        project_id=proj_id,
        payload=ReorderWhiteboardRequest(
            section_order=["Wishlist", "Ideas"],
            sections=[
                SectionReorderEntry(name="Ideas", block_ids=[b2["block"]["id"], b1["block"]["id"]]),
                SectionReorderEntry(name="Wishlist", block_ids=[b3["block"]["id"]]),
            ],
        ),
    )
    assert reorder_res["status"] == "ok"

    detail = await get_whiteboard_details(proj_id)
    blocks_by_title = {b["title"]: b for b in detail["blocks"]}
    assert blocks_by_title["Second idea"]["position_order"] < blocks_by_title["First idea"]["position_order"]
    assert detail["project"]["section_order"][0] == "Wishlist"
    assert blocks_by_title["Wish item"]["section_name"] == "Wishlist"

    # 4. Rename a section — blocks follow
    ren_res = await rename_section(
        project_id=proj_id,
        payload=SectionRenameRequest(old_name="Wishlist", new_name="Dream List"),
    )
    assert ren_res["status"] == "ok"
    detail = await get_whiteboard_details(proj_id)
    assert all(b["section_name"] != "Wishlist" for b in detail["blocks"])
    assert "Dream List" in detail["project"]["section_order"]

    # 5. Delete a section removes its cards
    del_sec = await delete_section(project_id=proj_id, name="Dream List")
    assert del_sec["status"] == "ok"
    assert del_sec["deleted_cards"] == 1
    detail = await get_whiteboard_details(proj_id)
    assert "Dream List" not in detail["project"]["section_order"]
    assert not any(b["section_name"] == "Dream List" for b in detail["blocks"])


@pytest.mark.asyncio
async def test_whiteboard_plugin_conversational_flow():
    """The chat capability can create boards, list them, summarize, and pin notes."""
    from orchestrator.router import WhiteboardPlugin
    from orchestrator.state import AssistantState
    from langchain_core.messages import HumanMessage

    plugin = WhiteboardPlugin()

    def make_state(text):
        return AssistantState(messages=[HumanMessage(content=text)], user_id=7301)

    # 1. Create board from natural language
    res = await plugin.execute(make_state("Plan my trip to Lisbon for the food scene"))
    assert "Created" in res.message.content
    assert "Trip to Lisbon" in res.message.content or "Lisbon" in res.message.content

    boards = await list_whiteboards(user_id=7301)
    board = next(p for p in boards["projects"] if "Lisbon" in p["title"])
    assert board["category"] == "trip"

    # 2. List boards
    res = await plugin.execute(make_state("show my boards"))
    assert "Your Planning Boards" in res.message.content
    assert "Lisbon" in res.message.content

    # 3. Pin a note to the board by name fragment
    res = await plugin.execute(make_state("pin try Time Out Market on my Lisbon board"))
    assert "Pinned" in res.message.content
    detail = await get_whiteboard_details(board["id"])
    pinned = [b for b in detail["blocks"] if b["title"].startswith("try Time Out Market")]
    assert len(pinned) >= 1

    # 4. Board summary
    res = await plugin.execute(make_state("what's on my Lisbon board?"))
    assert "Lisbon" in res.message.content
    assert "try Time Out Market" in res.message.content


@pytest.mark.asyncio
async def test_telegram_pin_callback_with_pending_content():
    """pb:<project>:<token> writes the exact captured content as a real card."""
    from app.ingress import TelegramIngress, register_pending_pin

    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(title="Pin Callback Board", category="general", template="blank"),
        user_id=7401,
    )
    proj_id = create_res["project"]["id"]

    token = register_pending_pin(
        project_id=proj_id,
        user_id=7401,
        title="Ramen at Ichiran",
        markdown="Try the ramen at Ichiran, Shibuya",
    )

    ingress = TelegramIngress()
    cb_res = await ingress.handle_callback_query({
        "id": "cb_query_wb_pin",
        "from": {"id": 7401},
        "message": {"chat": {"id": 17401}},
        "data": f"pb:{proj_id}:{token}",
    })
    assert cb_res["status"] == "ok"
    assert cb_res["action"] == "pinned_to_whiteboard"
    assert cb_res.get("block_id")

    detail = await get_whiteboard_details(proj_id)
    block = next(b for b in detail["blocks"] if b["id"] == cb_res["block_id"])
    assert block["title"] == "Ramen at Ichiran"
    assert "Ichiran" in json.dumps(block["content_payload"])

    # Token is single-use: replaying creates the honest placeholder instead
    cb_replay = await ingress.handle_callback_query({
        "id": "cb_query_wb_pin_2",
        "from": {"id": 7401},
        "message": {"chat": {"id": 17401}},
        "data": f"pb:{proj_id}:{token}",
    })
    assert cb_replay["action"] == "pinned_to_whiteboard"
    detail = await get_whiteboard_details(proj_id)
    replay_block = next(b for b in detail["blocks"] if b["id"] == cb_replay["block_id"])
    assert replay_block["title"] == "📌 Pinned from Telegram"


def test_planner_validate_brief():
    """Malformed briefs are rejected; entities normalized."""
    from capabilities.whiteboard.planner import validate_brief

    assert validate_brief(None) is None
    assert validate_brief({"action": "nonsense"}) is None
    assert validate_brief({"action": "none"}) == {"action": "none"}

    brief = validate_brief({
        "action": "create_board",
        "board_title": "Bali Bachelor Party",
        "category": "trip",
        "destination": "Bali",
        "date_range": "Sept 3-6",
        "occasion": "bachelor party",
        "entities": [
            {"kind": "accommodation", "title": "Villa Samatha", "details": "Tibubeneng", "status": "booked"},
            {"kind": "bogus_kind", "title": "", "details": "dropped - no title"},
            {"kind": "food", "title": "Lunch spots", "status": "weird-status"},
        ],
        "follow_up_questions": ["How many people?", "", 42],
        "research_queries": ["fitness social club Canggu Friday"],
    })
    assert brief is not None
    assert len(brief["entities"]) == 2
    assert brief["entities"][0]["status"] == "booked"
    assert brief["entities"][1]["kind"] == "food"
    assert brief["entities"][1]["status"] == "tbd"
    assert brief["follow_up_questions"] == ["How many people?"]
    assert len(brief["research_queries"]) == 1


@pytest.mark.asyncio
async def test_planning_intake_creates_board_with_entities(monkeypatch):
    """A freeform planning dump becomes one board with status-badged cards."""
    from capabilities.whiteboard import planner as wb_planner
    from capabilities.whiteboard import tools as wb_tools
    from orchestrator.router import WhiteboardPlugin
    from orchestrator.state import AssistantState
    from langchain_core.messages import HumanMessage

    async def fake_comprehend(text, board_context=None):
        return {
            "action": "create_board",
            "board_title": "Bali Bachelor Party",
            "category": "trip",
            "summary": "Sept 3-6 getaway",
            "destination": "Bali",
            "date_range": "Sept 3-6",
            "occasion": "bachelor party",
            "entities": [
                {"kind": "accommodation", "title": "Villa Samatha", "details": "Gang Anggrek, Tibubeneng", "status": "booked"},
                {"kind": "event", "title": "Finn's Beach Club", "details": "Saturday", "status": "confirmed"},
            ],
            "follow_up_questions": ["How many people total?"],
            "research_queries": [],
        }

    monkeypatch.setattr(wb_planner, "comprehend_request", fake_comprehend)

    plugin = WhiteboardPlugin()
    state = AssistantState(
        messages=[HumanMessage(content=(
            "I want to plan a trip to bali for the 3rd to 6th Sept\n"
            "I already booked an Airbnb at Villa Samatha, Tibubeneng\n"
            "It is for a bachelor party\nWe will be going to Finn's beach club on Saturday"
        ))],
        user_id=7501,
    )
    res = await plugin.execute(state)
    body = res.message.content

    assert "Created" in body and "Bali Bachelor Party" in body
    assert "✅ Booked" not in body  # badges live on cards, not necessarily the reply
    assert "Villa Samatha" in body
    assert "Finn's Beach Club" in body
    assert "How many people total?" in body

    boards = await list_whiteboards(user_id=7501)
    board = next(p for p in boards["projects"] if p["title"] == "Bali Bachelor Party")
    detail = await get_whiteboard_details(board["id"])

    by_title = {b["title"]: b for b in detail["blocks"]}
    villa = by_title["Villa Samatha"]
    assert villa["section_name"] == "Stays & Options"
    assert "Booked" in json.dumps(villa["content_payload"])
    assert "Tibubeneng" in json.dumps(villa["content_payload"])
    finns = by_title["Finn's Beach Club"]
    assert finns["section_name"] == "Itinerary"
    # Date range triggers a skeleton itinerary card
    assert any("Skeleton: Sept 3-6" in t for t in by_title)
    # Sections tracked in order
    assert "Stays & Options" in detail["project"]["section_order"]
    assert "Itinerary" in detail["project"]["section_order"]


@pytest.mark.asyncio
async def test_planning_intake_augments_recent_board_and_researches(monkeypatch):
    """Follow-up messages land on the recent board and research runs concurrently."""
    from types import SimpleNamespace
    from capabilities.whiteboard import planner as wb_planner
    from capabilities.general import tools as general_tools
    from orchestrator.router import WhiteboardPlugin
    from orchestrator.state import AssistantState
    from langchain_core.messages import HumanMessage

    create_res = await create_whiteboard(
        payload=CreateWhiteboardRequest(title="Bali Bachelor Party", category="trip", template="blank"),
        user_id=7601,
    )
    proj_id = create_res["project"]["id"]

    async def fake_comprehend(text, board_context=None):
        assert board_context is not None
        assert board_context["id"] == proj_id
        return {
            "action": "augment_board",
            "board_title": "Bali Bachelor Party",
            "category": "trip",
            "destination": "Bali",
            "date_range": None,
            "occasion": None,
            "entities": [
                {"kind": "activity", "title": "Fitness social club", "details": "Friday daytime", "status": "tbd"},
                {"kind": "food", "title": "Lunch & dinner near Tibubeneng", "status": "tbd"},
            ],
            "follow_up_questions": [],
            "research_queries": ["fitness social club Canggu", "restaurants Tibubeneng Bali"],
        }

    monkeypatch.setattr(wb_planner, "comprehend_request", fake_comprehend)

    async def fake_search(query):
        return f"Summary: top picks for {query}\n- Result A (https://a.example)\n- Result B (https://b.example)"

    class FakeSearchTool:
        async def ainvoke(self, payload):
            return await fake_search(payload.get("query") if isinstance(payload, dict) else str(payload))

    monkeypatch.setattr(general_tools, "search_web", FakeSearchTool())

    plugin = WhiteboardPlugin()
    state = AssistantState(
        messages=[HumanMessage(content="No budget but thinking of some fitness social club Friday and we need lunch and dinner")],
        user_id=7601,
        active_domain="whiteboard",
    )
    res = await plugin.execute(state)
    body = res.message.content

    assert "Updated" in body
    assert "Fitness social club" in body
    assert "Research" in body

    detail = await get_whiteboard_details(proj_id)
    titles = [b["title"] for b in detail["blocks"]]
    assert "Fitness social club" in titles
    assert any(b["section_name"] == "🔍 Research" for b in detail["blocks"])
    research_card = next(b for b in detail["blocks"] if b["section_name"] == "🔍 Research")
    assert "fitness social club Canggu" in json.dumps(research_card["content_payload"])
    assert research_card["content_payload"]["topics"][0]["query"] == "fitness social club Canggu"
    assert research_card["content_payload"]["topics"][0]["sources"][0]["url"].startswith("https://")


@pytest.mark.asyncio
async def test_planning_intake_fails_fast_instead_of_hanging_past_webhook_timeout(monkeypatch):
    """Regression: a real production incident where "bring up the upcoming
    bali trip" -- and then every unrelated follow-up message, since none
    matched a fast _parse_intent path either -- got stuck re-running
    _planning_intake() on every single turn, each one silently taking longer
    than the webhook's own 45s timeout with zero real progress ("Still
    working on that" forever). comprehend_request() and the research pass
    were each individually bounded, but nothing bounded their sum, so a slow
    (but within-budget) response from either could exceed the outer webhook
    deadline. WhiteboardPlugin.execute() must now fail fast with an honest
    message well under that ceiling instead of hanging."""
    import asyncio
    from capabilities.whiteboard import planner as wb_planner
    import orchestrator.router as router_module
    from orchestrator.router import WhiteboardPlugin
    from orchestrator.state import AssistantState
    from langchain_core.messages import HumanMessage

    # Tiny bound so the test itself stays fast while still exercising real
    # asyncio.wait_for cancellation, not a mock of it.
    monkeypatch.setattr(router_module, "PLANNING_INTAKE_TIMEOUT_SECONDS", 0.05)

    async def slow_comprehend(text, board_context=None):
        await asyncio.sleep(0.3)  # well past the 0.05s bound above
        return {"action": "none"}  # never reached

    monkeypatch.setattr(wb_planner, "comprehend_request", slow_comprehend)

    plugin = WhiteboardPlugin()
    state = AssistantState(
        messages=[HumanMessage(content="can you bring up the upcoming bali trip for me to plan some stuff")],
        user_id=7701,
    )

    loop = asyncio.get_event_loop()
    started = loop.time()
    res = await plugin.execute(state)
    elapsed = loop.time() - started

    assert elapsed < 0.2, f"execute() should fail fast at the bound, not wait out the full hang ({elapsed}s)"
    body = res.message.content
    assert "taking longer than expected" in body
    assert "Created" not in body
    assert res.state_update == {"active_domain": "whiteboard"}


@pytest.mark.asyncio
async def test_dispatch_reroutes_whiteboard_followups():
    """With active_domain=whiteboard, planning-signal follow-ups stay on the board."""
    from orchestrator.router import CapabilityRouter
    from orchestrator.state import AssistantState
    from langchain_core.messages import HumanMessage

    router = CapabilityRouter()
    captured = {}

    class SpyPlugin:
        name = "whiteboard"
        keywords = []

        async def execute(self, state):
            captured["called"] = True
            from langchain_core.messages import AIMessage
            from orchestrator.router import PluginOutput
            return PluginOutput(message=AIMessage(content="spy"), state_update={"active_domain": "whiteboard"})

    router.registry["whiteboard"] = SpyPlugin()

    state = AssistantState(
        messages=[HumanMessage(content="we need a place for lunch near the villa")],
        user_id=7701,
        active_domain="whiteboard",
    )

    # Directly exercise the routing decision block via dispatch internals:
    target = router.route_intent("we need a place for lunch near the villa")
    if target == "general" and state.get("active_domain") == "whiteboard":
        if router._has_planning_signal("we need a place for lunch near the villa"):
            target = "whiteboard"
    assert target == "whiteboard"
    assert router._has_planning_signal("lol random meme stuff") is False
