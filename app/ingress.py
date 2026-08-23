import asyncio
import base64
import html
import json
import os
import re
from typing import Dict, Any, List, Optional
import httpx
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlmodel import select
from core.config import settings
from core.db import async_session_factory
from core.llm import extract_llm_text
from core.models import UserProfile
from core.scheduler import list_active_jobs, run_now, update_user_timezone
from orchestrator.graph import get_assistant_graph

# Short-lived store of content awaiting a "pin to board" button press.
# Keyed by an 8-char token embedded in callback_data (Telegram caps it at 64 bytes).
_pending_pins: Dict[str, Dict[str, Any]] = {}
_PENDING_PIN_TTL_SECONDS = 3600


def register_pending_pin(project_id: int, user_id: int, title: str, markdown: str) -> str:
    """Store plannable content and return the token to embed in `pb:<project>:<token>` buttons."""
    import time
    import uuid

    now = time.time()
    for tok in [t for t, v in _pending_pins.items() if now - v.get("ts", 0) > _PENDING_PIN_TTL_SECONDS]:
        _pending_pins.pop(tok, None)
    token = uuid.uuid4().hex[:8]
    _pending_pins[token] = {
        "project_id": project_id,
        "user_id": user_id,
        "title": (title or "Pinned from Telegram")[:200],
        "markdown": markdown or "",
        "ts": now,
    }
    return token


async def consume_pending_pin(token: str) -> Optional[Dict[str, Any]]:
    """Pop stored pin content for a token, if present and fresh."""
    import time

    entry = _pending_pins.pop(token, None) if token else None
    if not entry or time.time() - entry.get("ts", 0) > _PENDING_PIN_TTL_SECONDS:
        return None
    return entry


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


