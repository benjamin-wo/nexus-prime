"""A PDF's pages as images, for reading a scanned statement: rendered in memory with
pdfium, nothing written anywhere."""

import io
import logging

import pypdfium2 as pdfium

from nexus.domain.errors import InvalidInput

log = logging.getLogger(__name__)

# 144 dpi in greyscale: a statement's small print stays legible to the model, and a
# page is about 200 KB as a JPEG.
SCALE = 2.0
MAX_SIDE = 2200
MAX_SCANNED_PAGES = 10


def page_images(data: bytes, password: str | None = None) -> list[bytes]:
    """Every page as a JPEG; InvalidInput past MAX_SCANNED_PAGES or if it won't open
    (the text reader has already checked the password)."""
    try:
        pdf = pdfium.PdfDocument(data, password=password)
    except pdfium.PdfiumError as exc:
        log.warning("couldn't open a PDF to render it: %s", type(exc).__name__)
        raise InvalidInput("couldn't read that PDF") from exc
    try:
        if len(pdf) > MAX_SCANNED_PAGES:
            raise InvalidInput(
                f"that scan has {len(pdf)} pages; Nexus reads up to {MAX_SCANNED_PAGES} at a "
                "time. Split it into parts, or use your bank's CSV export"
            )
        images: list[bytes] = []
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                picture = page.render(scale=SCALE, grayscale=True).to_pil()
            finally:
                page.close()
            picture.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            picture.convert("L").save(out, format="JPEG", quality=85)
            images.append(out.getvalue())
        return images
    finally:
        pdf.close()
