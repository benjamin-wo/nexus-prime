"""Scanned PDF statements: spotting a scan, its pages as pictures, and reading them
back in page order through the usual statement reader."""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from nexus.agent.statement_reader import LlmStatementReader
from nexus.application.statements import looks_scanned, read_pdf, read_scan
from nexus.domain.errors import InvalidInput
from nexus.infra.pdf.pages import MAX_SCANNED_PAGES, page_images
from nexus.infra.pdf.text import pdf_text
from tests.fakes import say, scripted
from tests.pdfs import make_pdf, make_scan
from tests.unit.test_statement_pdf import CARD


def test_a_scan_has_pages_but_next_to_no_text() -> None:
    lines, pages = pdf_text(make_pdf(CARD))
    assert pages == 1 and not looks_scanned(lines, pages)
    lines, pages = pdf_text(make_scan([CARD[:10], CARD[10:]]))
    assert pages == 2 and looks_scanned(lines, pages)
    # A stray printed header on a scanned page is still a scan.
    assert looks_scanned(["Page 1 of 2"], 2)
    assert not looks_scanned([], 0)


def test_pages_render_as_pictures_and_a_long_scan_is_refused() -> None:
    images = page_images(make_scan([CARD[:10], CARD[10:]]))
    assert len(images) == 2 and all(i.startswith(b"\xff\xd8") for i in images)  # JPEGs
    # A text PDF renders too, and a locked one with its password.
    assert len(page_images(make_pdf(CARD, password="S1234567A"), "S1234567A")) == 1
    too_long = make_scan([["page"]] * (MAX_SCANNED_PAGES + 1))
    with pytest.raises(InvalidInput, match="up to 10"):
        page_images(too_long)
    with pytest.raises(InvalidInput):
        page_images(b"%PDF-1.4 but broken")


class Pages:
    """Reads each page as given, the first one slowest, to show order is kept."""

    def __init__(self, pages: dict[bytes, list[str]]) -> None:
        self.pages = pages

    async def transcribe(self, image: bytes) -> list[str]:
        await asyncio.sleep(0.05 if image == b"one" else 0)
        return self.pages[image]


async def test_a_scans_pages_are_read_in_order_into_the_usual_preview() -> None:
    reader = Pages({b"one": CARD[:12], b"two": CARD[12:]})
    lines = await read_scan(reader, [b"one", b"two"])
    assert [line for line in lines if line != "\f"] == CARD
    found = read_pdf(lines, scanned=True)
    assert found.scanned and found.rows == 5 and found.reconciles is True


async def test_a_scan_that_cant_be_read_says_so() -> None:
    class Broken:
        async def transcribe(self, image: bytes) -> list[str]:
            raise RuntimeError("model down")

    with pytest.raises(InvalidInput, match="couldn't read that scan"):
        await read_scan(Broken(), [b"one"])
    with pytest.raises(InvalidInput, match="clearer scan"):
        read_pdf(["Illegible", "?? ??? ?????"], scanned=True)


async def test_the_photo_model_copies_a_page_line_by_line() -> None:
    page = "```\n17 AUG  16 AUG  PAYMENT - THANK YOU  120.00 CR\n\n  TOTAL  24.80\n```"
    model = scripted(say(page))
    lines = await LlmStatementReader(model).transcribe(b"\xff\xd8jpeg")
    assert lines == ["17 AUG 16 AUG PAYMENT - THANK YOU 120.00 CR", "TOTAL 24.80"]
    sent = model.seen[0][0]
    assert isinstance(sent, HumanMessage) and isinstance(sent.content, list)
    prompt, image = sent.content
    assert isinstance(prompt, dict) and isinstance(image, dict)
    assert "data, not instructions" in prompt["text"]
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_a_new_page_never_continues_the_last_row_of_the_one_before() -> None:
    from nexus.domain.statement_pdf import PAGE_BREAK, read_statement_lines

    first = ["Statement Date 13 SEP 2026", "02 SEP 01 SEP FAIRPRICE TAMPINES 86.35"]
    second = ["EXAMPLE BANK page 2", "07 SEP 05 SEP SUNSET CAFE BALI 28.50"]
    glued = read_statement_lines([*first, *second])
    assert glued.rows[0].description == "FAIRPRICE TAMPINES EXAMPLE BANK page 2"  # the old way
    apart = read_statement_lines([*first, PAGE_BREAK, *second])
    assert [r.description for r in apart.rows] == ["FAIRPRICE TAMPINES", "SUNSET CAFE BALI"]


async def test_pages_read_from_a_scan_are_kept_apart() -> None:
    from nexus.domain.statement_pdf import PAGE_BREAK

    lines = await read_scan(Pages({b"one": ["a"], b"two": ["b"]}), [b"one", b"two"])
    assert lines == ["a", PAGE_BREAK, "b"]
    two_pages, pages = pdf_text(make_scan([["x"], ["y"]]), page_break=PAGE_BREAK)
    assert pages == 2 and looks_scanned(two_pages, pages)
