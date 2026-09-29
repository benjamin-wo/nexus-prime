"""Test doubles for the model, Telegram, receipt reading and exchange rates."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field

from nexus.agent.receipts import ReceiptDraft
from nexus.agent.service import Button
from nexus.application.fx import Rate
from nexus.application.ports import MailboxGrant, MailboxRevoked
from nexus.domain.email import ExpenseDraft, FetchedEmail, Screening
from nexus.domain.errors import InvalidInput
from nexus.infra.llm.factory import ChatModels

NOW = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)  # noon in Singapore

type Step = AIMessage | Callable[[list[BaseMessage]], AIMessage] | Exception


def call(name: str, **args: Any) -> AIMessage:
    """A model turn that calls one tool."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{uuid4()}"}])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


class ScriptedModel(BaseChatModel):
    """Replies with a fixed script, one step per model call; records what it saw."""

    script: list[Any] = Field(default_factory=list)
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, Any]:
        return self

    def _next(self, messages: list[BaseMessage]) -> ChatResult:
        self.seen.append(list(messages))
        if not self.script:
            raise AssertionError("the model was called more times than scripted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._next(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._next(messages)


def scripted(*steps: Step) -> ScriptedModel:
    return ScriptedModel(script=list(steps), seen=[])


def models(primary: BaseChatModel) -> ChatModels:
    return ChatModels(primary=primary, fallbacks=(), vision=None, description="scripted")


@dataclass
class FakeReceipts:
    draft: ReceiptDraft
    reads: int = 0

    async def read(self, image: bytes, mime_type: str, caption: str | None) -> ReceiptDraft:
        self.reads += 1
        return self.draft


@dataclass
class Sent:
    chat_id: int
    text: str
    buttons: list[list[Button]] | None


@dataclass
class FakeTelegram:
    sent: list[Sent] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    cleared: list[tuple[int, int]] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    app_buttons: list[tuple[int, str, str]] = field(default_factory=list)
    menu_button: tuple[str, str] | None = None

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[Button]] | None = None
    ) -> None:
        self.sent.append(Sent(chat_id, text, buttons))

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        self.answered.append(callback_id)

    async def clear_buttons(self, chat_id: int, message_id: int) -> None:
        self.cleared.append((chat_id, message_id))

    async def download(self, file_id: str) -> bytes:
        return self.files[file_id]

    async def bot_username(self) -> str:
        return "nexus_test_bot"

    async def send_app_button(self, chat_id: int, text: str, label: str, url: str) -> None:
        self.app_buttons.append((chat_id, label, url))

    async def set_menu_button(self, label: str, url: str) -> None:
        self.menu_button = (label, url)


@dataclass
class FakeRates:
    """Published rates per (base, quote): {effective day: value}. Answers like the
    real provider: the latest rate on or before the day asked for."""

    published: dict[tuple[str, str], dict[date, str]] = field(default_factory=dict)
    asked: list[tuple[str, str, date]] = field(default_factory=list)

    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        self.asked.append((base, quote, on))
        days = [d for d in self.published.get((base, quote), {}) if d <= on]
        if not days:
            return None
        day = max(days)
        return Rate(base, quote, Decimal(self.published[(base, quote)][day]), day)


@dataclass
class FakeBucket:
    """An in-memory private bucket. Download links name the key and expiry, unsigned."""

    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    fail_deletes: bool = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def delete(self, key: str) -> None:
        if self.fail_deletes:
            raise OSError("bucket unavailable")
        self.objects.pop(key, None)

    def download_url(self, key: str, *, filename: str, expires: timedelta) -> str:
        return f"https://bucket.test/{key}?expires={int(expires.total_seconds())}&name={filename}"


@dataclass
class FakeMailbox:
    """A mailbox holding ``emails``; ``grant`` is what signing in returns."""

    emails: dict[str, FetchedEmail] = field(default_factory=dict)
    grant: MailboxGrant = field(
        default_factory=lambda: MailboxGrant("ann@gmail.com", "refresh-token-1")
    )
    revoked: bool = False
    fetched: list[str] = field(default_factory=list)
    revocations: list[str] = field(default_factory=list)

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://accounts.test/auth?state={state}&redirect_uri={redirect_uri}"

    async def exchange(self, code: str, *, redirect_uri: str) -> MailboxGrant:
        if code == "no-permission":
            raise InvalidInput("Nexus needs permission to read your email to find receipts")
        return self.grant

    async def access_token(self, refresh_token: str) -> str:
        if self.revoked:
            raise MailboxRevoked("revoked")
        assert refresh_token == self.grant.refresh_token
        return "access"

    async def search(self, access_token: str, query: str, *, after: datetime) -> list[str]:
        return [i for i, e in self.emails.items() if e.received_at > after]

    async def fetch(self, access_token: str, message_id: str) -> FetchedEmail:
        self.fetched.append(message_id)
        return self.emails[message_id]

    async def revoke(self, refresh_token: str) -> None:
        self.revocations.append(refresh_token)


@dataclass
class FakeForwarding:
    """Forwarding addresses: one inbox per owner, holding ``emails`` once made."""

    emails: dict[str, FetchedEmail] = field(default_factory=dict)
    inboxes: dict[str, str] = field(default_factory=dict)  # owner -> inbox id
    deleted: list[str] = field(default_factory=list)

    async def create_inbox(self, owner: str) -> tuple[str, str]:
        inbox = self.inboxes.setdefault(owner, f"inbox-{len(self.inboxes) + 1}")
        return inbox, f"nexus-{inbox}@agentmail.test"

    async def access_token(self, refresh_token: str) -> str:
        if refresh_token in self.deleted:
            raise MailboxRevoked("deleted")
        return refresh_token

    async def search(self, access_token: str, query: str, *, after: datetime) -> list[str]:
        return [i for i, e in self.emails.items() if e.received_at > after]

    async def fetch(self, access_token: str, message_id: str) -> FetchedEmail:
        return self.emails[message_id]

    async def revoke(self, refresh_token: str) -> None:
        self.deleted.append(refresh_token)


class FakeEmailReader:
    """Receipts are emails whose subject contains 'receipt'; the amount and merchant
    come from lines like 'Total: 18.50' and 'Merchant: Grab' in the text."""

    async def triage(self, email: FetchedEmail) -> Screening:
        if "receipt" in email.subject.lower():
            return Screening(True, "receipt")
        return Screening(False, "promotion")

    async def extract(self, email: FetchedEmail) -> ExpenseDraft:
        fields = dict(line.split(": ", 1) for line in email.text.splitlines() if ": " in line)
        return ExpenseDraft(
            fields.get("Total"), fields.get("Currency"), fields.get("Merchant"), fields.get("Date")
        )


def fake_email(
    message_id: str,
    subject: str,
    text: str = "",
    *,
    at: datetime = NOW,
    sender: str = "no-reply@grab.com",
    pdf: bytes | None = None,
) -> FetchedEmail:
    return FetchedEmail(message_id, at, sender, subject, text, pdf)
