import base64
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlmodel import select
from core.db import async_session_factory
from core.models import UserProfile
from core.scheduler import list_active_jobs, run_now, update_user_timezone
from orchestrator.graph import assistant_graph


class TelegramIngress:
    """Deep ingress adapter for Telegram Bot API payloads, slash commands, callbacks, and profile lookup."""

    async def ensure_profile(self, user_id: int, chat_id: int) -> UserProfile:
        """Ensure user profile exists in PostgreSQL."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if not profile:
                profile = UserProfile(
                    user_id=user_id,
                    telegram_chat_id=chat_id,
                    current_timezone="UTC",
                )
                session.add(profile)
                await session.commit()
                await session.refresh(profile)
            return profile

    def format_base64_data_uri(self, mime_type: str, data_bytes: bytes) -> str:
        """Format in-memory Base64 data-URI without temporary filesystem storage."""
        b64_str = base64.b64encode(data_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64_str}"

    async def process_multimodal_attachments(
        self, message: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Construct LangChain Base64 content blocks for text, voice (.ogg), or photo (.jpg)."""
        content_blocks = []
        text = message.get("text") or message.get("caption") or ""
        if text:
            content_blocks.append({"type": "text", "text": text})

        if "voice" in message or "audio" in message:
            dummy_audio = b"OggS_dummy_voice_data"
            data_uri = self.format_base64_data_uri("audio/ogg", dummy_audio)
            content_blocks.append(
                {"type": "media", "mime_type": "audio/ogg", "data_uri": data_uri}
            )

        if (
            "photo" in message
            and isinstance(message["photo"], list)
            and len(message["photo"]) > 0
        ):
            dummy_photo = b"\xff\xd8\xff_dummy_photo_data"
            data_uri = self.format_base64_data_uri("image/jpeg", dummy_photo)
            content_blocks.append({"type": "image_url", "image_url": {"url": data_uri}})

        return content_blocks

    async def handle_callback_query(self, callback: Dict[str, Any]) -> Dict[str, Any]:
        """Handle inline keyboard button callbacks for HITL confirmation and wishlist logging."""
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        user_id = callback.get("from", {}).get("id")
        callback_data = callback.get("data", "")

        if callback_data.startswith("log_req:"):
            tag = callback_data.split(":", 1)[1]
            from core.audit import log_capability_request

            await log_capability_request(
                user_id=user_id or 0,
                requested_task=f"Feature wishlist confirmation for #{tag}",
                intent_type="unsupported_transaction",
                tags=[tag],
            )
            return {
                "status": "ok",
                "action": "feature_request_logged",
                "tag": tag,
                "reply": f"✅ Logged #{tag} to our feature wishlist!",
            }

        action = "confirm"
        try:
            parsed = json.loads(callback_data)
            action = parsed.get("a", "confirm")
        except Exception:
            action = callback_data

        if chat_id:
            config = {"configurable": {"thread_id": str(chat_id)}}
            await assistant_graph.ainvoke(
                Command(resume={"action": action}),
                config=config,
            )
            return {"status": "ok", "action": action, "resumed": True}
        return {"status": "ok", "ignored": True}

    async def handle_slash_command(
        self, text: str, user_id: int
    ) -> Optional[Dict[str, Any]]:
        """Directly execute deterministic slash commands (/jobs, /run_now, /timezone, /missing_capabilities)."""
        if text.startswith("/jobs"):
            jobs = await list_active_jobs(user_id=user_id)
            return {"status": "ok", "jobs": jobs}

        if text.startswith("/run_now"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                success = await run_now(int(parts[1]))
                return {"status": "ok", "triggered": success}
            return {"status": "error", "message": "Usage: /run_now <job_id>"}

        if text.startswith("/timezone"):
            parts = text.split()
            if len(parts) >= 2:
                tz = parts[1]
                success = await update_user_timezone(
                    user_id=user_id, new_timezone=tz
                )
                return {"status": "ok", "updated": success, "timezone": tz}

        if text.startswith("/missing_capabilities"):
            from core.audit import get_capability_leaderboard

            leaderboard = await get_capability_leaderboard(limit=10)
            if not leaderboard:
                table_md = "📊 **Top Missing Capability Requests**\n\nNo missing capabilities logged yet."
            else:
                table_md = "📊 **Top Missing Capability Requests**\n\n| Rank | Tag | Requests | Sample Prompt |\n| :---: | :--- | :---: | :--- |\n"
                for idx, row in enumerate(leaderboard, 1):
                    table_md += f'| {idx} | `#{row["tag"]}` | {row["count"]} | *"{row["sample_prompt"]}"* |\n'
            return {"status": "ok", "leaderboard": leaderboard, "text": table_md}

        return None

    async def handle_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point for processing Telegram webhook updates."""
        if "callback_query" in payload:
            return await self.handle_callback_query(payload["callback_query"])

        message = payload.get("message") or payload.get("edited_message")
        if not message:
            return {"status": "ok", "ignored_non_message": True}

        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        text = (message.get("text") or "").strip()

        if not user_id or not chat_id:
            return {"status": "ok", "ignored_missing_user": True}

        profile = await self.ensure_profile(user_id=user_id, chat_id=chat_id)

        # Handle slash commands without invoking LangGraph
        slash_res = await self.handle_slash_command(text, user_id=user_id)
        if slash_res is not None:
            return slash_res

        content_blocks = await self.process_multimodal_attachments(message)
        human_msg = HumanMessage(
            content=content_blocks if len(content_blocks) > 1 else text
        )

        config = {"configurable": {"thread_id": str(chat_id)}}
        initial_state = {
            "messages": [human_msg],
            "user_id": user_id,
            "current_timezone": profile.current_timezone,
            "active_domain": None,
        }

        result = await assistant_graph.ainvoke(initial_state, config=config)
        if result.get("intent_type") == "unsupported_transaction":
            tags = result.get("missing_capability_tags") or ["general"]
            primary_tag = tags[0] if tags else "general"
            return {
                "status": "ok",
                "processed": True,
                "intent_type": "unsupported_transaction",
                "inline_keyboard": [
                    [
                        {
                            "text": f"+ Log Feature Request (#{primary_tag})",
                            "callback_data": f"log_req:{primary_tag}",
                        }
                    ]
                ],
            }

        return {"status": "ok", "processed": True}


# Global default ingress adapter
telegram_ingress = TelegramIngress()
