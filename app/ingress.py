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
from core.llm import extract_llm_text
from core.models import UserProfile
from core.scheduler import list_active_jobs, run_now, update_user_timezone
from orchestrator.graph import get_assistant_graph


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
                        select(TaskItem).where(TaskItem.id == task_id)
                    )).scalar_one_or_none()
                    if task:
                        task.status = "done"
                        task.completed_at = datetime.utcnow()
                        task.is_reminder_active = False
                        session.add(task)
                        await session.commit()
                        remove_task_reminder(task.id)
                        title = task.title

                reply_text = f"✅ Marked <b>{title}</b> as done! Great job."
                self._log_conversation("CALLBACK", chat_id, f"td:{task_id}")
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text="Marked as done! 🎉")
                if chat_id:
                    await send_telegram_message(chat_id, reply_text)
                    self._log_conversation("OUT", chat_id, reply_text)
                return {
                    "status": "ok",
                    "action": "task_completed",
                    "task_id": task_id,
                    "reply": reply_text,
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
                reply_text = f"⏰ Snoozed <b>{title}</b> for 1 hour."
                self._log_conversation("CALLBACK", chat_id, f"ts:{task_id}")
                if callback_query_id:
                    await answer_telegram_callback(callback_query_id, text="Snoozed 1h ⏰")
                if chat_id:
                    await send_telegram_message(chat_id, reply_text)
                    self._log_conversation("OUT", chat_id, reply_text)
                return {
                    "status": "ok",
                    "action": "task_snoozed",
                    "task_id": task_id,
                    "reply": reply_text,
                }
            except Exception as exc:
                print(f"[CALLBACK] error snoozing task {callback_data}: {exc}")

        if callback_data.startswith("pb:"):
            # pb:<project_id> or pb:<project_id>:<title>
            parts = callback_data.split(":", 2)
            proj_id_str = parts[1] if len(parts) > 1 else "1"
            try:
                proj_id = int(proj_id_str)
                from core.models import WhiteboardProject
                from core.db import async_session_factory
                from sqlmodel import select

                proj_title = "Whiteboard"
                async with async_session_factory() as session:
                    proj = (await session.execute(
                        select(WhiteboardProject).where(WhiteboardProject.id == proj_id)
                    )).scalar_one_or_none()
                    if proj:
                        proj_title = f"{proj.emoji_icon} {proj.title}"

                reply_text = f"📌 Pinned to <b>{proj_title}</b>! You can view and refine it anytime on your web canvas."
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

        if text.startswith(("/dashboard", "/start", "/web", "/app", "/link")):
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
            }

        if text.startswith(("/connect_email", "/gmail", "/email")):
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
            if public_domain:
                base_url = f"https://{public_domain}".rstrip("/")
            elif settings.webapp_url:
                base_url = settings.webapp_url.rstrip("/")
            else:
                base_url = "http://localhost:8000"

            connect_url = f"{base_url}/auth/gmail?user_id={user_id}"
            return {
                "status": "ok",
                "text": (
                    "📬 **Connect Your Gmail for Automated Expense Tracking**\n\n"
                    "Tap below to securely authorize read-only receipt tracking with Google. "
                    "Your transactions will be automatically extracted and organized on your personal dashboard:\n\n"
                    f"{connect_url}"
                ),
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
                        sent = await send_telegram_message(chat_id, reply_text)
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

            traceback.print_exc()
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
