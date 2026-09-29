from typing import Any, Protocol

import httpx

from nexus.agent.service import Button

MAX_TEXT = 4096
MAX_DOWNLOAD = 10 * 1024 * 1024


class TelegramError(RuntimeError):
    pass


class TelegramClient(Protocol):
    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[Button]] | None = None
    ) -> None: ...
    async def answer_callback(self, callback_id: str, text: str | None = None) -> None: ...
    async def clear_buttons(self, chat_id: int, message_id: int) -> None: ...
    async def download(self, file_id: str) -> bytes: ...
    async def bot_username(self) -> str: ...
    async def send_app_button(self, chat_id: int, text: str, label: str, url: str) -> None: ...
    async def set_menu_button(self, label: str, url: str) -> None: ...


def _button(button: Button) -> dict[str, str]:
    """``url:`` buttons open a link (in the phone's browser); the rest call back."""
    if button.data.startswith("url:"):
        return {"text": button.label, "url": button.data.removeprefix("url:")}
    return {"text": button.label, "callback_data": button.data}


def keyboard(buttons: list[list[Button]]) -> dict[str, Any]:
    return {"inline_keyboard": [[_button(b) for b in row] for row in buttons]}


class HttpTelegramClient:
    """Bot API over HTTPS. Plain text only, so user content can't inject markup."""

    def __init__(self, token: str, http: httpx.AsyncClient) -> None:
        self._base = f"https://api.telegram.org/bot{token}"
        self._files = f"https://api.telegram.org/file/bot{token}"
        self._http = http
        self._username: str | None = None

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        response = await self._http.post(f"{self._base}/{method}", json=payload, timeout=20)
        body = response.json()
        if not body.get("ok"):
            # Never include the URL: it contains the bot token.
            raise TelegramError(f"{method} failed: {body.get('description', response.status_code)}")
        return body.get("result")

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[Button]] | None = None
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:MAX_TEXT]}
        if buttons:
            payload["reply_markup"] = keyboard(buttons)
        await self._call("sendMessage", payload)

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:200]
        await self._call("answerCallbackQuery", payload)

    async def clear_buttons(self, chat_id: int, message_id: int) -> None:
        await self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )

    async def download(self, file_id: str) -> bytes:
        info = await self._call("getFile", {"file_id": file_id})
        if int(info.get("file_size") or 0) > MAX_DOWNLOAD:
            raise TelegramError("file too large")
        response = await self._http.get(f"{self._files}/{info['file_path']}", timeout=30)
        if response.status_code != 200:
            raise TelegramError(f"download failed: {response.status_code}")
        if len(response.content) > MAX_DOWNLOAD:
            raise TelegramError("file too large")
        return response.content

    async def bot_username(self) -> str:
        if self._username is None:
            me = await self._call("getMe", {})
            self._username = str(me["username"])
        return self._username

    async def send_app_button(self, chat_id: int, text: str, label: str, url: str) -> None:
        """A message with one button that opens ``url`` as a Mini App inside Telegram."""
        await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:MAX_TEXT],
                "reply_markup": {"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]},
            },
        )

    async def set_menu_button(self, label: str, url: str) -> None:
        """The default menu button (next to the message box) opens ``url`` as a Mini App."""
        await self._call(
            "setChatMenuButton",
            {"menu_button": {"type": "web_app", "text": label, "web_app": {"url": url}}},
        )

    async def webhook_info(self) -> dict[str, Any]:
        info: dict[str, Any] = await self._call("getWebhookInfo", {})
        return info

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
        )
