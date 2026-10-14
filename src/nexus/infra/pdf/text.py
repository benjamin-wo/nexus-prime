"""The text of a PDF, line by line, with pypdf. Nothing is written anywhere."""

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from nexus.domain.errors import InvalidInput

log = logging.getLogger(__name__)

MAX_BYTES = 10_000_000
MAX_PAGES = 60


class PasswordNeeded(Exception):
    """The PDF is locked; ``wrong`` when a password was given and didn't open it."""

    def __init__(self, *, wrong: bool) -> None:
        super().__init__("wrong password" if wrong else "password needed")
        self.wrong = wrong


def pdf_lines(data: bytes, password: str | None = None) -> list[str]:
    return pdf_text(data, password)[0]


def pdf_text(
    data: bytes, password: str | None = None, *, page_break: str | None = None
) -> tuple[list[str], int]:
    """The lines of text and the number of pages (a scan has pages but little text),
    with ``page_break`` as a line between pages when given."""
    if len(data) > MAX_BYTES:
        raise InvalidInput("the PDF is larger than 10 MB")
    if not data.startswith(b"%PDF"):
        raise InvalidInput("that isn't a PDF")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            if not password:
                raise PasswordNeeded(wrong=False)
            if not reader.decrypt(password):
                raise PasswordNeeded(wrong=True)
        if len(reader.pages) > MAX_PAGES:
            raise InvalidInput(f"the PDF has more than {MAX_PAGES} pages")
        lines: list[str] = []
        for number, page in enumerate(reader.pages):
            if page_break is not None and number:
                lines.append(page_break)
            # Layout mode keeps a row's date, description and amount on one line.
            text = page.extract_text(extraction_mode="layout") or ""
            lines.extend(" ".join(line.split()) for line in text.splitlines() if line.strip())
    except (PdfReadError, ValueError, KeyError) as exc:
        # The reason stays out of the logs: it can quote the statement.
        log.warning("couldn't read a PDF: %s", type(exc).__name__)
        raise InvalidInput("couldn't read that PDF") from exc
    return lines, len(reader.pages)
