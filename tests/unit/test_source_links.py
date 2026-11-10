"""Source links under a web answer: readable labels, one button per site, at most three,
public https pages only, and the same limits across a turn's searches. Every site here
is made up or an example."""

from nexus.agent.service import Button
from nexus.channels.telegram.client import keyboard
from nexus.domain.source_links import (
    MAX_LABEL,
    MAX_SOURCES,
    merge,
    site,
    site_name,
    source_button,
    source_buttons,
    source_rows,
)

A = "https://www.hardwarezone.com.sg/tech-news/console-prices"
B = "https://forums.hardwarezone.com.sg/threads/console-deals.1"
C = "https://www.xe.com/currencyconverter/"
D = "https://sg.emb-japan.go.jp/visa/"
E = "https://news.example.com/kaya-evals/latest"
F = "https://www.mom.gov.sg/passes"


def test_a_site_is_the_domain_without_www_and_subdomains() -> None:
    assert site(A) == site(B) == "hardwarezone.com.sg"
    assert site("https://en.wikipedia.org/wiki/X") == "wikipedia.org"
    assert site("https://www.bbc.co.uk/news/1") == "bbc.co.uk"
    assert site(F) == "mom.gov.sg"


def test_labels_are_short_site_names_with_an_arrow() -> None:
    assert source_button(A, "Console prices in Singapore - HardwareZone") == (
        "HardwareZone ↗",
        f"src:{A}",
    )
    assert source_button(C, "XE Currency Converter - XE") == ("XE ↗", f"src:{C}")
    assert source_button(E, "Example Daily: the latest") == ("Example Daily ↗", f"src:{E}")
    # With no help from the title, the domain's name: a short one in capitals.
    assert site_name(F, "Work passes") == "MOM"
    assert site_name(D, "Embassy of Japan in Singapore") == "Emb Japan"
    assert site_name(B, "Console deals") == "Hardwarezone"
    # A title with the site in a long headline is no label: the domain's name is used,
    # unless the title writes it as a word of its own.
    long = "A very long headline about console prices at HardwareZone this week"
    assert site_name(A, long) == "HardwareZone"


def test_a_label_never_goes_past_the_width_a_phone_button_has() -> None:
    url = "https://averyveryverylongdomainnameindeed.com/page"
    label, _ = source_button(url, "Page") or ("", "")
    assert len(label) <= MAX_LABEL and label.endswith("… ↗")
    for url, title in [(A, "x"), (C, "x"), (D, "x"), (E, "x"), (F, "x")]:
        label, _ = source_button(url, title) or ("", "")
        assert 0 < len(label) <= MAX_LABEL


def test_only_public_https_pages_get_a_button() -> None:
    assert source_button("http://example.com/a", "A") is None
    assert source_button("javascript:alert(1)", "A") is None
    assert source_button("https://10.0.0.1/a", "A") is None
    assert source_button("https://localhost/a", "A") is None
    assert source_button("https://user:pw@example.com/a", "A") is None
    assert source_button("", "A") is None


def test_one_button_per_site_and_three_at_most() -> None:
    pages = [(A, "HardwareZone"), (B, "Forum"), ("http://x.example.org/a", "Plain"), (C, "XE")]
    assert [d for _, d in source_buttons(pages)] == [f"src:{A}", f"src:{C}"]
    many = [(A, "a"), (C, "b"), (D, "c"), (E, "d"), (F, "e")]
    assert len(source_buttons(many)) == MAX_SOURCES == 3
    assert source_buttons([]) == []


def test_buttons_go_two_to_a_row() -> None:
    rows = source_rows([(A, "HardwareZone"), (C, "XE"), (E, "Example Daily")])
    assert [[label for label, _ in row] for row in rows] == [
        ["HardwareZone ↗", "XE ↗"],
        ["Example Daily ↗"],
    ]
    assert source_rows([(A, "HardwareZone")]) == [[("HardwareZone ↗", f"src:{A}")]]
    assert source_rows([("http://example.com", "x")]) == []


def test_two_searches_in_a_turn_still_show_three_sources_at_most() -> None:
    first = source_rows([(A, "HardwareZone"), (C, "XE")])
    second = source_rows([(B, "Forum"), (D, "Emb"), (E, "Example Daily"), (F, "MOM")])
    rows = merge([*first, *second])
    flat = [d for row in rows for _, d in row]
    # The forum is the same site as the first search's page; the rest, in order, to 3.
    assert flat == [f"src:{A}", f"src:{C}", f"src:{D}"]
    assert [len(row) for row in rows] == [2, 1]


def test_merging_leaves_other_buttons_alone_and_puts_sources_last() -> None:
    confirm = [("Confirm", "hitl:1:y"), ("Cancel", "hitl:1:n")]
    mixed = [("Open it", "url:https://example.com/a"), ("XE ↗", f"src:{C}")]
    rows = merge([mixed, confirm, [("HardwareZone ↗", f"src:{A}")]])
    assert rows == [
        [("Open it", "url:https://example.com/a")],
        confirm,
        [("XE ↗", f"src:{C}"), ("HardwareZone ↗", f"src:{A}")],
    ]
    assert merge([]) == []


def test_telegram_shows_a_source_as_a_link_button_not_a_callback() -> None:
    markup = keyboard(
        [
            [Button("HardwareZone ↗", f"src:{A}"), Button("Open", "url:https://example.com/x")],
            [Button("Undo", "act:undo")],
        ]
    )
    assert markup == {
        "inline_keyboard": [
            [
                {"text": "HardwareZone ↗", "url": A},
                {"text": "Open", "url": "https://example.com/x"},
            ],
            [{"text": "Undo", "callback_data": "act:undo"}],
        ]
    }