def parse_custom_split_amounts(text: str) -> Dict[str, float]:
    """Extract explicit final shares from a /split command.

    Supported forms include ``I pay $20, Alex pays $10`` and
    ``Me: $20, Alex: $10``. An empty mapping means the caller should use the
    normal equal/item-based split behavior.
    """
    matches = []
    personal = re.compile(
        r"\b(?P<name>me|myself|i|my\s+share)\b\s*"
        r"(?:(?:will|should|need\s+to)\s+)?"
        r"(?:(?:pay|paid|pays|owe|owes|get|gets|share(?:\s+is)?)\s*|:\s*)"
        r"\$?\s*(?P<amount>\d+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )
    named = re.compile(
        r"\b(?P<name>[A-Za-z][A-Za-z0-9'&.\-]{1,30})\b\s*"
        r"(?:(?:will|should|needs?\s+to)\s+)?"
        r"(?:pay|paid|pays|owe|owes|get|gets|share(?:\s+is)?)\s*"
        r"\$?\s*(?P<amount>\d+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )
    colon = re.compile(
        r"\b(?P<name>[A-Za-z][A-Za-z0-9'&.\-]{1,30})\b\s*:\s*"
        r"\$?\s*(?P<amount>\d+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )
    matches.extend(personal.finditer(text or ""))
    matches.extend(named.finditer(text or ""))
    matches.extend(colon.finditer(text or ""))

    amounts: Dict[str, float] = {}
    for match in sorted(matches, key=lambda item: item.start()):
        name = match.group("name").strip().title()
        if name.lower() in {"me", "my", "myself", "i", "my share"}:
            name = "Me"
        try:
            amounts[name] = round(float(match.group("amount")), 2)
        except (TypeError, ValueError):
            continue
    return amounts if len(amounts) >= 2 else {}


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


async def delete_telegram_message(chat_id: int, message_id: int) -> bool:
    """Delete a Telegram message by ID to remove completed/snoozed reminder bubbles."""
    return await telegram_api_call(
        "deleteMessage", {"chat_id": chat_id, "message_id": message_id}
    )


async def setup_telegram_bot_commands() -> bool:
    """
    Register native Telegram bot slash commands (pop-up autocomplete list on '/')
    and configure the bottom persistent chat Menu Button.
    """
    commands = [
        {"command": "dashboard", "description": "🚀 Open Web Cockpit & Analytics"},
        {"command": "split", "description": "👥 Split a bill with friends & create IOUs"},
        {"command": "expenses", "description": "💰 View recent expenses & spending"},
        {"command": "income", "description": "💵 View incoming money"},
        {"command": "credit", "description": "➕ Log money received"},
        {"command": "tasks", "description": "📋 View pending tasks & reminders"},
        {"command": "groceries", "description": "🛒 View grocery shopping list"},
        {"command": "email", "description": "📬 Connect Gmail or Outlook for receipts"},
        {"command": "disconnect_email", "description": "🔌 Remove Gmail or Outlook access"},
        {"command": "jobs", "description": "⏰ Manage scheduled background alerts"},
        {"command": "timezone", "description": "📍 Check or update your current timezone"},
        {"command": "help", "description": "💡 View tips, shortcuts & commands guide"},
    ]
    
    # 1. Register slash commands so typing '/' pops up the interactive menu
    res1 = await telegram_api_call("setMyCommands", {"commands": commands})
    
    # 2. Configure default Menu button to open the command menu
    res2 = await telegram_api_call("setChatMenuButton", {"menu_button": {"type": "commands"}})
    
    print(f"[TELEGRAM] Bot commands registered: {res1}, Menu button configured: {res2}")
    return res1 and res2



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
                    current_timezone="Asia/Singapore",
                )
                session.add(profile)
                await session.commit()
                await session.refresh(profile)
            else:
                updated = False
                if chat_id and chat_id != 999999 and profile.telegram_chat_id != chat_id:
                    profile.telegram_chat_id = chat_id
                    updated = True
                if not profile.current_timezone or profile.current_timezone == "UTC":
                    profile.current_timezone = "Asia/Singapore"
                    updated = True
                if updated:
                    session.add(profile)
                    await session.commit()
                    await session.refresh(profile)
            return profile

    def format_base64_data_uri(self, mime_type: str, data_bytes: bytes) -> str:
        """Format in-memory Base64 data-URI without temporary filesystem storage."""
        b64_str = base64.b64encode(data_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64_str}"

    async def _download_telegram_media(self, file_id: str) -> Optional[tuple[str, bytes]]:
        """Download a Telegram media file via the Bot API; returns (file_path, bytes)."""
        token = settings.telegram_bot_token
        if not token or token == "test_bot_token":
            return None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                info_resp = await client.get(
                    f"https://api.telegram.org/bot{token}/getFile",
                    params={"file_id": file_id},
                )
                info = info_resp.json()
                if not info.get("ok"):
                    print(f"[TG MEDIA] getFile failed: {info.get('description')}")
                    return None
                file_path = info["result"].get("file_path")
                if not file_path:
                    return None
                download = await client.get(f"https://api.telegram.org/bot{token}/{file_path}")
                if download.status_code != 200:
                    print(f"[TG MEDIA] download failed: {download.status_code}")
                    return None
                return str(file_path), download.content
        except Exception as exc:  # noqa: BLE001
            print(f"[TG MEDIA] download error: {exc}")
            return None

    @staticmethod
    def _guess_mime(file_path: str, fallback: str) -> str:
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        return {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif",
            "ogg": "audio/ogg",
            "oga": "audio/ogg",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
        }.get(ext, fallback)

    async def process_multimodal_attachments(
        self, message: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Download real Telegram media and construct Gemini content blocks for
        text, voice/audio, and photos. Falls back to a warning note if a file
        cannot be downloaded.
        """
        content_blocks = []
        text = message.get("text") or message.get("caption") or ""
        if text:
            content_blocks.append({"type": "text", "text": text})

        media_items: List[tuple[str, str]] = []  # (file_id, mime_type)
        if "voice" in message:
            voice = message["voice"]
            media_items.append((voice.get("file_id", ""), "audio/ogg"))
        if "audio" in message:
            audio = message["audio"]
            media_items.append(
                (audio.get("file_id", ""), audio.get("mime_type") or "audio/mpeg")
            )
        if "document" in message:
            document = message["document"]
            mime = document.get("mime_type") or ""
            if mime.startswith("image/") or mime.startswith("audio/"):
                media_items.append((document.get("file_id", ""), mime))
        if "photo" in message and isinstance(message["photo"], list) and message["photo"]:
            largest = message["photo"][-1]
            media_items.append((largest.get("file_id", ""), "image/jpeg"))

        for file_id, mime_type in media_items:
            if not file_id:
                continue
            downloaded = await self._download_telegram_media(file_id)
            if downloaded is None:
                content_blocks.append(
                    {
                        "type": "text",
                        "text": "⚠️ (couldn't download the attached media)",
                    }
                )
                continue
            file_path, file_bytes = downloaded
            resolved_mime = self._guess_mime(file_path, mime_type)
            content_blocks.append(
                {
                    "type": "media",
                    "mime_type": resolved_mime,
                    "data": base64.b64encode(file_bytes).decode("utf-8"),
                }
            )

        return content_blocks

    async def handle_callback_query(self, callback: Dict[str, Any]) -> Dict[str, Any]:
        """Handle inline keyboard button callbacks for HITL confirmation and wishlist logging."""
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        user_id = callback.get("from", {}).get("id")
        callback_data = callback.get("data", "")
        callback_query_id = callback.get("id", "")

        if callback_data.startswith("cmd:"):
            cmd = callback_data.split(":", 1)[1]
            if callback_query_id:
                await answer_telegram_callback(callback_query_id)
            if cmd == "expenses":
                res = await self.handle_slash_command("/expenses", user_id=user_id or 0)
                if res and chat_id:
                    await send_telegram_message(chat_id, res.get("text", "No expenses."))
            elif cmd == "tasks":
                res = await self.handle_slash_command("/tasks", user_id=user_id or 0)
                if res and chat_id:
                    await send_telegram_message(chat_id, res.get("text", "No tasks."))
            elif cmd == "income":
                res = await self.handle_slash_command("/income", user_id=user_id or 0)
                if res and chat_id:
                    await send_telegram_message(chat_id, res.get("text", "No incoming money."))
            elif cmd == "email":
                res = await self.handle_slash_command("/email", user_id=user_id or 0)
                if res and chat_id:
                    await send_telegram_message(chat_id, res.get("text", "Connect email."))
            elif cmd == "split":
                if chat_id:
                    await send_telegram_message(
                        chat_id,
                        "👥 **How to Split a Bill:**\n\n"
                        "Send a message like:\n"
                        "• `/split 160 Haidilao with Alex, Chloe, Ben and me`\n"
                        "• Or simply text: *'Split $120 dinner at Haidilao with Chloe and Alex'*\n"
                        "• Or upload a receipt photo with the caption: *'Split 3 ways'*."
                    )
            elif cmd == "groceries":
                res = await self.handle_slash_command("/groceries", user_id=user_id or 0)
                if res and chat_id:
                    await send_telegram_message(chat_id, res.get("text", "Grocery list."))
            return {"status": "ok", "action": f"cmd_{cmd}"}

        if callback_data.startswith("log_req:"):
            tag = callback_data.split(":", 1)[1]
            from core.audit import log_capability_request

            await log_capability_request(
                user_id=user_id or 0,
                requested_task=f"Feature wishlist confirmation for #{tag}",
                intent_type="unsupported_transaction",
                tags=[tag],
                expectation=f"User explicitly requested a feature for `{tag}` via the Telegram wishlist button.",
                block_reason="Capability does not exist yet — logged from explicit wishlist confirmation.",
                channel="telegram",
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

        if callback_data.startswith("sb:"):
            tx_id_str = callback_data.split(":", 1)[1]
            try:
                tx_id = int(tx_id_str)
                from core.models import ExpenseTransaction
                from core.db import async_session_factory
                from sqlmodel import select

                async with async_session_factory() as session:
                    tx = (await session.execute(
                        select(ExpenseTransaction).where(
                            ExpenseTransaction.id == tx_id,
                            ExpenseTransaction.user_id == (user_id or 0),
                        )
                    )).scalar_one_or_none()

                if tx:
                    reply_text = (
                        f"👥 **Split Bill: {tx.currency} {tx.amount:.2f} at {tx.merchant}**\n\n"
                        f"Who are you splitting this with? Tell me the names or number of people (e.g. *\"Alex, Chloe, Ben and me\"* or *\"/split {tx.amount:.2f} {tx.merchant} with Alex, Chloe and Ben\"*)."
                    )
                else:
                    reply_text = "👥 Tell me the amount and friends to split with (e.g. *'/split 120 Haidilao with Alex, Chloe and me'*)."
            except Exception:
                reply_text = "👥 Tell me who you want to split this bill with (e.g. *'/split 120 Haidilao with Alex, Chloe and me'*)."

            if callback_query_id:
                await answer_telegram_callback(callback_query_id, text="Let's split this bill!")
            if chat_id:
                await send_telegram_message(chat_id, reply_text)
                self._log_conversation("OUT", chat_id, reply_text)
            return {
                "status": "ok",
                "action": "split_bill_prompt",
                "reply": reply_text,
            }

        if callback_data.startswith("td:"):
            task_id_str = callback_data.split(":", 1)[1]
            try:
                task_id = int(task_id_str)
                from core.models import TaskItem
                from core.db import async_session_factory
                from core.scheduler import remove_task_reminder
                from sqlmodel import select
                from datetime import datetime

                title = f"Task #{task_id}"
                async with async_session_factory() as session:
                    task = (await session.execute(
                        select(TaskItem).where(
                            TaskItem.id == task_id,
                            TaskItem.user_id == (user_id or 0),
                        )
                    )).scalar_one_or_none()
                    if task:
                        if task.linked_expense_id and task.iou_friend:
                            from capabilities.expenses.settlement import (
                                IouSettlementCommand,
                                settle_iou,
                            )

                            settlement = await settle_iou(IouSettlementCommand(
                                expense_id=task.linked_expense_id,
                                user_id=user_id or 0,
                                participant=task.iou_friend,
                            ))
                            if settlement.get("status") in {"settled", "already_settled"}:
                                title = f"{task.iou_friend} repayment"
                                if callback_query_id:
                                    await answer_telegram_callback(
                                        callback_query_id,
                                        text=f"✅ {task.iou_friend} marked paid",
                                    )
                                if chat_id:
                                    if settlement.get("status") == "already_settled":
                                        reply_text = f"ℹ️ {task.iou_friend}'s IOU is already marked as paid."
                                    else:
                                        reply_text = (
                                            f"✅ Marked {task.iou_friend}'s IOU as paid and logged "
                                            f"{settlement.get('amount_received', 0):.2f} "
                                            f"{settlement.get('currency', 'SGD')} incoming."
                                        )
                                    await send_telegram_message(
                                        chat_id,
                                        reply_text,
                                    )
                                return {
                                    "status": "ok",
                                    "action": "iou_settled",
                                    "task_id": task_id,
                                    "expense_id": task.linked_expense_id,
                                    "settlement": settlement,
                                }
                            if callback_query_id:
                                await answer_telegram_callback(
                                    callback_query_id,
                                    text="Could not settle this IOU",
                                )
                            if chat_id:
                                await send_telegram_message(
                                    chat_id,
                                    "I could not reconcile that IOU. Open the transaction in the cockpit to review it.",
                                )
                            return {
                                "status": "error",
                                "action": "iou_settlement_failed",
                                "task_id": task_id,
                                "settlement": settlement,
                            }
                        task.status = "done"
                        task.completed_at = datetime.utcnow()
                        task.is_reminder_active = False
                        session.add(task)
                        await session.commit()
                        remove_task_reminder(task.id)
                        title = task.title

                self._log_conversation("CALLBACK", chat_id, f"td:{task_id}")
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text=f"✅ Marked '{title}' as done")

                # Remove the reminder message bubble so the chat stays clean
                message_id = callback.get("message", {}).get("message_id")
                if chat_id and message_id:
                    await delete_telegram_message(chat_id, message_id)

                return {
                    "status": "ok",
                    "action": "task_completed",
                    "task_id": task_id,
                }
            except Exception as exc:
                print(f"[CALLBACK] error completing task {callback_data}: {exc}")

        if callback_data.startswith("ts:"):
            task_id_str = callback_data.split(":", 1)[1]
            try:
                task_id = int(task_id_str)
                from core.models import TaskItem
                from core.db import async_session_factory
                from core.scheduler import snooze_task_reminder
                from sqlmodel import select

                title = f"Task #{task_id}"
                async with async_session_factory() as session:
                    task = (await session.execute(
                        select(TaskItem).where(TaskItem.id == task_id)
                    )).scalar_one_or_none()
                    if task:
                        title = task.title

                await snooze_task_reminder(task_id, user_id=user_id or 0, minutes=60)
                self._log_conversation("CALLBACK", chat_id, f"ts:{task_id}")
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text=f"⏰ Snoozed '{title}' for 1h")

                # Remove the reminder message bubble
                message_id = callback.get("message", {}).get("message_id")
                if chat_id and message_id:
                    await delete_telegram_message(chat_id, message_id)

                return {
                    "status": "ok",
                    "action": "task_snoozed",
                    "task_id": task_id,
                }
            except Exception as exc:
                print(f"[CALLBACK] error snoozing task {callback_data}: {exc}")

        if callback_data.startswith("pb:"):
            # pb:<project_id>[:<token>] — pin content to a whiteboard board.
            # With a token, the exact content captured when the button was sent is
            # written as a note card. Without one, an honest placeholder card is
            # still created so "Pinned!" never lies.
            parts = callback_data.split(":", 2)
            proj_id_str = parts[1] if len(parts) > 1 else "1"
            token = parts[2] if len(parts) > 2 else ""
            try:
                proj_id = int(proj_id_str)
                from core.models import WhiteboardProject
                from core.db import async_session_factory
                from sqlmodel import select as _select
                from capabilities.whiteboard.tools import add_block_to_whiteboard

                proj_title = "Whiteboard"
                async with async_session_factory() as session:
                    proj = (await session.execute(
                        _select(WhiteboardProject).where(WhiteboardProject.id == proj_id)
                    )).scalar_one_or_none()
                    if proj:
                        proj_title = f"{proj.emoji_icon} {proj.title}"

                pin_entry = await consume_pending_pin(token)
                if pin_entry and int(pin_entry.get("project_id") or 0) == proj_id:
                    block_title = str(pin_entry.get("title") or "Pinned from Telegram")
                    markdown = f"📌 **Pinned from Telegram**\n\n{pin_entry.get('markdown') or ''}".strip()
                else:
                    block_title = "📌 Pinned from Telegram"
                    markdown = f"Pinned on {__import__('datetime').datetime.utcnow().strftime('%b %d, %H:%M')} UTC"

                block = await add_block_to_whiteboard(
                    project_id=proj_id,
                    section_name="Pinned",
                    block_type="note",
                    title=block_title,
                    content_payload={"markdown": markdown},
                )

                reply_text = (
                    f"📌 Pinned *{block.title}* to <b>{proj_title}</b> (card #{block.id}).\n"
                    f"View it anytime on your web canvas."
                )
                self._log_conversation("CALLBACK", chat_id, callback_data)
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text=f"Pinned to {proj_title}!")
                if chat_id:
                    await send_telegram_message(chat_id, reply_text)
                    self._log_conversation("OUT", chat_id, reply_text)
                return {
                    "status": "ok",
                    "action": "pinned_to_whiteboard",
                    "project_id": proj_id,
                    "block_id": block.id,
                    "reply": reply_text,
                }
            except Exception as exc:
                print(f"[CALLBACK] error pinning to whiteboard {callback_data}: {exc}")

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
                result = await get_assistant_graph().ainvoke(
                    Command(resume={"action": action}),
                    config=config,
                )
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text="Done")
                reply_text = self._extract_ai_reply(result)
                if reply_text:
                    sent = await send_telegram_message(chat_id, reply_text)
                    self._log_conversation("OUT" if sent else "SEND-FAIL", chat_id, reply_text)
            except Exception as exc:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                if callback_query_id:
                    await answer_telegram_callback(
                        callback_query_id, text="Something glitched — try again"
                    )
                await send_telegram_message(
                    chat_id,
                    "😵‍💫 Sorry, something glitched on my end — I've logged it and I'm on it. Try again in a minute?",
                )
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
                return extract_llm_text(message.content)
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

        if text.startswith("/groceries"):
            from capabilities.recipes.tools import get_user_grocery_list

            items = await get_user_grocery_list.ainvoke({"user_id": user_id})
            if not items:
                return {"status": "ok", "groceries": [], "text": "🛒 Your grocery list is empty."}
            lines = [
                f"• {item['name']} × {item['quantity']} ({item['category']})"
                for item in items[:15]
            ]
            return {
                "status": "ok",
                "groceries": items,
                "text": "🛒 Grocery list:\n" + "\n".join(lines),
            }

        if text.startswith(("/income", "/incoming")):
            from core.models import IncomeTransaction

            async with async_session_factory() as session:
                rows = (await session.execute(
                    select(IncomeTransaction)
                    .where(IncomeTransaction.user_id == user_id)
                    .order_by(IncomeTransaction.date.desc())
                    .limit(10)
                )).scalars().all()
            if not rows:
                return {"status": "ok", "income": [], "text": "💵 No incoming money logged yet."}
            lines = [
                f"• {row.date.strftime('%Y-%m-%d')} {row.currency} {row.amount:.2f} — "
                f"{row.source} ({row.category})"
                for row in rows
            ]
            total = sum(row.amount for row in rows)
            lines.append(f"\nTotal (last {len(rows)}): {rows[0].currency} {total:.2f}")
            return {
                "status": "ok",
                "income": [row.model_dump() for row in rows],
                "text": "💵 Recent incoming money:\n" + "\n".join(lines),
            }

        if text.startswith(("/credit", "/received", "/log_income")):
            from capabilities.expenses.tools import (
                income_source_id,
                is_duplicate_income,
                parse_incoming_transaction_text,
                save_income_transaction,
            )

            parse_text = text if not text.startswith("/credit") else text.replace("/credit", "received", 1)
            parse_text = parse_text if not parse_text.startswith("/log_income") else parse_text.replace("/log_income", "received", 1)
            parsed = parse_incoming_transaction_text(parse_text)
            if parsed is None:
                return {
                    "status": "error",
                    "text": "Usage: `/credit <amount> from <person or company> [salary|repayment|claim]`.",
                }
            source_id = income_source_id(user_id, text)
            if await is_duplicate_income(source_id):
                return {"status": "ok", "text": "↩️ That incoming transaction is already logged."}
            item = await save_income_transaction(
                user_id=user_id,
                income=parsed,
                source_message_id=source_id,
            )
            return {
                "status": "ok",
                "income": item.model_dump(),
                "text": (
                    f"✅ Logged incoming *{item.currency} {item.amount:.2f}* from "
                    f"*{item.source}* ({item.category})."
                ),
            }

        if text.startswith(("/help", "/commands", "/start")):
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
            if public_domain:
                base_url = f"https://{public_domain}".rstrip("/")
            elif settings.webapp_url:
                base_url = settings.webapp_url.rstrip("/")
            else:
                base_url = "http://localhost:8000"

            dash_url = f"{base_url}/?user_id={user_id}"
            help_text = (
                "🤖 **Welcome to Nexus Prime — Your AI Life Copilot**\n\n"
                "Here are the core features & quick shortcuts you can use:\n\n"
                "💳 **Expenses & Spending**\n"
                "• Type or voice: *'Spent $12.50 at Starbucks'* or snap a receipt photo\n"
                "• `/expenses` — View recent spending\n"
                "• `/split <amount> with <friends>` — Split bills & generate WhatsApp text\n"
                "• `/email` — Connect email (Gmail/Outlook) for automated receipt tracking\n\n"
                "💵 **Money In**\n"
                "• Type: *'Loren repaid me $13'* or *'salary SGD 3500 from my employer'*\n"
                "• `/credit <amount> from <person or company>` — Log money received\n"
                "• `/income` — View recent incoming money\n\n"
                "• `/disconnect_email [gmail|outlook|all]` — Remove mailbox access\n\n"
                "📋 **Tasks & Reminders**\n"
                "• Type or voice: *'Remind me tomorrow at 9am to submit report'*\n"
                "• `/tasks` — View your todo list & pending IOUs\n"
                "• `/jobs` — View scheduled background alerts\n\n"
                "🛒 **Groceries & Commute**\n"
                "• Type: *'Add oat milk and eggs to grocery list'*\n"
                "• `/groceries` — View shopping list\n"
                "• Ask: *'Bus timings at 08057'* or *'Route to Orchard'*\n\n"
                "🚀 **Web Cockpit & Analytics**\n"
                "• `/dashboard` — Open your personal visual cockpit\n\n"
                f"{dash_url}"
            )
            buttons = [
                [{"text": "🚀 Open Web Cockpit", "url": dash_url}],
                [
                    {"text": "💰 Recent Expenses", "callback_data": "cmd:expenses"},
                    {"text": "💵 Recent Incoming", "callback_data": "cmd:income"},
                    {"text": "📋 Pending Tasks", "callback_data": "cmd:tasks"},
                ],
                [
                    {"text": "📬 Connect Gmail", "callback_data": "cmd:email"},
                    {"text": "👥 Split a Bill", "callback_data": "cmd:split"},
                ],
            ]
            return {
                "status": "ok",
                "text": help_text,
                "reply_markup": {"inline_keyboard": buttons},
            }

        if text.startswith(("/dashboard", "/web", "/app", "/link")):
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
            if public_domain:
                base_url = f"https://{public_domain}".rstrip("/")
            elif settings.webapp_url:
                base_url = settings.webapp_url.rstrip("/")
            else:
                base_url = "http://localhost:8000"

            dash_url = f"{base_url}/?user_id={user_id}"
            welcome_text = (
                "👋 **Welcome to Nexus Prime Cockpit!**\n\n"
                "Tap below to open your personal financial cockpit, view expenses, and manage tasks:\n\n"
                f"{dash_url}"
            )
            return {
                "status": "ok",
                "text": welcome_text,
                "reply_markup": {"inline_keyboard": [[{"text": "🚀 Open Web Cockpit", "url": dash_url}]]},
            }

        if text.startswith(("/connect_email", "/gmail", "/email")):
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
            if public_domain:
                base_url = f"https://{public_domain}".rstrip("/")
            elif settings.webapp_url:
                base_url = settings.webapp_url.rstrip("/")
            else:
                base_url = "http://localhost:8000"

            lines = [
                "📬 **Connect Your Email for Automated Expense Tracking**\n\n"
                "Tap a link to securely authorize read-only receipt tracking. "
                "Your transactions will be automatically extracted and organized on your personal dashboard:"
            ]
            if settings.google_client_id and settings.google_client_secret:
                lines.append(f"\n🟢 Gmail: {base_url}/auth/gmail?user_id={user_id}")
            if settings.microsoft_client_id and settings.microsoft_client_secret:
                lines.append(f"\n🔵 Outlook: {base_url}/auth/outlook?user_id={user_id}")
            if len(lines) == 1:
                lines.append(
                    "\n\n⚠️ Email OAuth isn't configured for any provider on this service yet. "
                    "Ask the operator to set the OAuth client credentials."
                )
            return {
                "status": "ok",
                "text": "\n".join(lines),
            }

        if text.startswith(("/disconnect_email", "/disconnect_mail")):
            from capabilities.email.tools import disconnect_email_account

            parts = text.split()
            provider = parts[1].lower() if len(parts) > 1 else "all"
            result = await disconnect_email_account(user_id=user_id, provider=provider)
            if result.get("status") == "invalid_provider":
                return {
                    "status": "error",
                    "text": "Usage: `/disconnect_email gmail`, `/disconnect_email outlook`, or `/disconnect_email all`.",
                }
            if result.get("count"):
                names = ", ".join(result["disconnected"]).title()
                return {
                    "status": "ok",
                    "disconnected": result["disconnected"],
                    "text": f"🔌 Disconnected {names}. I will no longer read those mailboxes or use them for automatic expense tracking.",
                }
            target = "your mailboxes" if provider in {"all", "email", "both"} else f"your {provider} account"
            return {"status": "ok", "text": f"ℹ️ No connected credential found for {target}."}

        if text.startswith("/split"):
            from capabilities.expenses.tools import split_bill_expense
            
            amt_match = re.search(r"\$?([0-9]+(?:\.[0-9]{1,2})?)", text)
            if not amt_match:
                return {
                    "status": "ok",
                    "text": "Usage: `/split <amount> [merchant] with [Friend 1], [Friend 2]...`\n\nExamples:\n`/split 160 Haidilao with Alex, Chloe, Ben and me`\n`/split 30 with Alex, I pay $20 and Alex pays $10`",
                }
            amt = float(amt_match.group(1))

            names_part = text
            if "with " in text.lower():
                names_part = text.lower().split("with ", 1)[1]
            elif "between " in text.lower():
                names_part = text.lower().split("between ", 1)[1]
            elif "for " in text.lower():
                names_part = text.lower().split("for ", 1)[1]

            merchant = "Dinner / Outing"
            m_match = re.search(rf"\$?{amt_match.group(1)}\s+([a-zA-Z0-9\s]+?)(?:\s+with|\s+between|\s+for|$)", text, re.IGNORECASE)
            if m_match and m_match.group(1).strip():
                merchant = m_match.group(1).strip().title()

            custom_amounts = parse_custom_split_amounts(text)
            if custom_amounts:
                people_names = [name for name in custom_amounts if name != "Me"]
            else:
                people_names = [p.strip().title() for p in re.split(r",|\band\b|&", names_part) if p.strip()]

            res = await split_bill_expense.ainvoke({
                "user_id": user_id,
                "total_amount": amt,
                "merchant": merchant,
                "people": people_names,
                "custom_amounts": custom_amounts or None,
            })
            return {
                "status": "ok",
                "text": res.get("reply_text") or res.get("message"),
                "reply_markup": {"inline_keyboard": res.get("buttons")} if res.get("buttons") else None,
            }

        if text.startswith("/expenses"):
            from capabilities.expenses.tools import get_user_expenses

            rows = await get_user_expenses.ainvoke({"user_id": user_id, "limit": 10})
            if not rows:
                return {"status": "ok", "expenses": [], "text": "💰 No expenses logged yet."}
            lines = [
                f"• {row['date'][:10]} {row['currency']} {row['amount']:.2f} — "
                f"{row['merchant']} ({row['category']})"
                for row in rows
            ]
            total = sum(row["amount"] for row in rows)
            lines.append(f"\nTotal (last {len(rows)}): {rows[0]['currency']} {total:.2f}")
            return {
                "status": "ok",
                "expenses": rows,
                "text": "💰 Recent expenses:\n" + "\n".join(lines),
            }

        if text.startswith(("/tasks", "/todo")):
            from core.models import TaskItem
            from core.db import async_session_factory
            from sqlmodel import select

            async with async_session_factory() as session:
                tasks = (await session.execute(
                    select(TaskItem).where(TaskItem.user_id == user_id, TaskItem.status == "todo").order_by(TaskItem.created_at.desc())
                )).scalars().all()

            if not tasks:
                return {"status": "ok", "tasks": [], "text": "📋 You have no pending tasks! Great job."}
            lines = []
            for t in tasks[:15]:
                rem_info = f" (⏰ {t.reminder_type})" if t.reminder_type != "none" else ""
                due_info = f" — due {t.due_at.strftime('%m/%d %H:%M')}" if t.due_at else ""
                lines.append(f"• #{t.id} <b>{t.title}</b> [{t.priority.upper()}]{due_info}{rem_info}")
            return {
                "status": "ok",
                "tasks": [t.model_dump() for t in tasks],
                "text": "📋 <b>Pending Tasks:</b>\n" + "\n".join(lines),
            }

        if text.startswith(("/boards", "/whiteboards")):
            from core.models import WhiteboardProject, WhiteboardBlock
            from core.db import async_session_factory
            from sqlmodel import select

            async with async_session_factory() as session:
                projects = (await session.execute(
                    select(WhiteboardProject).where(WhiteboardProject.user_id == user_id).order_by(WhiteboardProject.updated_at.desc())
                )).scalars().all()

            if not projects:
                return {
                    "status": "ok",
                    "projects": [],
                    "text": "🎨 **Whiteboard & Planning Canvas**\n\nNo active boards yet! Create one on the dashboard or tell me what to plan (e.g. *\"Plan my trip to Tokyo\"*).",
                }

            lines = ["🎨 **Active Planning Whiteboards:**\n"]
            for p in projects[:10]:
                lines.append(f"• {p.emoji_icon} **{p.title}** (`#{p.id}` · *{p.category}*)")
            lines.append("\n💡 *Ask me in chat to research options, build itineraries, or pin items to any board!*")
            return {
                "status": "ok",
                "projects": [p.model_dump() for p in projects],
                "text": "\n".join(lines),
            }

        if text.startswith("/del_job"):
            from core.scheduler import delete_scheduled_job

            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                deleted = await delete_scheduled_job(int(parts[1]), user_id)
                return {
                    "status": "ok",
                    "deleted": deleted,
                    "text": (
                        f"🗑️ Reminder #{parts[1]} deleted."
                        if deleted
                        else f"⚠️ No reminder #{parts[1]} found."
                    ),
                }
            return {
                "status": "error",
                "message": "Usage: /del_job <job_id>",
                "text": "Usage: /del_job <job_id> — find IDs with /jobs.",
            }

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

        # Telegram location pins -> detect timezone and update the profile.
        location = message.get("location") or (message.get("venue") or {}).get("location")
        if location and location.get("latitude") is not None:
            from core.shared_tools.location import (
                resolve_timezone_from_coordinates,
                resolve_timezone_from_coordinates_api,
            )

            lat = location["latitude"]
            lon = location["longitude"]
            tz = await resolve_timezone_from_coordinates_api(lat, lon)
            tz = tz or resolve_timezone_from_coordinates(lat, lon)
            updated = await update_user_timezone(user_id, tz) if tz else False
            if updated:
                await send_telegram_message(
                    chat_id, f"📍 Got your location — timezone set to *{tz}*."
                )
            else:
                await send_telegram_message(
                    chat_id, "📍 Got your location, but couldn't pin down a timezone for it."
                )
            self._log_conversation("IN", chat_id, "<location pin>")
            return {"status": "ok", "location": True, "timezone": tz}

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
                        reply_markup = slash_res.get("reply_markup")
                        sent = await send_telegram_message(
                            chat_id, reply_text, reply_markup=reply_markup
                        )
                        self._log_conversation(
                            "OUT" if sent else "SEND-FAIL", chat_id, reply_text
                        )
                return slash_res

            # Conversational timezone changes: "I just landed in Tokyo".
            if text and (
                "timezone" in text.lower()
                or "landed in" in text.lower()
                or "arrived in" in text.lower()
            ):
                from core.shared_tools.location import resolve_timezone_from_location

                detected_tz = resolve_timezone_from_location(text)
                if detected_tz:
                    tz_updated = await update_user_timezone(user_id, detected_tz)
                    if tz_updated:
                        await send_telegram_message(
                            chat_id, f"✅ Timezone updated to *{detected_tz}*."
                        )
                        return {"status": "ok", "timezone": detected_tz, "updated": True}

            content_blocks = await self.process_multimodal_attachments(message)
            has_media = any(
                isinstance(block, dict) and block.get("type") == "media"
                for block in content_blocks
            )
            human_msg = HumanMessage(
                content=content_blocks if has_media or len(content_blocks) > 1 else text
            )

            config = {"configurable": {"thread_id": str(chat_id)}}
            initial_state = {
                "messages": [human_msg],
                "user_id": user_id,
                "current_timezone": profile.current_timezone,
                "active_domain": None,
            }

            result = await get_assistant_graph().ainvoke(initial_state, config=config)
            interrupts = result.get("__interrupt__")
            if interrupts:
                for interrupt_item in interrupts:
                    payload = getattr(interrupt_item, "value", interrupt_item)
                    if not isinstance(payload, dict) or not payload.get("prompt"):
                        continue
                    buttons = [
                        [
                            {
                                "text": button.get("text", "OK"),
                                "callback_data": button.get("callback_data", "{}"),
                            }
                        ]
                        for button in payload.get("buttons", [])
                    ]
                    sent = await send_telegram_message(
                        chat_id,
                        str(payload["prompt"]),
                        reply_markup={"inline_keyboard": buttons} if buttons else None,
                    )
                    self._log_conversation("OUT" if sent else "SEND-FAIL", chat_id, payload["prompt"])
                return {"status": "ok", "interrupted": True}
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
        except Exception as exc:  # noqa: BLE001 - never leave the user hanging
            import traceback

            tb_str = traceback.format_exc()
            traceback.print_exc()

            # Asynchronously report production bug to Gemini SRE audit and GitHub Issues
            try:
                from core.audit import report_production_bug

                asyncio.create_task(
                    report_production_bug(
                        user_id=user_id,
                        thread_id=str(user_id or chat_id),
                        error_context=f"TelegramIngress runtime exception: {exc}",
                        error_traceback=tb_str,
                        detection_source="runtime_exception",
                    )
                )
            except Exception:  # noqa: BLE001
                pass

            await send_telegram_message(
                chat_id,
                "😵‍💫 Sorry, something glitched on my end — I've logged it and I'm on it. Try again in a minute?",
            )
            return {"status": "ok", "processed": False, "error": str(exc)}
        finally:
            stop_event.set()
            typing_task.cancel()
            await asyncio.gather(typing_task, return_exceptions=True)


# Global default ingress adapter
telegram_ingress = TelegramIngress()
