"""The chat as kept: where a message came from, and long replies cut short."""

from nexus.domain.chat import MAX_TEXT, channel_of, clip


def test_where_a_message_came_from() -> None:
    assert channel_of("web:abc:1") == "web"
    assert channel_of("telegram:42:7") == "telegram"
    assert channel_of("tg:1:1") is None


def test_long_text_is_cut() -> None:
    assert clip("  hi  ") == "hi"
    long = clip("x" * (MAX_TEXT + 50))
    assert len(long) == MAX_TEXT and long.endswith("…")
