"""Tiny text PDFs for tests: one line of Helvetica per row, top to bottom."""

import io

from pypdf import PdfReader, PdfWriter


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str], password: str | None = None) -> bytes:
    stream = (
        "BT /F1 9 Tf 12 TL 40 800 Td\n"
        + "".join(f"({_escape(line)}) Tj T*\n" for line in lines)
        + "ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    data = out.getvalue()
    if password is None:
        return data
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.encrypt(password, algorithm="AES-128")
    locked = io.BytesIO()
    writer.write(locked)
    return locked.getvalue()


def make_scan(pages: list[list[str]]) -> bytes:
    """A scanned PDF: each page a picture of its lines, with no text in it at all."""
    from PIL import Image, ImageDraw

    pictures = []
    for lines in pages:
        picture = Image.new("L", (1190, 1684), 255)  # A4 at 144 dpi
        draw = ImageDraw.Draw(picture)
        for n, line in enumerate(lines):
            draw.text((80, 80 + n * 28), line, fill=0)
        pictures.append(picture)
    out = io.BytesIO()
    pictures[0].save(out, format="PDF", save_all=True, append_images=pictures[1:], resolution=144)
    return out.getvalue()
