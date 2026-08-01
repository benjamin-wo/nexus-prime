import asyncio
import base64
import html
import json
import re
from typing import Dict, Any, List, Optional
import httpx
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlmodel import select
from core.config import settings
from core.db import async_session_factory
from core.models import UserProfile
from core.scheduler import list_active_jobs, run_now, update_user_timezone
from orchestrator.graph import assistant_graph


def format_for_telegram(text: str) -> str:
    """
    Convert lightweight Markdown into Telegram-safe HTML.
    Everything is HTML-escaped first, so unknown syntax renders as literal text
    instead of breaking Telegram's parse mode.
    """
    text = html.escape(text)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                continue  # drop markdown table separator rows
            lines.append("• " + " · ".join(cells))
        elif re.match(r"^#{1,6}\s+", stripped):
            lines.append("<b>" + re.sub(r"^#{1,6}\s+", "", stripped) + "</b>")
        elif re.match(r"^\s*[-*]\s+", line):
            lines.append("• " + re.sub(r"^\s*[-*]\s+", "", line))
        else:
            lines.append(line)
    return "\n".join(lines)


async def telegram_api_call(method: str, payload: Dict[str, Any]) -> bool:
    """Best-effort Telegram Bot API call. Returns False instead of raising on errors."""
    token = settings.telegram_bot_token
    if not token or token == "test_bot_token":
        print(f"[TELEGRAM] {method} skipped: bot token not configured")
        return False
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            print(f"[TELEGRAM] {method} failed: {resp.status_code} {resp.text[:300]}")
            return False
        data = resp.json()
        if not data.get("ok"):
            print(f"[TELEGRAM] {method} error: {data.get('description')}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - webhook ack must not depend on outbound calls
        print(f"[TELEGRAM] {method} exception: {exc}")
        return False


async def send_telegram_message(
    chat_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send a text message to a Telegram chat."""
    url_match = re.search(r"https?://[^\s]+", text)
    if url_match and reply_markup is None:
        url = url_match.group(0).rstrip(".,);!?")
        text = text.replace(url_match.group(0), "").strip()
        text = f"{text}\n\n👇 Tap the button below." if text else "👇 Tap the button below."
        reply_markup = {
            "inline_keyboard": [[{"text": "🔗 Open link", "url": url}]]
        }
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": format_for_telegram(text),
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return await telegram_api_call("sendMessage", payload)


async def answer_telegram_callback(
    callback_query_id: str,
    text: Optional[str] = None,
) -> bool:
    """Acknowledge an inline button press to clear Telegram's loading state."""
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return await telegram_api_call("answerCallbackQuery", payload)


async def send_telegram_chat_action(chat_id: int, action: str = "typing") -> bool:
    """Show a typing indicator so the bot feels responsive while processing."""
    return await telegram_api_call(
        "sendChatAction", {"chat_id": chat_id, "action": action}
    )


class TelegramIngress:
    """Deep ingress adapter for Telegram Bot API payloads, slash commands, callbacks, and profile lookup."""

    @staticmethod
    async def _typing_loop(chat_id: int, stop_event: asyncio.Event) -> None:
        """Repeat the typing indicator every ~4s until processing finishes."""
        while not stop_event.is_set():
            await send_telegram_chat_action(chat_id, "typing")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                continue

    @staticmethod
    def _log_conversation(direction: str, chat_id: Any, text: Any) -> None:
        """Print a lightweight conversation line to Railway logs for monitoring."""
        preview = str(text).replace("\n", " ")[:220] if text else ""
        print(f"[TG {direction}] chat={chat_id}: {preview}")

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
        callback_query_id = callback.get("id", "")

        if callback_data.startswith("log_req:"):
            tag = callback_data.split(":", 1)[1]
            from core.audit import log_capability_request

            await log_capability_request(
                user_id=user_id or 0,
                requested_task=f"Feature wishlist confirmation for #{tag}",
                intent_type="unsupported_transaction",
                tags=[tag],
            )
            reply_text = f"✅ Logged #{tag} to our feature wishlist!"
            self._log_conversation("CALLBACK", chat_id, f"log_req:{tag}")
            if callback_query_id:
                await answer_telegram_callback(callback_query_id, text="Logged")
            if chat_id:
                await send_telegram_message(chat_id, reply_text)
                self._log_conversation("OUT", chat_id, reply_text)
            return {
                "status": "ok",
                "action": "feature_request_logged",
                "tag": tag,
                "reply": reply_text,
            }

        action = "confirm"
        try:
            parsed = json.loads(callback_data)
            action = parsed.get("a", "confirm")
        except Exception:
            action = callback_data

        if chat_id:
            stop_event = asyncio.Event()
            typing_task = asyncio.create_task(self._typing_loop(chat_id, stop_event))
            try:
                config = {"configurable": {"thread_id": str(chat_id)}}
                result = await assistant_graph.ainvoke(
                    Command(resume={"action": action}),
                    config=config,
                )
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text="Done")
                reply_text = self._extract_ai_reply(result)
                if reply_text:
                    sent = await send_telegram_message(chat_id, reply_text)
                    self._log_conversation("OUT" if sent else "SEND-FAIL", chat_id, reply_text)
            finally:
                stop_event.set()
                typing_task.cancel()
                await asyncio.gather(typing_task, return_exceptions=True)
            return {"status": "ok", "action": action, "resumed": True}
        return {"status": "ok", "ignored": True}

    @staticmethod
    def _extract_ai_reply(result: Dict[str, Any]) -> Optional[str]:
        """Return the text of the last AI message produced by the assistant graph."""
        messages = result.get("messages") or []
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                return str(message.content)
        return None

    @staticmethod
    def _format_slash_reply(result: Dict[str, Any], raw_text: str) -> Optional[str]:
        """Convert a deterministic slash-command result into user-facing text."""
        if result.get("text"):
            return str(result["text"])

        if raw_text.startswith("/jobs"):
            jobs = result.get("jobs") or []
            if not jobs:
                return "📋 No active jobs."
            lines = []
            for job in jobs:
                next_run = job.get("next_run_time") or "not scheduled"
                lines.append(
                    f"- #{job.get('job_id')} **{job.get('job_name')}** "
                    f"(`{job.get('cron_expression')}` @ {job.get('timezone')}, next: {next_run})"
                )
            return "📋 Active jobs:\n" + "\n".join(lines)

        if raw_text.startswith("/run_now"):
            if result.get("status") == "error":
                return str(result.get("message") or "Usage: /run_now <job_id>")
            return (
                f"✅ Job {raw_text.split()[1]} triggered."
                if result.get("triggered")
                else "⚠️ Job could not be triggered."
            )

        if raw_text.startswith("/timezone"):
            if result.get("status") == "error":
                return str(result.get("message") or "Usage: /timezone <zone>")
            return f"✅ Timezone updated to `{result.get('timezone')}`."

        return None

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

        self._log_conversation("IN", chat_id, text or "<attachment>")

        if chat_id:
            await send_telegram_chat_action(chat_id)

        stop_event = asyncio.Event()
        typing_task = asyncio.create_task(self._typing_loop(chat_id, stop_event))
        try:
            profile = await self.ensure_profile(user_id=user_id, chat_id=chat_id)

            # Handle slash commands without invoking LangGraph
            slash_res = await self.handle_slash_command(text, user_id=user_id)
            if slash_res is not None:
                if chat_id:
                    reply_text = self._format_slash_reply(slash_res, text)
                    if reply_text:
                        sent = await send_telegram_message(chat_id, reply_text)
                        self._log_conversation(
                            "OUT" if sent else "SEND-FAIL", chat_id, reply_text
                        )
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
            reply_text = self._extract_ai_reply(result)
            reply_markup = None
            if result.get("intent_type") == "unsupported_transaction":
                tags = result.get("missing_capability_tags") or ["general"]
                primary_tag = tags[0] if tags else "general"
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {
                                "text": f"+ Log Feature Request (#{primary_tag})",
                                "callback_data": f"log_req:{primary_tag}",
                            }
                        ]
                    ]
                }
                if chat_id and reply_text:
                    sent = await send_telegram_message(chat_id, reply_text, reply_markup=reply_markup)
                    self._log_conversation(
                        "OUT" if sent else "SEND-FAIL", chat_id, reply_text
                    )
                return {
                    "status": "ok",
                    "processed": True,
                    "intent_type": "unsupported_transaction",
                    "inline_keyboard": reply_markup["inline_keyboard"],
                }

            if chat_id and reply_text:
                sent = await send_telegram_message(chat_id, reply_text)
                self._log_conversation(
                    "OUT" if sent else "SEND-FAIL", chat_id, reply_text
                )
            return {"status": "ok", "processed": True}
        finally:
            stop_event.set()
            typing_task.cancel()
            await asyncio.gather(typing_task, return_exceptions=True)


# Global default ingress adapter
telegram_ingress = TelegramIngress()
