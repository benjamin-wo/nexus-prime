"""Regenerate the Nexus brand assets from one pixel-grid definition.

    uv run python scripts/brand_icons.py

The mark is a pixel-art "N" with a small spark at its top right, rebuilt from the
owner's brand board (docs/brand/nexus-brand-board.png). The grid below is the single
source of truth; this script writes everything derived from it:

* web/src/assets/nexus-mark*.svg      the mark (light backgrounds, dark backgrounds, one-colour)
* web/src/assets/nexus-wordmark*.svg  NEXUS in blocky pixels, with the AI LIFESTYLE MANAGER line
* web/src/assets/nexus-lockup*.svg    mark + wordmark side by side
* web/src/assets/nexusBrand.generated.ts   the same rects as data, for components/NexusMark.tsx
* web/public/*.png                    favicon, touch icon, app icons (plain and maskable)
* web/public/nexus-telegram-avatar.png

Only Pillow is needed (it is in the backend venv). Nothing here reads the board image;
fidelity to it was checked by eye (see docs/brand/README.md).
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "web" / "src" / "assets"
PUBLIC = ROOT / "web" / "public"

# --- Palette -------------------------------------------------------------------------
MIDNIGHT = "#0B1020"
BLUE = "#2563EB"
TEAL = "#22D3EE"
LIME = "#A3FF12"
CLOUD = "#F8FAFC"

# --- The mark ------------------------------------------------------------------------
# Units are "u": one N cell is 4u wide and 4u tall, so the spark can sit on a finer
# grid than the letter, as it does on the board. The N is 13 cells wide, 11 tall.
#
#   B blue   T teal   L lime
#   b blue on light backgrounds, teal on dark ones (the diagonal reads as one band there)
#   K midnight, left stroke   (dark backgrounds: blue)
#   k midnight, diagonal edge (dark backgrounds: teal, so the diagonal stays one band)
CELL = 4
N_GRID = [
    "..BBBB.......",
    "KKBBBBB...LLL",
    "KKBbbbb...LLL",
    "KKKbbbbT..LLL",
    "KKK.bbbT..LLL",
    "KKK..kkTTTLLL",
    "KKK...kTTTTLL",
    "TTT....kTTTTT",
    "TTT.....kTTTT",
    "LLL.....kTTTT",
    "LLL......kTTT",
]

# The spark: arms (x, y, w, h, colour) and a diamond of rows (y, width), centred on x = 57
# (in u, relative to the top-left of the N; y grows downwards, so the spark is above row 0).
SPARK_CX = 57.5
SPARK_ARMS = [
    (56, -12, 3, 4, "L"),  # top
    (63, -3, 4, 3, "L"),  # right
    (48, -3, 4, 3, "T"),  # left
    (56, 6, 3, 4, "T"),  # bottom
]
SPARK_DIAMOND = [3, 7, 9, 9, 9, 9, 9, 9, 9, 9, 7, 3]  # row widths, from y = -7 to y = 4
SPARK_TOP = -7

MARK_VIEWBOX = (0, -12, 67, 56)  # x, y, w, h in u

HEX = {"B": BLUE, "b": BLUE, "T": TEAL, "L": LIME, "K": MIDNIGHT, "k": MIDNIGHT}

Rect = tuple[float, float, float, float, str]  # x, y, w, h, key


def mark_rects() -> list[Rect]:
    """The mark as rects in u, with each run of equal cells merged (no seams, few rects)."""
    runs: list[Rect] = []
    for r, row in enumerate(N_GRID):
        c = 0
        while c < len(row):
            key = row[c]
            if key == ".":
                c += 1
                continue
            end = c
            while end + 1 < len(row) and row[end + 1] == key:
                end += 1
            runs.append((c * CELL, r * CELL, (end - c + 1) * CELL, CELL, key))
            c = end + 1
    # merge vertically where a run sits exactly on top of an identical one
    merged: list[Rect] = []
    for x, y, w, h, k in runs:
        for i, (mx, my, mw, mh, mk) in enumerate(merged):
            if (mx, mw, mk) == (x, w, k) and my + mh == y:
                merged[i] = (mx, my, mw, mh + h, mk)
                break
        else:
            merged.append((x, y, w, h, k))
    spark: list[Rect] = [(x, y, w, h, k) for x, y, w, h, k in SPARK_ARMS]
    for i, width in enumerate(SPARK_DIAMOND):
        spark.append((SPARK_CX - width / 2, SPARK_TOP + i, width, 1, "L"))
    # merge diamond rows of equal width
    out: list[Rect] = []
    for x, y, w, h, k in spark:
        if out and out[-1][4] == k == "L" and out[-1][0] == x and out[-1][2] == w and out[-1][1] + out[-1][3] == y:
            px, py, pw, ph, pk = out[-1]
            out[-1] = (px, py, pw, ph + h, pk)
        else:
            out.append((x, y, w, h, k))
    return merged + out


def variant_rects(variant: str) -> list[tuple[float, float, float, float, str]]:
    """Rects with real colours. variant: light | dark | cloud | ink.

    light  the mark on white / Cloud / pale backgrounds (Midnight pixels visible)
    dark   on Midnight: the left stroke's Midnight pixels become Blue, the diagonal's and the inner blue become Teal
    cloud  one colour, Cloud, for the accent-coloured button and other dark or saturated fills
    ink    one colour, Midnight, for Lime or other very light fills
    """
    out = []
    for x, y, w, h, k in mark_rects():
        if variant == "light":
            colour = HEX[k]
        elif variant == "dark":
            colour = {"K": BLUE, "k": TEAL, "b": TEAL}.get(k, HEX[k])
        elif variant == "cloud":
            colour = CLOUD
        elif variant == "ink":
            colour = MIDNIGHT
        else:
            raise ValueError(variant)
        out.append((x, y, w, h, colour))
    return out


def num(v: float) -> str:
    return f"{v:g}"


def rect_svg(rects: list[tuple[float, float, float, float, str]], dx: float = 0, dy: float = 0, s: float = 1) -> str:
    return "".join(
        f'<rect x="{num(x * s + dx)}" y="{num(y * s + dy)}" width="{num(w * s)}" height="{num(h * s)}" fill="{c}"/>'
        for x, y, w, h, c in rects
    )


def svg_doc(view: tuple[float, float, float, float], body: str, title: str) -> str:
    vx, vy, vw, vh = view
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{num(vx)} {num(vy)} {num(vw)} {num(vh)}" '
        f'width="{num(vw)}" height="{num(vh)}" shape-rendering="crispEdges" role="img" aria-label="{title}">'
        f"<title>{title}</title>{body}</svg>\n"
    )


# --- The wordmark --------------------------------------------------------------------
# Blocky capitals, two cells thick, 10 cells tall. A cell is 2 units; the tagline's pixel is 1 unit.
GLYPHS = {
    "N": [
        "##.....##",
        "####...##",
        "####...##",
        "##.##..##",
        "##.##..##",
        "##..##.##",
        "##..##.##",
        "##...####",
        "##...####",
        "##.....##",
    ],
    "E": [
        "########",
        "########",
        "##......",
        "##......",
        "######..",
        "######..",
        "##......",
        "##......",
        "########",
        "########",
    ],
    "X": [
        "##.....##",
        "##.....##",
        ".##...##.",
        ".##...##.",
        "..#####..",
        "..#####..",
        ".##...##.",
        ".##...##.",
        "##.....##",
        "##.....##",
    ],
    "U": [
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        ".######.",
        ".######.",
    ],
    "S": [
        ".######.",
        "########",
        "##......",
        "##......",
        ".######.",
        "..######",
        "......##",
        "......##",
        "########",
        ".######.",
    ],
}
TINY = {
    "A": [".##.", "#..#", "####", "#..#", "#..#"],
    "I": ["####", ".##.", ".##.", ".##.", "####"],
    "L": ["#...", "#...", "#...", "#...", "####"],
    "F": ["####", "#...", "###.", "#...", "#..."],
    "E": ["####", "#...", "###.", "#...", "####"],
    "S": [".###", "#...", ".##.", "...#", "###."],
    "T": ["####", ".##.", ".##.", ".##.", ".##."],
    "Y": ["#..#", "#..#", ".##.", ".##.", ".##."],
    "M": ["#..#", "####", "####", "#..#", "#..#"],
    "N": ["#..#", "##.#", "####", "#.##", "#..#"],
    "G": [".###", "#...", "#.##", "#..#", ".###"],
    "R": ["###.", "#..#", "###.", "#.#.", "#..#"],
}
WORD = "NEXUS"
TAGLINE = "AI LIFESTYLE MANAGER"
WORD_GAP = 2  # cells between letters
WORD_CELL = 2  # units
TAG_PX = 1  # units
TAG_PITCH = 5  # pixels per tagline character (4 wide + 1 gap)
TAG_GAP = 7  # units between wordmark and tagline


def bitmap_rects(rows: list[str], ox: float, oy: float, cell: float) -> list[tuple[float, float, float, float]]:
    """Horizontal runs of a bitmap, merged vertically (same x and width on consecutive rows)."""
    runs: list[list[float]] = []
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            if row[c] != "#":
                c += 1
                continue
            e = c
            while e + 1 < len(row) and row[e + 1] == "#":
                e += 1
            x, w = ox + c * cell, (e - c + 1) * cell
            for run in runs:
                if run[0] == x and run[2] == w and run[1] + run[3] == oy + r * cell:
                    run[3] += cell
                    break
            else:
                runs.append([x, oy + r * cell, w, cell])
            c = e + 1
    return [(a, b, c_, d) for a, b, c_, d in runs]


def wordmark_rects(tagline: bool) -> tuple[list[tuple[float, float, float, float]], float, float]:
    """Rects (x, y, w, h) in units and the (width, height) of the block."""
    rects: list[tuple[float, float, float, float]] = []
    x = 0.0
    for i, ch in enumerate(WORD):
        rows = GLYPHS[ch]
        rects += bitmap_rects(rows, x, 0, WORD_CELL)
        x += (len(rows[0]) + (WORD_GAP if i < len(WORD) - 1 else 0)) * WORD_CELL
    width = x
    height = 10 * WORD_CELL
    if tagline:
        ty = height + TAG_GAP
        # spread the line across the full width of the word: pitch is a fixed 5 px, so it is 100 units
        tx = 0.0
        for ch in TAGLINE:
            if ch != " ":
                rects += bitmap_rects(TINY[ch], tx, ty, TAG_PX)
            tx += TAG_PITCH * TAG_PX
        height = ty + 5 * TAG_PX
    return rects, width, height


def wordmark_svg(colour: str, tagline: bool, title: str) -> str:
    rects, w, h = wordmark_rects(tagline)
    body = "".join(f'<rect x="{num(x)}" y="{num(y)}" width="{num(rw)}" height="{num(rh)}" fill="{colour}"/>' for x, y, rw, rh in rects)
    return svg_doc((0, 0, w, h), body, title)


def lockup_svg(variant: str, title: str) -> str:
    """Mark and wordmark side by side. The mark's cell is 3 units here, the wordmark's 2, the tagline's pixel 1
    (all x4 so every edge is a whole number)."""
    k = 4
    mark = variant_rects(variant)
    u = 0.75 * k  # mark u in lockup units
    mx0, my0, mw, mh = MARK_VIEWBOX
    word_colour = CLOUD if variant == "dark" else MIDNIGHT
    wrects, ww, wh = wordmark_rects(True)
    # N bottom (y = 44u) lines up with the tagline's bottom; the mark's own top (spark) rises above the cap line
    n_bottom = 44 * u
    dy = wh * k - n_bottom
    gap = 6 * u
    mark_w = mw * u
    body = rect_svg(mark, -mx0 * u, dy, u)
    ox = mark_w + gap
    body += "".join(
        f'<rect x="{num(ox + x * k)}" y="{num(y * k)}" width="{num(w * k)}" height="{num(h * k)}" fill="{word_colour}"/>'
        for x, y, w, h in wrects
    )
    top = min(0.0, dy + my0 * u)
    # shift everything so the top is 0
    body = f'<g transform="translate(0 {num(-top)})">{body}</g>'
    total_h = max(wh * k, dy + 44 * u) - top
    return svg_doc((0, 0, ox + ww * k, total_h), body, title)


# --- PNG rendering -------------------------------------------------------------------
def rgb(hex_: str) -> tuple[int, int, int]:
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def render_icon(
    size: int,
    *,
    cell_px: float,
    radius: float = 0.0,
    background: str | None = MIDNIGHT,
    variant: str = "dark",
    supersample: int = 1,
) -> Image.Image:
    """An icon: the mark centred (bounding box including the spark) on a square.

    cell_px is the size of one N cell in output pixels; with supersample = 1 and a whole
    number the pixels stay perfectly crisp. radius is the corner radius as a share of size
    (0 for full-bleed squares such as the touch icon, which iOS rounds itself).
    """
    ss = supersample
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        if radius:
            d.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(radius * big), fill=rgb(background) + (255,))
        else:
            d.rectangle((0, 0, big, big), fill=rgb(background) + (255,))
    u = cell_px * ss / CELL
    vx, vy, vw, vh = MARK_VIEWBOX
    ox = (big - vw * u) / 2 - vx * u
    oy = (big - vh * u) / 2 - vy * u
    for x, y, w, h, c in variant_rects(variant):
        x0, y0 = round(ox + x * u), round(oy + y * u)
        x1, y1 = round(ox + (x + w) * u), round(oy + (y + h) * u)
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=rgb(c) + (255,))
    if ss > 1:
        img = img.resize((size, size), Image.BOX)
    return img


def write_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print("wrote", path.relative_to(ROOT))


# --- Output --------------------------------------------------------------------------
def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def write_ts() -> None:
    mx, my, mw, mh = MARK_VIEWBOX
    wrects, ww, wh = wordmark_rects(True)
    plain, pw, ph = wordmark_rects(False)
    data = {
        "markViewBox": [mx, my, mw, mh],
        "mark": [[x, y, w, h, k] for x, y, w, h, k in mark_rects()],
        "wordmarkViewBox": [0, 0, pw, ph],
        "wordmark": [[x, y, w, h] for x, y, w, h in plain],
        "wordmarkTaglineViewBox": [0, 0, ww, wh],
        "wordmarkTagline": [[x, y, w, h] for x, y, w, h in wrects],
    }
    lines = [
        "// Generated by scripts/brand_icons.py from the pixel grid there. Do not edit by hand.",
        "// Mark cells are [x, y, w, h, key] in u (one N cell = 4u). Keys: B blue, b blue (teal on dark), T teal, L lime, K midnight",
        "// (left stroke), k midnight (diagonal edge). Wordmark rects are [x, y, w, h].",
        "",
        "export type MarkRect = readonly [x: number, y: number, w: number, h: number, key: string];",
        "export type WordRect = readonly [x: number, y: number, w: number, h: number];",
        "",
    ]
    for name, value in data.items():
        ts_type = {"mark": "readonly MarkRect[]", "wordmark": "readonly WordRect[]", "wordmarkTagline": "readonly WordRect[]"}.get(
            name, "readonly [number, number, number, number]"
        )
        lines.append(f"export const {name}: {ts_type} = {json.dumps(value, separators=(', ', ': '))};")
    write_text(ASSETS / "nexusBrand.generated.ts", "\n".join(lines) + "\n")


def main() -> None:
    mx, my, mw, mh = MARK_VIEWBOX
    view = MARK_VIEWBOX
    # SVGs
    write_text(ASSETS / "nexus-mark.svg", svg_doc(view, rect_svg(variant_rects("light")), "Nexus"))
    write_text(ASSETS / "nexus-mark-dark.svg", svg_doc(view, rect_svg(variant_rects("dark")), "Nexus"))
    write_text(ASSETS / "nexus-mark-cloud.svg", svg_doc(view, rect_svg(variant_rects("cloud")), "Nexus"))
    write_text(ASSETS / "nexus-mark-ink.svg", svg_doc(view, rect_svg(variant_rects("ink")), "Nexus"))
    write_text(ASSETS / "nexus-wordmark.svg", wordmark_svg(MIDNIGHT, True, "Nexus, AI lifestyle manager"))
    write_text(ASSETS / "nexus-wordmark-light.svg", wordmark_svg(CLOUD, True, "Nexus, AI lifestyle manager"))
    write_text(ASSETS / "nexus-lockup.svg", lockup_svg("light", "Nexus, AI lifestyle manager"))
    write_text(ASSETS / "nexus-lockup-dark.svg", lockup_svg("dark", "Nexus, AI lifestyle manager"))
    write_ts()

    # PNG icons. Whole-number cells keep the pixels crisp; the 32px favicon is supersampled.
    write_png(render_icon(32, cell_px=1.45, radius=0.22, supersample=16), PUBLIC / "favicon-32.png")
    write_png(render_icon(180, cell_px=7, radius=0, ), PUBLIC / "apple-touch-icon.png")
    write_png(render_icon(192, cell_px=7, radius=0.22), PUBLIC / "icon-192.png")
    write_png(render_icon(512, cell_px=19, radius=0.22), PUBLIC / "icon-512.png")
    # Maskable: full bleed, mark inside the central safe zone (a circle of 40% of the side); the
    # mark's half-diagonal is 44.4u, so at 4.5 px per u it reaches 197 px, inside the 205 px radius.
    write_png(render_icon(512, cell_px=18, radius=0), PUBLIC / "icon-maskable-512.png")
    write_png(render_icon(640, cell_px=24, radius=0), PUBLIC / "nexus-telegram-avatar.png")


if __name__ == "__main__":
    main()
