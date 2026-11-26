"""What the model reads of the conversation: the recent window, with messages from an
earlier local day stamped with when they were sent (moved out of ``graph``)."""

from collections.abc import Sequence
from datetime import UTC, datetime, tzinfo
from typing import Any, cast

from langchain_core.messages import AnyMessage, BaseMessage, HumanMessage

HISTORY_LIMIT = 40
SENT_AT = "nexus_sent_at"


def trim(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """The recent history, starting at a user message so no tool result is orphaned."""
    window = list(messages[-HISTORY_LIMIT:])
    for i, message in enumerate(window):
        if isinstance(message, HumanMessage):
            return window[i:]
    return window[-1:]


def sent_at(message: BaseMessage) -> datetime | None:
    """When the user sent this message, if it was stamped."""
    raw = message.additional_kwargs.get(SENT_AT)
    if not isinstance(raw, str):
        return None
    try:
        sent = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return sent if sent.tzinfo else sent.replace(tzinfo=UTC)


def day(moment: datetime) -> str:
    """ "Sat 24 Oct"."""
    return f"{moment:%a} {moment.day} {moment:%b}"


def when(moment: datetime) -> str:
    """ "Sat 24 Oct, 22:51"."""
    return f"{day(moment)}, {moment:%H:%M}"


def prefixed(message: HumanMessage, prefix: str) -> HumanMessage:
    """A copy of the message with ``prefix`` before its text; images are left alone."""
    content = message.content
    if isinstance(content, str):
        new: str | list[str | dict[str, Any]] = prefix + content
    else:
        parts = list(content)
        for i, part in enumerate(parts):
            if isinstance(part, str):
                parts[i] = prefix + part
                break
            if part.get("type") == "text":
                parts[i] = {**part, "text": prefix + str(part.get("text", ""))}
                break
        else:
            parts.insert(0, {"type": "text", "text": prefix.rstrip()})
        new = parts
    return message.model_copy(update={"content": new})


def history(messages: Sequence[AnyMessage], now: datetime, tz: tzinfo) -> list[AnyMessage]:
    """What the model reads: the recent history, with messages from an earlier local day
    stamped with when they were sent, and a note on the newest one when the day has
    turned since the one before it. Copies only; the stored messages are not touched.
    Messages without a stamp (older threads) are left as they are."""
    window = trim(messages)
    today = now.astimezone(tz).date()
    humans = [i for i, m in enumerate(window) if isinstance(m, HumanMessage)]
    shown = list(window)
    for i in humans:
        sent = sent_at(window[i])
        if sent is not None and sent.astimezone(tz).date() != today:
            shown[i] = prefixed(cast(HumanMessage, window[i]), f"[{when(sent.astimezone(tz))}] ")
    if len(humans) >= 2:
        latest, before = sent_at(window[humans[-1]]), sent_at(window[humans[-2]])
        if latest is not None and before is not None:
            then = before.astimezone(tz)
            if latest.astimezone(tz).date() > then.date():
                note = (
                    f"[It's now {day(now.astimezone(tz))}; the messages above are from "
                    f"{day(then)} or earlier.]\n"
                )
                shown[humans[-1]] = prefixed(cast(HumanMessage, shown[humans[-1]]), note)
    return shown
