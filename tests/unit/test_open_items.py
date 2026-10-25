"""Open items: the summariser's OPEN section is parsed in code, capped, and aged out."""

from datetime import UTC, datetime, timedelta

from nexus.agent.open_items import MAX_ITEMS, MAX_TEXT, OpenItem, carry, live, split_reply

NOW = datetime(2026, 10, 25, 11, 28, tzinfo=UTC)


def item(text: str, age: timedelta = timedelta(0)) -> OpenItem:
    return {"text": text, "since": (NOW - age).isoformat()}


def test_the_items_follow_the_summary_and_stay_out_of_it() -> None:
    reply = (
        "The user planned dinner at Jumbo on Sat 24 Oct.\n\n"
        "OPEN:\n"
        "- Jumbo dinner on Sat 24 Oct, about 80; the user will send the exact amount\n"
        "- Rent receipt to send\n"
    )
    summary, items = split_reply(reply)
    assert summary == "The user planned dinner at Jumbo on Sat 24 Oct."
    assert items == [
        "Jumbo dinner on Sat 24 Oct, about 80; the user will send the exact amount",
        "Rent receipt to send",
    ]


def test_none_means_there_are_none() -> None:
    for tail in ("OPEN: none", "OPEN: None.", "OPEN:\nnone", "**OPEN:** (none)", "open: -"):
        summary, items = split_reply(f"A summary.\n{tail}")
        assert summary == "A summary."
        assert items == [], tail


def test_a_reply_without_the_section_is_all_summary_and_says_nothing_of_items() -> None:
    assert split_reply("  Just a summary.\nOn two lines.  ") == (
        "Just a summary.\nOn two lines.",
        None,
    )


def test_stray_whitespace_bullets_and_numbering_are_tolerated() -> None:
    reply = (
        "Summary.\r\n\r\n   OPEN :   \r\n  *  first   thing \r\n\r\n 2)  second\tthing  \r\n   \r\n"
    )
    assert split_reply(reply) == ("Summary.", ["first thing", "second thing"])


def test_an_item_on_the_same_line_as_the_marker_counts() -> None:
    assert split_reply("Summary.\nOPEN: send the receipt") == ("Summary.", ["send the receipt"])


def test_more_than_the_cap_are_cut_and_long_items_trimmed() -> None:
    lines = "\n".join(f"- item {n}" for n in range(MAX_ITEMS + 3))
    _, items = split_reply(f"Summary.\nOPEN:\n{lines}\n- {'x' * 500}")
    assert items is not None and len(items) == MAX_ITEMS
    assert items[0] == "item 0" and items[-1] == f"item {MAX_ITEMS - 1}"
    _, long = split_reply(f"Summary.\nOPEN:\n- {'x' * 500}")
    assert long is not None and len(long[0]) == MAX_TEXT and long[0].endswith("…")


def test_repeated_items_are_listed_once() -> None:
    assert split_reply("S.\nOPEN:\n- Pay Ann\n- pay ann\n") == ("S.", ["Pay Ann"])


def test_a_reply_that_is_only_the_section_has_no_summary() -> None:
    assert split_reply("OPEN: none") == ("", [])


def test_items_older_than_three_days_are_dropped() -> None:
    fresh = item("fresh", timedelta(days=2, hours=23))
    stale = item("stale", timedelta(days=3, minutes=1))
    assert live([stale, fresh], NOW) == [fresh]
    assert live(None, NOW) == []


def test_items_with_an_unreadable_time_are_dropped_and_the_list_is_capped() -> None:
    bad: OpenItem = {"text": "no time", "since": "someday"}
    many = [item(f"n{n}") for n in range(MAX_ITEMS + 2)]
    assert live([bad, *many], NOW) == many[:MAX_ITEMS]


def test_no_section_keeps_the_items_so_far_less_the_stale_ones() -> None:
    keep, old = item("keep", timedelta(days=1)), item("old", timedelta(days=4))
    assert carry([keep, old], None, NOW) == [keep]


def test_a_listed_item_keeps_its_first_time_and_a_new_one_starts_now() -> None:
    earlier = item("Pay Ann", timedelta(days=2))
    carried = carry([earlier], ["pay ann", "Send receipt"], NOW)
    assert carried == [
        {"text": "pay ann", "since": earlier["since"]},
        {"text": "Send receipt", "since": NOW.isoformat()},
    ]


def test_an_empty_list_clears_everything() -> None:
    assert carry([item("done")], [], NOW) == []
