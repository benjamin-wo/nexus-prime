"""What the model reads of the history: messages from an earlier day say when they were
sent, and the day turning is pointed out once."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from nexus.agent.graph import SENT_AT, _history, _line

MADRID = ZoneInfo("Europe/Madrid")
SAT_NIGHT = datetime(2026, 10, 24, 20, 51, tzinfo=UTC)  # 22:51 in Madrid
SUN_MORNING = datetime(2026, 10, 25, 10, 28, tzinfo=UTC)  # 11:28 in Madrid
NOTE = "[It's now Sun 25 Oct; the messages above are from Sat 24 Oct or earlier.]\n"


def human(content: str | list[str | dict[Any, Any]], at: datetime | None) -> HumanMessage:
    extra = {SENT_AT: at.isoformat()} if at else {}
    return HumanMessage(content=content, additional_kwargs=extra)


def texts(messages: list[AnyMessage]) -> list[str]:
    return [str(m.content) for m in messages]


def test_yesterdays_message_is_stamped_and_the_new_day_is_noted() -> None:
    messages: list[AnyMessage] = [
        human("lets go to Sitges tomorrow", SAT_NIGHT),
        AIMessage(content="Sure."),
        human("brunch?", SUN_MORNING),
    ]
    shown = _history(messages, SUN_MORNING, MADRID)
    assert texts(shown) == [
        "[Sat 24 Oct, 22:51] lets go to Sitges tomorrow",
        "Sure.",
        NOTE + "brunch?",
    ]
    assert [type(m) for m in shown] == [type(m) for m in messages]


def test_the_stored_messages_are_not_changed() -> None:
    messages: list[AnyMessage] = [
        human("hi", SAT_NIGHT),
        AIMessage(content="yo"),
        human("x", SUN_MORNING),
    ]
    _history(messages, SUN_MORNING, MADRID)
    assert texts(messages) == ["hi", "yo", "x"]
    assert messages[0].additional_kwargs == {SENT_AT: SAT_NIGHT.isoformat()}


def test_messages_from_the_same_local_day_are_left_alone() -> None:
    later = datetime(2026, 10, 24, 21, 30, tzinfo=UTC)
    messages: list[AnyMessage] = [human("a", SAT_NIGHT), AIMessage(content="b"), human("c", later)]
    assert texts(_history(messages, later, MADRID)) == ["a", "b", "c"]


def test_the_day_is_the_users_local_day_not_utc() -> None:
    # 23:30 UTC on Sat is already Sun 01:30 in Madrid: the same day as a 11:28 Sun message.
    late = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
    messages: list[AnyMessage] = [human("a", late), AIMessage(content="b"), human("c", SUN_MORNING)]
    assert texts(_history(messages, SUN_MORNING, MADRID)) == ["a", "b", "c"]


def test_messages_without_a_stamp_are_untouched() -> None:
    messages: list[AnyMessage] = [
        human("old", None),
        AIMessage(content="ok"),
        human("new", SUN_MORNING),
    ]
    assert texts(_history(messages, SUN_MORNING, MADRID)) == ["old", "ok", "new"]  # no note either
    mixed: list[AnyMessage] = [
        human("old", None),
        human("sat", SAT_NIGHT),
        human("new", SUN_MORNING),
    ]
    assert texts(_history(mixed, SUN_MORNING, MADRID)) == [
        "old",
        "[Sat 24 Oct, 22:51] sat",
        NOTE + "new",
    ]


def test_the_note_comes_once_not_on_later_messages_of_the_day() -> None:
    soon = datetime(2026, 10, 25, 10, 40, tzinfo=UTC)
    messages: list[AnyMessage] = [
        human("sat", SAT_NIGHT),
        AIMessage(content="a"),
        human("brunch?", SUN_MORNING),
        AIMessage(content="b"),
        human("thanks", soon),
    ]
    assert texts(_history(messages, soon, MADRID)) == [
        "[Sat 24 Oct, 22:51] sat",
        "a",
        "brunch?",
        "b",
        "thanks",
    ]


def test_list_content_is_stamped_on_its_text_and_images_are_left_alone() -> None:
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    messages: list[AnyMessage] = [
        human([image, {"type": "text", "text": "this one"}], SAT_NIGHT),
        human([image], SAT_NIGHT),
        human(["plain part"], SAT_NIGHT),
        human("brunch?", SUN_MORNING),
    ]
    shown = _history(messages, SUN_MORNING, MADRID)
    assert shown[0].content == [image, {"type": "text", "text": "[Sat 24 Oct, 22:51] this one"}]
    assert shown[1].content == [{"type": "text", "text": "[Sat 24 Oct, 22:51]"}, image]
    assert shown[2].content == ["[Sat 24 Oct, 22:51] plain part"]
    assert messages[0].content == [image, {"type": "text", "text": "this one"}]  # stored: as was


def test_tool_calls_stay_paired_with_their_results() -> None:
    call = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}])
    result = ToolMessage(content="done", tool_call_id="c1")
    messages: list[AnyMessage] = [
        human("log it", SAT_NIGHT),
        call,
        result,
        AIMessage(content="Logged."),
        human("and now?", SUN_MORNING),
    ]
    shown = _history(messages, SUN_MORNING, MADRID)
    assert shown[1] is call and shown[2] is result
    assert [m.id for m in shown] == [m.id for m in messages]


def test_the_summariser_sees_when_each_user_line_was_sent() -> None:
    assert _line(human("protest now", SAT_NIGHT), MADRID) == "User [Sat 24 Oct, 22:51]: protest now"
    assert _line(human("old", None), MADRID) == "User: old"
