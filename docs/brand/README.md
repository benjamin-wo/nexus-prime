# Nexus brand

The owner's brand board is `nexus-brand-board.png` in this folder. Everything below is rebuilt from it as
vector and generated from one pixel grid, so nothing here is a traced or scaled-up bitmap.

## Palette

| Name | Hex | Use |
| --- | --- | --- |
| Midnight | `#0B1020` | Dark surfaces, text on light, the N's dark pixels on light backgrounds |
| Nexus Blue | `#2563EB` | Brand colour, links and accents on light, the mark's top-left |
| Digital Teal | `#22D3EE` | The mark's diagonal, highlights and accents on dark |
| Lime | `#A3FF12` | The spark and the N's lower and right strokes; one small accent at a time |
| Cloud | `#F8FAFC` | Light surfaces, text on dark |

### Contrast (WCAG 2.x, computed from the hex values)

| Colour | on white | on Cloud | on Midnight | on Nexus Blue |
| --- | --- | --- | --- | --- |
| Midnight | 18.9 | 18.1 | | 3.7 |
| Nexus Blue | 5.2 | 4.9 | 3.7 | |
| Digital Teal | 1.8 | 1.7 | 10.5 | 2.9 |
| Lime | 1.2 | 1.2 | 15.2 | 4.2 |
| Cloud | 1.0 | | 18.1 | 4.9 |

What that means for text:

* **On white or Cloud**: Midnight (any size) and Nexus Blue (AA, 4.5:1 or more) are safe text colours. Teal and Lime are
  not: never use them for text, icons that carry meaning or thin lines on a light background. They are fine as fills
  next to a Midnight or Blue edge, as the mark uses them.
* **On Midnight**: Cloud, Teal and Lime are safe text colours. Nexus Blue is 3.7:1, so only for large text (24px, or 19px
  bold) and graphics, never for body text.
* **On Nexus Blue**: Cloud (4.9:1) is the text and mark colour. Midnight is 3.7:1, so large text only.
* **On Lime**: Midnight (15.2:1), nothing else.

## The mark

A pixel-art capital **N** with a small **spark** at its top right. The N is 13 cells wide and 11 tall; the spark sits
on a finer grid (a quarter of a cell). The pixels run from Nexus Blue at the top left, through Digital Teal on the
diagonal, to Lime on the lower and right strokes; the spark is Lime with Teal arms to the left and below.

Variants (all in `web/src/assets/`):

| File | Use |
| --- | --- |
| `nexus-mark.svg` | Full colour on white, Cloud or other light backgrounds. Midnight pixels on the left stroke and the diagonal's edge. |
| `nexus-mark-dark.svg` | Full colour on Midnight or other dark backgrounds. A Midnight pixel on Midnight would vanish, so the left stroke turns Nexus Blue and the diagonal's edge and the inner blue turn Digital Teal, as the dark app icon on the board does. |
| `nexus-mark-cloud.svg` | One colour, Cloud: on Nexus Blue, photos and other dark or saturated fills. |
| `nexus-mark-ink.svg` | One colour, Midnight: on Lime and other very light fills, and for one-colour print. |

In the app, `NexusMark` (`web/src/components/NexusMark.tsx`) draws the same rects inline. By default it switches between
the light and dark colouring with the theme; `variant="mono"` takes the surrounding text colour (used on the accent
buttons, where it follows `--on-accent`), `"cloud"` and `"ink"` match the files above.

Rules:

* Use the variant that reads on the background; do not put the light mark on Midnight or the dark one on white.
* Do not recolour pixels, stretch, rotate, add shadows or outlines, or round the pixel corners. Scale it uniformly.
* Keep the spark. The N alone is not the mark.
* **Minimum size**: 24px wide for the full mark on screen (smaller than that the spark's arms are under a pixel).
  Browser tabs use `favicon-32.png`, which is drawn for that size.
* **Clear space**: 3 cells (a quarter of the N's height) on every side, measured from the outer edge of the mark,
  spark included.
* The mark is 67 units wide (a cell is 4). At a width of 67 px, 134 px, 201 px and so on every unit is a whole number
  of pixels and the pixels are perfectly crisp. The SVGs use `shape-rendering="crispEdges"` for other sizes, which
  keeps edges hard but lets cells differ by a pixel.

## Wordmark and lockup

`NEXUS` in blocky pixel capitals (two cells thick, drawn from rects, no font to load), with the line
`AI LIFESTYLE MANAGER` under it in a 4 by 5 pixel monospace face, spread to the full width of the word.

| File | Use |
| --- | --- |
| `nexus-wordmark.svg` | Midnight, on light backgrounds |
| `nexus-wordmark-light.svg` | Cloud, on dark backgrounds |
| `nexus-lockup.svg` | Mark and wordmark side by side, light backgrounds |
| `nexus-lockup-dark.svg` | The same, dark backgrounds |

Minimum sizes: the letters at 16px tall; the tagline only when the wordmark is at least 200px wide (below that, use
`NexusWordmark` without `tagline`, which draws just the letters). Same clear space as the mark.

In the app, `NexusWordmark` draws the letters in the text colour around it.

## App icons

Rendered from the dark variant on a Midnight square. Files are in `web/public/`:

| File | Size | Notes |
| --- | --- | --- |
| `favicon-32.png` | 32 | Rounded square, supersampled for the tab size |
| `apple-touch-icon.png` | 180 | Full bleed square (iOS rounds it) |
| `icon-192.png`, `icon-512.png` | 192, 512 | Rounded square, `"purpose": "any"` in the manifest |
| `icon-maskable-512.png` | 512 | Full bleed, mark inside the central safe zone (a circle of 40% of the side), `"purpose": "maskable"` |
| `nexus-telegram-avatar.png` | 640 | Telegram crops it to a circle; the mark is well inside |

`web/public/manifest.webmanifest` names the app Nexus and uses Midnight for `background_color` and `theme_color`.

## Regenerating

The pixel grid lives in `scripts/brand_icons.py` (`N_GRID`, `SPARK_*`, the wordmark glyphs). To change the mark, edit it
there and run, from the repo root:

```
uv run python scripts/brand_icons.py
```

That rewrites every SVG in `web/src/assets/`, `web/src/assets/nexusBrand.generated.ts` (the data `NexusMark.tsx` draws
from; do not edit it by hand) and every PNG in `web/public/`. Only Pillow is needed; it is in the backend venv.
Nothing reads the board image: the grid was worked out from it by eye, zooming in on the large N and the dark app icon.
