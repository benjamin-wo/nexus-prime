"""Web Chat API router for Nexus Prime.

Provides an asynchronous HTTP JSON endpoint `POST /api/chat` that directly connects
the website chat interface with the LangGraph assistant graph orchestrator,
supporting persistent sessions, dynamic timezones, slash commands, and HITL resume actions.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from sqlmodel import select, desc

from core.db import async_session_factory
from core.llm import extract_llm_text
from core.models import UserProfile
from orchestrator.graph import get_assistant_graph
from app.ingress import telegram_ingress

router = APIRouter(prefix="/chat", tags=["Web Chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message text or slash command")
    session_id: Optional[str] = Field(default="web-session-default", description="Conversation session identifier")
    timezone: Optional[str] = Field(default="Asia/Singapore", description="User IANA timezone")
    action: Optional[str] = Field(default=None, description="Resume action for interrupted HITL confirmation")
    user_id: Optional[int] = Field(default=999999, description="Synthetic or authenticated user identifier")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Ambient page context (e.g. current_page, filters)")


class ChatResponse(BaseModel):
    status: str = "ok"
    reply: str
    session_id: str
    buttons: Optional[List[Dict[str, Any]]] = None
    resumed: bool = False
    interrupted: bool = False
    events: Optional[List[Dict[str, Any]]] = None


async def ensure_web_profile(user_id: Optional[int], timezone: str) -> UserProfile:
    """Ensure a user profile exists in PostgreSQL/SQLite for the web user or primary user."""
    async with async_session_factory() as session:
        target_uid = user_id
        if not target_uid or target_uid == 999999:
            # Check if there is an existing active user profile (e.g. from Telegram)
            res = await session.execute(
                select(UserProfile).order_by(desc(UserProfile.created_at)).limit(1)
            )
            existing = res.scalar_one_or_none()
            if existing:
                return existing
            target_uid = 999999

        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == target_uid)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfile(
                user_id=target_uid,
                telegram_chat_id=target_uid,
                current_timezone=timezone or "Asia/Singapore",
            )
            session.add(profile)
            await session.commit()
            await session.refresh(profile)
        elif timezone and profile.current_timezone != timezone:
            profile.current_timezone = timezone
            session.add(profile)
            await session.commit()
            await session.refresh(profile)
        return profile


@router.post("", response_model=ChatResponse)
async def handle_web_chat(request: ChatRequest) -> ChatResponse:
    """Execute a turn with the Nexus Prime LangGraph agent orchestrator."""
    raw_text = (request.message or "").strip()
    # Initialize session_id early so it is always available in the except block
    session_id = request.session_id or f"web-{request.user_id or 999999}"

    try:
        profile = await ensure_web_profile(user_id=request.user_id, timezone=request.timezone or "Asia/Singapore")
        user_id = profile.user_id
        session_id = request.session_id or f"web-{user_id}"
        config = {"configurable": {"thread_id": str(session_id)}}

        # 1. Handle resume actions if responding to a previous LangGraph interrupt
        if request.action:
            action_payload = request.action
            try:
                parsed_action = json.loads(action_payload)
            except Exception:
                parsed_action = {"action": action_payload}

            graph = get_assistant_graph()
            result = await graph.ainvoke(
                Command(resume=parsed_action),
                config=config,
            )
            reply = telegram_ingress._extract_ai_reply(result) or "Action processed successfully."
            return ChatResponse(
                status="ok",
                reply=reply,
                session_id=session_id,
                resumed=True,
            )

        # 2. Check for deterministic slash commands
        if raw_text.startswith("/"):
            slash_res = await telegram_ingress.handle_slash_command(raw_text, user_id=user_id)
            if slash_res is not None:
                reply_text = telegram_ingress._format_slash_reply(slash_res, raw_text) or str(slash_res)
                return ChatResponse(
                    status="ok",
                    reply=reply_text,
                    session_id=session_id,
                )

        # 3. Standard conversational execution through LangGraph
        human_msg = HumanMessage(content=raw_text)
        initial_state = {
            "messages": [human_msg],
            "user_id": user_id,
            "current_timezone": profile.current_timezone,
            "active_domain": None,
        }

        graph = get_assistant_graph()
        result = await graph.ainvoke(initial_state, config=config)

        # Check for LangGraph Interrupts (e.g. HITL confirmation for spend/writes)
        interrupts = result.get("__interrupt__")
        buttons = None
        if interrupts:
            for interrupt_item in interrupts:
                payload = getattr(interrupt_item, "value", interrupt_item)
                if isinstance(payload, dict) and payload.get("prompt"):
                    reply = payload["prompt"]
                    buttons = payload.get("buttons", [])
                    return ChatResponse(
                        status="ok",
                        reply=reply,
                        session_id=session_id,
                        buttons=buttons,
                        interrupted=True,
                    )

        reply = telegram_ingress._extract_ai_reply(result)
        if not reply:
            reply = "I've processed your request."

        # Extract and emit ReactiveUIEvents for client-side live dashboard sync
        events: List[Dict[str, Any]] = []
        active_domain = result.get("active_domain")
        if active_domain:
            events.append({"type": f"{active_domain}_changed", "domain": active_domain})

        reply_lower = reply.lower()
        if any(w in reply_lower for w in ["logged", "saved", "deleted", "restored", "expense", "transaction", "sgd", "spend", "spent"]):
            if not any(e.get("type") == "expenses_changed" for e in events):
                events.append({"type": "expenses_changed", "domain": "expenses"})
        if any(w in reply_lower for w in ["reminder", "scheduled", "job", "cron"]):
            if not any(e.get("type") == "reminders_changed" for e in events):
                events.append({"type": "reminders_changed", "domain": "reminders"})
        if any(w in reply_lower for w in ["grocery", "groceries", "checklist", "pantry", "added to your"]):
            if not any(e.get("type") == "groceries_changed" for e in events):
                events.append({"type": "groceries_changed", "domain": "groceries"})

        return ChatResponse(
            status="ok",
            reply=reply,
            session_id=session_id,
            buttons=None,
            events=events,
        )

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return ChatResponse(
            status="error",
            reply=f"😵‍💫 Sorry, something glitched on my end: {str(exc)}",
            session_id=session_id,
        )
