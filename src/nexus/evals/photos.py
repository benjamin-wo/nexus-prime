"""Receipt and travel screenshots for the evaluation set.

Drawn ones (made-up shops, apps, places, dates and totals) live in ``receipts/``. Real photos
aren't committed: this repository is public and they belong to whoever took
them, so only their link is kept, and the runner downloads each once into a
local cache that git ignores.
"""

import asyncio
from pathlib import Path

import httpx

DRAWN = Path(__file__).parent / "receipts"

# Real receipts, by link.
LINKED: dict[str, str] = {
    # Secret Recipe, Plaza Singapura: total 12.00 after a card discount, with a
    # subtotal of 10.26 printed below it; dated 16 Feb 2013.
    "secret-recipe": "https://cdn-sg.orstatic.com/userphoto/photo/0/CQ/002IL4FB783618A0C585CAlv.jpg",
}


def known(key: str) -> bool:
    return key in LINKED or (DRAWN / f"{key}.png").exists()


async def load(key: str, cache: Path) -> tuple[bytes, str]:
    """The photo's bytes and media type."""
    if key not in LINKED:
        return await asyncio.to_thread((DRAWN / f"{key}.png").read_bytes), "image/png"
    body, kind = cache / f"{key}.bin", cache / f"{key}.type"
    if not await asyncio.to_thread(body.exists):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(LINKED[key])
            response.raise_for_status()
        await asyncio.to_thread(cache.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(body.write_bytes, response.content)
        media = response.headers.get("content-type", "image/jpeg").split(";")[0]
        await asyncio.to_thread(kind.write_text, media)
    return await asyncio.to_thread(body.read_bytes), await asyncio.to_thread(kind.read_text)
