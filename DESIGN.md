# Nexus Design System

## 1. Atmosphere & Identity

Nexus is a personal assistant. You talk to **Nexus Prime**, and Prime runs a suite of apps for you: Money,
Investments and Travel today, Health and Home & family later. You control it by voice and by intent ("I spent 12.50
on lunch", "what if I spend 500?"), and Prime composes the screen to answer: the **spoken canvas**
(`docs/adr/0002-spoken-canvas.md`), where Prime picks from hand-built views and fills them in, instead of
inventing interface. Because every view is hand-built, the look has to be one calm system that any app can
lend a view to. The direction is called **Paper**: calm and personal, like a good notebook.

The page is a warm paper ground (`#F3F1EC`; a warm near-black in dark). Structure comes from soft sections, not
cards around everything: a section is a slightly lighter surface (`#FBFAF7`) with a generous radius, hairline rows
inside it, and space between sections. Headings and every figure are set in Bricolage Grotesque, an inky grotesque
with tight tracking at large sizes; body copy and anything long is set in Newsreader, a bookish serif. Buttons are
pills. The current tab is marked by a 4px dot.

The month's one key figure is the headline of Home ("1,842.60", about 56px, with "left for November" in a plain
sentence under it), and every other figure is set the same way: tabular lining numerals, right-aligned where it
belongs to a row. There is one accent, **ink green** `#1D5A44`: primary buttons, links, money in, the current tab's
dot and the user's chat bubble. Attention is a warm rust as text (no tinted pill); an error or a month over
budget is red text. Nothing glows and nothing is a gradient. Copy is plain sentences ("about 230 a day"), and the
assistant speaks briefly: it never narrates the interface.

The app is light by default and dark when the phone (or Telegram) is. It is also a Telegram Mini App, and an iOS
WebView shell is coming, so every colour and size comes from a token and the dark scheme is a full second set of
the same roles.

Status: this file is the target. `web/src/styles.css` still holds the previous look (Midnight and Nexus Blue,
a gradient hero, Lime, glows, and Statement's values where they landed) until the token and component PRs land;
where a token's role goes away it is marked "to remove in the token PR", and `web/src/design.test.ts` lists what
still breaks the rules (see Rules).

## 2. Color

### Palette

The roles: **Ground** `#F3F1EC` (the page), **Section** `#FBFAF7` (a soft tinted block on the ground, also a sheet,
dialog or menu), **Ink** `#1D1C19` (text), **Hairline** `#EBE8E1` (row dividers inside a section), **Edge**
`#D8D4CA` (a stronger outline: a chip, the ask bar), **Ink green** `#1D5A44` (the one accent, and money in),
**Attention** `#9A4A12`, **Error** `#B42318`. Green fills carry white text (8.1:1). Nothing else is green or
tinted green.

The token names are the ones in `styles.css`, kept where the role survives so the token PR changes values without
renaming. `--bg-card` keeps its name but now means the soft section surface. Contrast is against the ground
`#F3F1EC` and the section surface `#FBFAF7` unless a column says otherwise.

| Role | Token | Value | Usage |
|------|-------|-------|-------|
| Surface/primary | --bg-shell | #F3F1EC | Page background (the ground) |
| Surface/secondary | --bg-frame | #F3F1EC | The rail and the chat panel: the ground itself, told apart by a hairline |
| Surface/section | --bg-card | #FBFAF7 | A soft section (radius 14 to 22px), a sheet, a dialog, a menu |
| Surface/interactive | --bg-card-hover | #F1EEE7 | A hovered or pressed row or control (text 4.9:1 muted, 14.7:1 ink) |
| Input surface | --bg-input | #FBFAF7 | Form controls and the ask bar, with a `--border-input` edge |
| Surface/raised | --bg-raised | #E9E6DE | The secondary button and a selected quiet chip (ink 13.7:1, secondary 9.4:1, muted 4.6:1) |
| Text/primary | --text-primary | #1D1C19 | Main content and figures (15.1:1 on the ground, 16.3:1 on a section) |
| Text/strong | --text-strong | #1D1C19 | Headings and the headline figure (Ink, the same as primary) |
| Text/secondary | --text-secondary | #3B3832 | Supporting content and Prime's prose (10.4:1 on the ground, 11.2:1 on a section) |
| Text/tertiary | --text-muted | #6B665C | Sub-lines, labels and hints (5.1:1 on the ground, 5.5:1 on a section) |
| Border/default | --border-card | #EBE8E1 | Hairline row dividers inside a section (decorative: 1.2:1) |
| Border/subtle | --border-subtle | #E4E1D8 | A quieter divider on the ground |
| Border/edge | --border-edge (new) | #D8D4CA | A stronger outline that is decoration, not a control's only mark: a chip's edge, a sheet's edge (1.3:1) |
| Border/input | --border-input (new) | #8C867A | The edge of a field, a checkbox and an off switch's track (3.2:1 on the ground, 3.5:1 on a section). Paper's mock uses the Edge for the ask bar; the real field needs this 3:1 edge |
| Accent | --accent | #1D5A44 | A primary button's fill (white text 8.1:1), the user's chat bubble, a link, the current tab's dot; nothing that cannot be pressed or that is not money in |
| Accent/hover | --accent-hover | #154634 | Primary hover and pressed (white text 10.7:1) |
| Accent/text | --accent-text | #1D5A44 | A link or a text button (7.2:1 on the ground, 7.7:1 on a section, 7.0:1 on a hovered row) |
| Accent/border | --accent-border | #1D5A44 | A field's focus edge |
| Focus ring | --ring | #1D5A44 | Every `:focus-visible` outline (7.2:1 on the ground); 2px, offset 2px |
| Text/on-accent | --on-accent | #FFFFFF | Text on an accent fill; white in both schemes |
| Status/money | --emerald-accent | #1D5A44 | Money in and completed states: the same ink green, as text (7.2:1 on the ground) |
| Status/warning | --status-warning | #9A4A12 | Attention and pending: a word or figure in this colour, no pill (5.5:1 on the ground, 6.0:1 on a section) |
| Status/error | --rose-accent | #B42318 | An error, deleting, a month over budget: text (5.8:1 on the ground, 6.3:1 on a section) |
| Link/underline | --link-underline | rgba(29,28,25,0.35) | The underline of a link inside text |
| Scrim/overlay | --overlay | rgba(29,28,25,0.45) | The dim behind a sheet or dialog |
| Switch/knob | --switch-thumb | #FFFFFF | The knob of a switch |
| Switch/off | --switch-off | #8C867A | The track of a switch that is off (3.2:1 on the ground) |
| Tab/active | --nav-active-glyph | #1D1C19 | The current place in the rail: ink text, with a 4px green dot |
| Button/hover | --btn-hover-bg | #E2DFD6 | A secondary button or chip under the pointer |
| Bar/background | --bar-bg | #F3F1EC | The phone's bottom bar: the ground, no rule needed |
| Bar/text | --bar-text | #6B665C | Inactive bottom bar labels (5.1:1) |
| Bar/active | --bar-text-active, --bar-indicator | #1D1C19, #1D5A44 | The current label (15.1:1) and the 4px dot under it (7.2:1) |
| Shadows | --shadow-modal, -drag, -thumb | (in `:root`) | Warm black at low opacity, only on a sheet or dialog, a dragged item and a button on a photo |

Money in is `--emerald-accent`, which is now the same value as `--accent`. The token stays separate so a later
change to either does not move the other, and so a figure's colour says what it is. Money out is ink, with its
sign.

The chart palette, for charts and category swatches (every mark is 3:1 or more on the ground and on a section):
`--pal-blue` is renamed in the token PR to `--pal-accent` #1D5A44 (7.2:1, the selected or pressable bar only),
`--pal-slate` #3B3832 (10.4:1), `--pal-track` #8C867A (3.2:1: past months, the rest bucket), `--pal-track-hover`
#6B665C (5.1:1), `--pal-wash` #E4E1D8 (the pale half of the planned-spend hatching). Category swatches go ink, slate,
then the track for the rest; this month's bar is `--text-strong`. Any chart value is also in text.

#### Going away (remove in the token PR)

These roles do not exist in Paper. Their tokens stay in `styles.css` until the component PRs stop using them, then
the token PR deletes them.

| Token | Was | Why it goes |
|-------|-----|-------------|
| --hero-top, --hero-mid, --hero-fade | The blue hero gradient | No gradient and no hero panel; Home's headline sits on the ground |
| --nexus-from, --nexus-to | The assistant button's gradient | The send button is a plain `--accent` pill |
| --accent-glow, --accent-soft, --emerald-soft, --status-warning-soft, --emerald-border, --status-warning-border, --sky-soft | Tinted pill and tile fills | No tinted pills or tiles; status is a word in its colour |
| --title-accent | The accent word in a page title | No coloured accent word |
| --cyan-accent, --cyan-text, --sky-accent, --sky-text, --pal-teal | Digital Teal and sky | One accent; they were decoration |
| --pal-lime, --bar-active-bg, and Lime in --bar-text-active, --bar-indicator, --nav-active-glyph | Lime "you are here" | No neon; the current place is ink with a 4px green dot |
| --tabs-bg, --tab-active-bg | The tab tray and open tab | Tabs are text, the current one with a dot |
| --accent-rgb, --danger-rgb | The accent and rose as r, g, b for tints and glows | Nothing is tinted or glows (`--rose-rgb` stays for the over-budget hatching until the chart PR) |
| --shadow-frame, -card, -tab, -bar, -slim | Soft shadows under cards, tabs and bars | Soft sections and space, not shadows, separate things |
| `.fab`'s blue glow shadow and the scrims named in `.photo-credit*` | Literals in rules | Become tokens in `:root` (see Rules) |

### Dark

The app follows the phone: the dark values apply under `@media (prefers-color-scheme: dark)` unless `<html data-theme="light">`, and always under `<html data-theme="dark">`; the same set is written out once for each (keep them identical). Inside Telegram, `telegram.ts` sets `data-theme` from `Telegram.WebApp.colorScheme` at start and on Telegram's `themeChanged`, since Telegram's theme can differ from the phone's; it then paints Telegram's header, background and bottom bar (`CHROME` in `theme.ts`: light page, header and bar `#F3F1EC`; dark page, header and bar `#161512`; there is no hero colour any more). `index.html` declares `color-scheme: light dark` and a `theme-color` for each (`#F3F1EC`, `#161512`), and `:root` sets `color-scheme`, so native inputs, selects and scrollbars follow. There is no manual toggle.

Paper's dark counterpart: a warm near-black ground with a slightly lighter section, warm off-white text (not pure white) and the green lifted so it reads as text. Same roles, values chosen to keep text at 4.5:1 and marks at 3:1.

| Token | Dark | Notes |
|-------|------|-------|
| --bg-shell, --bg-frame, --bar-bg | #161512 | Ground, rail, bottom bar |
| --bg-card, --bg-input | #1F1D19 | Sections, sheets, dialogs, menus, form controls |
| --bg-card-hover | #26241F | Hovered rows and controls (muted 5.8:1, ink 12.8:1) |
| --bg-raised | #2A2722 | The secondary button, a selected chip (ink 12.3:1, secondary 8.6:1, muted 5.5:1) |
| --text-primary, --text-strong | #EDE9E0 | 15.1:1 on the ground, 13.9:1 on a section |
| --text-secondary | #C9C4B8 | 10.5:1 on the ground, 9.7:1 on a section |
| --text-muted, --bar-text | #A39D90 | 6.8:1 on the ground, 6.2:1 on a section |
| --border-card | #2A2722 | Hairlines inside a section (decorative) |
| --border-subtle | #24221E | Quieter divider |
| --border-edge | #34312B | Stronger outline (decorative: 1.4:1) |
| --border-input, --switch-off, --pal-track | #8A8477 | 4.9:1 on the ground, 4.5:1 on a section; the knob `--switch-thumb` is #EDE9E0 |
| --accent, --accent-hover | #2F7A5C, #276149 | A fill, `--on-accent` white on it 5.2:1 and 7.3:1; the fill itself 3.5:1 on the ground, 3.3:1 on a section. The user's bubble is this fill |
| --accent-text, --accent-border, --ring, --pal-accent, --emerald-accent | #6FC29B | Links, money in, focus edge, rings: 8.6:1 on the ground, 7.9:1 on a section, 7.0:1 on a raised surface |
| --status-warning | #E39A5E | Attention: 7.9:1 on the ground, 7.3:1 on a section |
| --rose-accent | #F28B82 | Error: 7.6:1 on the ground, 7.0:1 on a section |
| --pal-slate, --pal-track-hover | #C9C4B8, #A39D90 | |
| --pal-wash | #34312B | |
| --bar-text-active, --nav-active-glyph | #EDE9E0 | The current label |
| --bar-indicator | #6FC29B | The 4px dot |
| --overlay | rgba(0,0,0,0.60) | |
| Shadows | black at 45–60% | Darker, because a shadow on a dark page hardly shows |

### Contrast

Every text pair is at least 4.5:1 and every mark (a progress bar or chart mark, a focus ring, a field's edge, a switch track, the current tab's dot) at least 3:1 in both schemes. Hairlines and the Edge are decoration, not marks that carry meaning (a row is also told apart by its spacing and content, and a field has its own 3:1 `--border-input`). The progress bar is ink on `--pal-wash`: 13.0:1 in light, 10.7:1 in dark. The user's chat bubble is white on the green fill: 8.1:1 light, 5.2:1 dark. The muted text on a raised surface is 4.6:1 light and 5.5:1 dark, the weakest pair in the set, so nothing smaller than 13px is muted on `--bg-raised`. The ticked checkbox's check is white on the accent in both schemes. Recompute and update the ratios here whenever a value in the tables above changes.

### Rules

- Two schemes of the same palette, light and dark; do not introduce a third visual theme.
- Every colour outside `:root` is a token: no hex, `rgb()`, `rgba()` or `hsl()` literals in rules (`rgba(var(--token-rgb), 0.16)` is fine). The only places a literal colour may appear are the `:root` token blocks: the light set, the dark set under `prefers-color-scheme`, and the dark set under `data-theme`. A colour that is the same in both schemes because what it sits on is (white text and scrims on a trip's cover photo, the photo credit) is a token in `:root` too (`--on-photo`, `--scrim-*`, to add in the token PR), not a literal in the rule.
- No gradients and no coloured or glowing shadow. A `box-shadow` is `none` or `var(--shadow-*)`.
- `font-family` is `inherit`, a `var(--font-*)` token, or one of the stacks in Typography.
- `web/src/design.test.ts` checks the three rules above against `styles.css`. It carries `KNOWN_OFFENDERS`, an explicit list of the rules that still break them (selector and kind). The test fails on a new violation, and also when a listed offender no longer exists, so the list only shrinks: when a PR fixes a rule it deletes that line; nobody adds one.
- Ink green is the one accent and marks only what can be pressed, plus money in and the user's own words (their chat bubble). Nothing decorative is green. Attention is rust text; an error is red text. No fill is tinted with a status colour.
- Light text sits only on an accent fill and on photos (under a dark fade).
- Colour never carries a meaning alone: money out and in are said by sign and word, state by text. Money in being green and money out being ink is a second cue, not the only one.
- New colours must be added here before they are used in CSS.

## 3. Typography

### Faces

- **Bricolage Grotesque** (variable, axes `opsz` 12–96 and `wght` 400–700) sets headings, the headline figure and all money figures, and, at its small optical size, every UI label, button, input, tab and chip. Tracking tightens as size grows: -0.03em to -0.05em on the headline and large figures, -0.02em on headings, none at label sizes.
- **Newsreader** (variable, `opsz` 6–72, `wght` 400–600; italic cut for quotations only) sets body copy and long text: Prime's replies, notes, captions that run to a sentence, empty-state lines, descriptions in rows. It is the voice that reads like a person.
- A figure and its words are different faces on purpose: "230" is Bricolage even inside a Newsreader sentence, with `font-variant-numeric: tabular-nums lining-nums`.

### Scale

Weights for Bricolage are 400 to 700 (600 for figures and headings, 500 for row titles and labels, 700 only for the headline); Newsreader 400, 500 for emphasis.

| Level | Face, size | Weight | Line Height | Usage |
|-------|------------|--------|-------------|-------|
| Headline | Bricolage, 3.5rem (56px), `opsz` 96, tracking -0.04em | 600 | 1.0 | The month's key figure on Home ("1,842.60"); 3rem under 360px. The currency is not beside it: the sentence under it says "left for November" |
| Display | Bricolage, 1.75rem, tracking -0.03em | 600 | 1.15 | Page title (1.625rem on phones) |
| Figure | Bricolage, 1.5rem, tracking -0.03em | 600 | 1.15 | A view's headline amount |
| H2 | Bricolage, 1.1875rem (19px), tracking -0.02em | 600 | 1.25 | A section's heading ("For today") |
| H3 | Bricolage, 1rem | 600 | 1.35 | Sub-heading |
| Body | Newsreader, 1rem (16px) | 400 | 1.5 | Default copy and Prime's prose (1.0625rem in chat) |
| Row title | Newsreader, 1rem | 400 | 1.35 | The first line of a row (500 if it needs to stand out) |
| Caption | Newsreader, 0.8125rem to 0.875rem | 400 | 1.4 | A row's muted sub-line, hints and metadata |
| Label | Bricolage, 0.8125rem (13px) | 500 | 1.3 | Small labels: a view's tag, a date line ("Sunday, 22 November"), column heads. Sentence case, no tracking |
| Data | Bricolage, 1.0625rem, tabular lining | 500 | 1.3 | A row's amount (the Home row amounts are 1.0625rem; a ledger row's 1.0625rem) |
| UI | Bricolage, 0.875rem to 0.9375rem at small `opsz` | 500/600 | 1.2 | Buttons, tabs, chips, inputs (inputs 16px on a phone) |

### Font Stack

- Display and UI (`--font-ui`, new): "Bricolage Grotesque", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif. Set `font-optical-sizing: auto` so `opsz` follows the size; force `font-variation-settings: "opsz" 96` only on the headline.
- Body (`--font-body`, new): "Newsreader", Georgia, "Times New Roman", serif.
- Mono (`--font-mono`, new): ui-monospace, SFMono-Regular, Menlo, monospace, only for an error's technical detail and identifiers a person may copy. Money is never mono.
- No coloured accent word and no italic accent word in a title: a title is one weight, one colour. `.accent-serif` and `--title-accent` are removed in the component and token PRs. Newsreader italic is allowed for one thing only: quoting what someone said or wrote ("how much leeway do i have this month?" echoed back, a note a person wrote, a merchant's own message). It is never emphasis, never a title and never coloured.

### Loading the fonts

Self-hosted, no runtime Google Fonts request. Two woff2 variable files per face family are enough (`BricolageGrotesque[opsz,wdth,wght]` trimmed to Latin; `Newsreader[opsz,wght]` and its italic, Latin), put in `web/public/fonts/` (or taken from the `@fontsource-variable/bricolage-grotesque` and `@fontsource-variable/newsreader` packages, whichever the token PR finds smaller to bundle) and declared with `@font-face` (`font-display: swap`, `unicode-range` for Latin) in `styles.css`; preload the Bricolage file in `index.html`. Fallback metrics (`size-adjust`) are set so the swap does not move the headline.

**CSP: needs a change.** `src/nexus/channels/web/frontend.py` sets `font-src https://fonts.gstatic.com` and, because `font-src` is given, it overrides `default-src 'self'`, so self-hosted fonts would be blocked. The token PR must change it to `font-src 'self'` (and may drop `https://fonts.gstatic.com`, and `https://fonts.googleapis.com` from `style-src`, if nothing else uses them). A font small enough for Vite to inline as a `data:` URI would also be blocked, so keep them as files (set `build.assetsInlineLimit` below the files' size, or keep them in `public/`).

### Rules

- Every amount uses Bricolage with `font-variant-numeric: tabular-nums lining-nums`, in rows, tables, the headline and chat: digits line up in a column, so a column of money can be read down.
- A figure is right-aligned in its row; the currency code follows it where needed (ISO, never a symbol), smaller and muted in a headline, plain in a row. Home's headline leaves the code to the sentence ("left for November") and the home currency.
- Prime's prose is Newsreader; the figures inside it are Bricolage (`<b class="fig">`). UI chrome is never Newsreader.
- 13px is the floor for any text, and the Label level is the only one that small. Body copy must remain readable at narrow widths; wrap long counterparties and notes.
- Sentence case everywhere, no uppercase labels, no letter-spaced capitals.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a 4px base unit.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Icon-to-label spacing |
| --space-2 | 8px | Tight control groups |
| --space-3 | 12px | Form field padding |
| --space-4 | 16px | A section's side padding |
| --space-5 | 20px | Comfortable grouping |
| --space-6 | 24px | Page side padding on a phone, headline block |
| --space-8 | 32px | Section separation on a wide screen |

### Grid

- Max content width: 1420px
- Primary shell: fixed rail plus one scroll-owning main viewport
- Wide dashboard: 2-column content grid with a 70/30 split
- Transaction ledger: one readable column at 375px; table details may scroll within a named table region
- Breakpoints: 720px mobile, 900px compact shell, 1024px stacked dashboard

### Rules

- `.main-viewport` owns application content scroll on desktop.
- The transaction table wrapper owns horizontal table scroll only when required by dense data.
- Mobile uses a fixed bottom navigation and bottom-sheet dialogs.
- Use intrinsic wrapping before adding a breakpoint.

## 5. Components

### Surfaces and radius

- **A section is a soft block, not a card.** It is `--bg-card` on the ground with a 14px radius on a phone (up to 22px for a large view on a wide screen), 4px 16px padding, 12px side margin from the screen edge, 8 to 12px between sections. Inside it: an optional heading row (H2 in Bricolage at the left, its action, such as See all, Open or Edit, as a text button at the right) and rows divided by `--border-card` hairlines, the last row without one. No border and no shadow around a section. Sections are never nested; a row is never a card. Sheets, dialogs and menus are the same surface with a `--border-edge` edge and `--shadow-modal` (radius 22px on a sheet's top corners, 14px on a menu; `--radius` 14px and `--radius-inner` 10px replace today's 20px and 12px). A control's radius is 12px; a text field on its own is a pill.
- **Shapes**: buttons are pills (radius half the height); the ask bar is a pill; chips are pills; the chat bubble has the 18px radius with a 4px corner at the tail. Status is never a pill, only a word in its colour. No glows, no gradients.
- Home has no hero panel: it opens on a date label, the month's headline figure and one sentence, all on the ground (see Home headline). The ask bar is pinned above the bottom bar, not inside the page flow.
- **Buttons**: pills, 44px tall (52px for a full-width primary at the foot of a form or a sheet; 38px only inside the ask bar, where it sits in a 50px field). The primary is a filled `--accent` pill with white text (UI, 600). The secondary is `--bg-raised` with ink text. A text button (the section actions, "Show all") is `--accent-text` with no fill. No outlines on buttons (chips have a `--border-edge` outline, see below), no gradients, no glow or shadow. Destructive is a text button in `--rose-accent`, never filled. In Travel the secondary is `.btn-soft`, which becomes a `--bg-raised` pill with ink text in the component PR (no pale fill); grey `--bg-raised` is also cancel and back.
- **Chips and filters** (All, Spent, Received, Pending; the Travel day pills): 34px tall (40px on touch) pills, UI at 0.875rem. Off: transparent with a `--border-edge` outline and ink text. On: `--text-strong` fill with `--bg-shell` text (15.1:1); a colour is never what says "on". A chip is the only filter control; Travel's `.day-pill` follows it.
- **Department tabs are the bottom bar** on a phone and the rail on a wide screen (below); inside a department, sub-tabs (Money has Overview, Ledger, Budgets, Cash flow; Investment three: Portfolio, Watchlist, Trade plans; Travel's one tab means no bar) are text in Bricolage on the ground, the current one ink and 600 with a 4px green dot under it, the rest `--text-muted`; keep a department to five tabs or fewer. Setup that is done once (Receipts by email, Import a statement) is not a tab: it lives in Settings under Connections, and the Ledger's More menu links to the import.
- Ink green is for what can be pressed or is the person's own (the primary button, links, text buttons, the focus ring, the selected pressable chart bar, the current tab's dot, the user's bubble) and for money in. Figures are ink; links in text keep the text's colour with a green underline (`--link-underline` at rest, `--accent-text` on hover).
- Fresh on return and pull to refresh: when the app comes back to the front (Telegram's `activated`, `visibilitychange`, `focus`, a restored `pageshow`; one return refreshes once) what is on screen is refetched: money data always, other data once stale, and everything after more than 5 minutes away. Home, the Money overview, the Ledger and Budgets can also be pulled down at the top of the page (the page follows the finger with a 28px green ring, letting go past 64px refreshes; "Refreshing…" and "Updated" are announced, and a "Refresh" button shows for keyboards while focused). The pull works because the Mini App has turned off swipe-to-close; in a Telegram without that call it stays off.
- In Telegram the app behaves natively: Telegram's back button on a page inside a section (a trip, a stock, a plan, a page inside Settings), a light haptic tap on the main button and a tick when changing tab or day, Telegram's header, background and bottom bar in the ground colour (all in Telegram's own light or dark theme), and no swipe-to-close while scrolling.
- **The bottom bar** (phone): on the ground with no rule and no shadow, four text labels, Today, Money, Invest, Trips (Home reads "Today" on the bar; the page is still Home), equal width, no icons and no middle button. A label is UI (0.8125rem), at least 44px tall and 44px wide; the current one is `--bar-text-active` (ink), weight 600, with a 4px `--bar-indicator` dot under it (the others keep the dot's space, transparent, so nothing shifts), the others `--bar-text`, so the current one reads without colour alone. A tab's accessible name keeps the full one where the label is shorter ("Invest (Investments)", "Trips (Travel)"); the set of tabs follows the apps the person has, and a fifth (Health, Home) arrives as an app does (five at most). The rail on a wide screen is the same: text names, the current one ink with the 4px dot at its left. Settings is a text link at the top of Home (and in the rail on a wide screen). The chat is reached from the pinned ask bar on every page, not just Home: the bar sits above the bottom bar on Home and on each app's main page, and an app's own add button stays beside it (decided in the component PR).
- No floating chat bubble. The only floating button is the labelled Add button (`.fab`: white text on `--accent`, a pill with a plus and "Add", 52px tall, no glow, at most `--shadow-drag`), 20px above the bottom bar on a phone (above the ask bar on Home, which has none), where it steps aside while the page scrolls down and comes back on the way up, and where it also steps aside while typing. A trip page always has it (and from 1024px has the trip header's Add beside Share instead); the Ledger shows it only once its header Add has scrolled out of view, named "Add a transaction" so it never doubles the header's "Add transaction", and there it stays put while scrolling down (`.fab-steady`), with room left under the list so it never covers the last row.
- An amount never breaks inside its figure: tile figures size to their box and wrap, if they must, between the currency and the number. Differences are said in words, not with a minus sign in green.
- Say a figure once per screen: Home's headline sentence gives this month's left to spend and the pace, so Money this month adds only what the sentence doesn't; the Money overview's Spending by month shows the trend and adds what the tiles around it don't (a usual month; the biggest category is "Where it went", beside it).
- Empty sections are one short line in Newsreader, left-aligned, with one action; a secondary way in (adding a holding by hand, recording a trade) stays behind a small button until asked for.
- Charts say one thing: past months are quiet bars (`--pal-track`), rose stripes only mark a month over budget, this month is a solid ink bar over the dashed outline of a usual month, the selected month's bar is outlined in green, and the legend lists only what's drawn.
- Ledger on a phone: no tick boxes until Select; dates are one select (All dates, This month, Last month, Custom) beside the search, with the date boxes on a row of their own only for Custom; each row names its category as a small caption under the merchant (the Category column is for wide screens).
- Touch targets: on touch screens buttons and chips are at least 40px tall (44px for primaries and tabs) and filter chips 38px.
- One heading style: Bricolage, sentence case, no emoji, no coloured word. Small labels are sentence case too.
- Page padding 40px 48px on desktop, 24px on the headline block and 12px beside sections on phones (a section's own padding is 16px).
- On phones a page's actions sit under its title and share the width (a primary action gets its own row); a section's note sits under its heading; form buttons fill the row.

### Views on the canvas

A **view** is what Prime puts on the spoken canvas (ADR 0002): a hand-built component that takes data. Every view has one shape, so any app can contribute one and Prime can stack them.

- **Structure**: a soft section, then, inside it, a small label (Label level, `--text-muted`, sentence case: "Money · this month", "Investments", "Trips") that names the app the view comes from, a Bricolage title (H2 or Figure, e.g. "Left for November" or "Where it went"), then rows. Right of the title, at most one text-button action. A view has no icon tile and no badge.
- **Rows** are the Rows pattern below. A figure-first view (a balance, a pace) puts its one big figure under the title in the Figure style, with the sentence in Newsreader beside it; a chart view has the chart in text too.
- **Prime composes, it does not style**: a view's colours, faces and spacing are the system's; Prime supplies data, order and at most a one-line sentence above the view in its own voice (Newsreader). Views stack with 8 to 12px between them, no wrapper around the stack.
- **Confirm cards** (ADR 0002 decision 8): anything that would change something (a log, a split, a settle-up, a delete, a trade plan) is shown first as a view with its effect in plain words and two pills: the primary, named for what it does ("Log 12.50", "Split evenly"), and a `--bg-raised` "Not now". The effect is the first line ("Record 12.50 as Food, paid with Citi PremierMiles ·· 4321. Nexus only records it."). A destructive one has a `--rose-accent` text button and asks for the typed word where the old UI did. It is one soft section, never a modal, and it stays in the conversation, greyed to a line with the outcome ("Logged 12.50") once answered. Nothing runs until the primary is pressed.
- **States**: every view has loading (rows as hairlines with a muted line), empty (one Newsreader line) and error (a rose line with Try again) states, so Prime can always place one.

### Home headline

- **Structure**: a Label with the date ("Sunday, 22 November"), muted, with a text link "Settings" and, when there is something to read, a bell at its right (both 44px high); the headline figure, 1,842.60 in the Headline style (`--text-strong`; `--rose-accent` when the month is over budget); then one sentence in Body (16px, `--text-secondary`): "left for November. That's about **230** a day for the next 8 days, and 1,364.70 less spent than by this time in October." (figures in Bricolage inside it). Everything sits on the ground: no panel, no gradient, no round buttons.
- **Rules**: the headline counts up the first time it is seen, and keeps its format. "About 230 a day" is left divided by the days remaining, rounded in the home currency's units; the clause is left out when there is no overall budget, when the month is over (the sentence then says "over for November by 214.00") or on the last day. The comparison clause ("less spent than by this time last month") appears only when last month's figure is known, and says "more" or "less" in words. With no budget the headline is the month's spending and the sentence says "spent in November" and the comparison. A progress bar is not on Home: the sentence says it. The headline is never narrated ("You're doing great"); it is only figures and the words that say what they are. The progress bar of the Money overview, where it appears, is 4px, ink on `--pal-wash`, a `role="progressbar"` named "Spent 1,357.40 of 3,200.00".
- **Content**: the brief paragraph is not on Home. What it said is a row in For today: a market row (the held stock that moved most in the latest US session, when it moved by 3% or more: "NVDA fell past your stop", sub-line "You set 182.40"), the trip row ("Check in at Hotel Sakura", "Kyoto, from 3 pm"), and each thing that needs the person. Rows are written in code from the user's own figures (`brief.ts` is reworked to produce them), never a model's words, and none says how many things there are.

### Today (Home)

- **Order on a phone**: the headline block, the trip view while a trip is on, For today, Working on (only while research runs), Get set up (only while unfinished), then Money this month, Portfolio today and Next trip; the ask bar is pinned above the bottom bar throughout. From 1024px two columns (3 to 2): the headline block and For today on the left, the three views at a glance on the right, and the trip view across the top of both
- **For today**: a soft section ("For today", with "See all 8" as a text button at the right when there are more than five; the page keeps its first five) of rows: the title in Newsreader, one muted sub-line naming the thing, and at the right a figure (Bricolage, ink) or a plain word ("Look", "Today", "File", "Pay"; "Look" and the like are text buttons in `--accent-text`, or `--status-warning` when it needs the person now). No icon tile. The API sorts by `when`; "See all (n)" (`aria-expanded`; "Show fewer" once open) opens the rest in place. An item that needs the person now (`when: "now"`) has its word in `--status-warning` at the right; an item about today says "Today" in `--text-muted` in place of a figure; the rest say neither. A row links to where it is settled, and a row that needs a decision has its word as the text button that settles it in place. With nothing: "Nothing for today." (not a sentence about the app)
- **Working on**: a soft section under For today, up to three runs, each a title, its progress line and a thin bar (ink on `--pal-wash`), with a Cancel text button while it runs
- **Ask bar**: pinned above the bottom bar (above the safe area), full width inside 12px of the screen edge: a pill 50px tall on `--bg-input` with a `--border-input` edge, a text field (16px, Bricolage UI) and a **Send** pill inside it (38px, filled `--accent`, white text; no sparkle or magic icon). The field's placeholder is an example of a real request ("Tell me what you spent, or ask"), never "Ask anything". Send on Enter. Sending opens the chat with the message. The suggested questions are not on the bar; they appear in an empty chat. A mic sits beside Send for voice (see Voice notes in the chat).
- **Get set up**: shown while the server's checklist is not dismissed and has a step left; it goes by itself when every step is done. A line says how many steps are left; each step is a row, ticked with "Done" when done, else an empty ring and a "Set up" text button to the page where it is done. "Get receipts in automatically" also has a quiet "Ask Nexus" button, since its sentence is a request for help; the other sentences (`ask`) carry example values (a payday, a stock, a budget) and are never sent as if they were the person's. "Hide" in the heading calls `POST /api/setup/dismiss` and the section goes; if that fails it says so under the list and stays
- **At a glance**: three views (each with one text button at the right). Money this month: spent (the figure the headline sentence also implies, as the view needs it), then with an overall budget the share used against the share of the month gone as two thin bars with the word "Ahead of pace" (in `--status-warning`), "On pace" or "Under pace" (more than 5 points apart), without one "Last month by now: SGD 1,200.00"; Details opens Money. Portfolio today: the value in the home currency, the day's change in `--emerald-accent` or `--rose-accent` and the `PriceWhen` caption (live dot, close); with no holdings "No holdings yet."; Open opens Investments. Next trip: "Tokyo in 12 days" (or "tomorrow") with its dates and any nights with no place to stay; with none "No trip coming up."
- **Trip mode**: while the next trip is on, a view ("Day 3 in Tokyo", Open trip at the right) leads above For today and Next trip gives way to it. It has up to three rows, each only when the trip's data has it: Next (the first plan today still to come, with its time; else one with no time; else "Nothing more planned today."), Spent today with what is left per day of the trip's budget, and Next booking (the next flight, train or stay after today). Nothing here asks the server for more than the trip page does
- **Left out of Home**: the six-month chart (now on the Money overview), the Budgets view (on the Budgets page) and the Today investment view (Investments)

### Spending by month (Money overview)

- Six bars: slate-grey for past months, striped rose over the overall budget, solid ink for this month so far over the dashed outline of a usual month; the budget as a dashed line
- Placed in the left column of the overview, under Where it went
- Two small tiles underneath: budget left (or money received) and a usual month; the biggest category is Where it went, beside it
- Every bar's month and amount is in text for screen readers; the legend names every mark

### Month picker (Money overview and Budgets)

- "‹ October 2026 ›" on the input surface (`.month-picker`, like the tabs): ghost chevron buttons labelled "Previous month" and "Next month" (disabled at the current month and 24 months back), the month between them as a live region; in the page head beside Log expense, on a row of its own on a phone
- The month is kept in the address (`?month=YYYY-MM`); this month has no parameter. A past month is titled "Looking back" with the month's spending and its comparison with the month before as the caption
- A past month hides what is forward-looking (budget left, left to spend, Latest, Who owes you, the nudge) and shows each budget against today's limits ("Against today's limits"), over in rose and warning in amber
- In the Spending by month chart each bar is a button ("October 2026: SGD 2,140.00", `aria-pressed`); the month shown is outlined in green, its label in green, and the legend says "Month shown"

### Rows

- Title and a muted sub-line on the left, a figure or a plain word right-aligned on the right (tabular, `--text-primary`; a word such as "Review" is a text button); rows divided by a 1px `--border-card` hairline, at least 56px tall, with no icon tile, no card and no badge
- Used for Today, holdings, the latest transactions and budgets

### Investment

- **Prices**: every price says when it is from, in one muted caption (13px, `.caption`) built by `priceWhen` in `format.ts` and shown with `PriceWhen`: "Live · 10:42pm" while the US market is open (with a 6px emerald dot, the only mark of live), "Close (provisional) · 4:00am" after the close until the official close arrives, and "Close of Fri 16 Oct" otherwise. Times are in the browser's timezone. The label sits in the Holdings card's heading row, under the price on the watchlist and stock page, and under the total on Home's Portfolio today card; a holding whose price is of another kind than the card's says so under its price. While a price is live and the page is in view, Portfolio, Watchlist, a stock and Home's Portfolio today card ask again every 60 seconds (`livePolling`) and on window focus; a close is not polled.
- **Today card**: how the portfolio did in the latest US session, at the top of Portfolio (a card under the heading); Home has no such card, only the day's change on Portfolio today. The title follows the session: "Today" while the market is open (with the `PriceWhen` label and its live dot), "Today's session" after the close, "Last session" before the next open. The change in the home currency and its percentage are the one big figure, green or rose as gains are everywhere else; under it up to three movers, each with the stock as a link, its move, its price and the day's newest headline as a quiet 13px line (a link out when it has a url), and a ghost "Why did it move?" button that reads the day's headlines and answers in place in 2 to 3 sentences with "From today's headlines" beneath ("Try again in a minute" after a 429, the server's short reason for a 404 or 422, else "Couldn't read that move just now"). It asks again every 60 seconds while live and in view, and is hidden when nothing is held or watched. It adds no primary action.
- **Stock page**: the Price card holds the price, then under it a quiet list of up to three facts against the levels ("1.2% below resistance at 131.00", "10.4% above its 50-day average (117.25)") in caption text, with no heading of their own. The page's one primary is Make a plan.
- **Plan page and Trade plans list** (the tab and list are called Trade plans, at `/investment/plans`; one plan is still "a plan", e.g. "NVDA plan"): under the title, a price line ("Price 182.40", then the muted `PriceWhen` caption: a live dot and "Live · 10:42pm", "Close (provisional) · 4:00am" or "Close of Fri 17 Oct"), left out for a plan made before prices were kept; then the usual "Closing price" line, and, quietly in caption text, "Refreshed from the plan of 7 Oct" (a link to that plan) when the plan replaced an older one. The verdict card carries the backend's price notes as amber callouts with a warning sign ("The price is already under the buy zone: …"). Under it, an open plan has a card with one switch, "Keep this plan fresh" (the same checkbox-in-a-label `toggle` as "Telegram alerts for this plan", 44px tall) and the caption "Nexus re-runs it when the price moves a lot, after earnings, or once a week."; it changes at once and is put back, with the server's words in red under it, if refused; a finished or refreshed plan has no such card. A refreshed plan shows a muted "Refreshed" badge where target, stopped and ran out show, and "A newer plan replaced this one" as a link under the title. In the Trade plans list an open plan with the switch on has a small green "Fresh" word beside its status, and a refreshed plan its "Refreshed" badge; refreshed plans stay in the list but not in the track record. There is no popup when a plan is made: the plan page, where the result is read, is where the switch is offered.
- **Settings**: three groups, each a small section title over a grid of cards. **Notifications**: Telegram updates (with quiet hours and the investment fields), a Time zone card (below), Shared trips and a Notifications card (an Open button; "What Nexus sent you on Telegram in the last 30 days, and what is waiting.") that opens `/settings/notifications`, one more page inside Settings. **Connections**: Receipts by email and Import a statement, each a card with an Open button (Receipts by email shows the connected addresses and how many emails wait, or "Not connected"); they open `/settings/email` and `/settings/import`, which are pages inside Settings: a quiet "Back to Settings" link above the title, no department tabs, and Settings stays marked in the rail. **Your data**: Categories, Wallets, Category rules, What Nexus remembers and a Download or delete card. The **Download or delete** card has two rows. Download all my data ("Your ledger, budgets, trips, investments, memories and settings, as a zip.") has a small Download button (`GET /api/me/export`, fetched as a blob and saved as `nexus-export-YYYYMMDD.zip`; "Preparing…" while it runs, then "Downloaded."; a 429 says to try again in a few minutes, in rose; inside Telegram's iOS and Android apps the line goes on with "If the download doesn't start, open Nexus in your browser to download it."). Delete everything (what goes, that shared trips stop being shared, that it can't be undone and a new invite is needed to come back) has a quiet rose "Delete everything…" that opens a confirm view in place (the confirm card pattern, no tint): a "Type DELETE to confirm" field (focused), a rose Delete everything that stays off until the field is exactly DELETE, and Cancel. Confirming (`POST /api/me/delete`) clears what the app holds and lands on the sign-in page; a refusal shows beneath in rose and stays put. The **Time zone** card is where Nexus counts your day: the current zone as "Madrid · UTC+2" (the city from the IANA name, the offset worked out in the browser), a caption under it for what put Nexus there ("from your phone", "you set it", "from your trip", "home") and "Home: Singapore" when home is a different zone. The phone's zone is reported once per page load after sign-in (`POST /api/me/timezone`, source `phone`), unless the person picked a zone themselves in the last 24 hours. Two small buttons: Change opens a picker (a search box over a list of every zone the browser knows, or a short common list) with Save and Cancel, which sends the zone as the person's own choice (source `manual`); Use home time, only while the zone isn't home, goes back to it. The result is said under the buttons ("Saved. Nexus now uses Tokyo time.") and a refusal shows beneath in rose. The investment fields sit in the Telegram updates card under their own "Investments" heading and each saves alone with only the field that changed: Quiet hours (two time inputs, From and To, default 23:00 to 08:00; "Nexus holds messages in these hours. A broken stop on a stock you hold still comes through."), Messages a day under it (a number input, 3 to 20, default 6, saved when the field is left or on Enter; a value outside the range or a fraction shows "Enter a whole number from 3 to 20" and sends nothing; "After this many (3 to 20), the rest go into your digest. Urgent messages, ones with buttons and your summaries don't count; they still come."), Big move alerts (a number input, 1 to 20%, saved when the field is left or on Enter; the server's refusal shows beneath and the saved value stays) and a Morning investment summary switch ("At 8am after each US trading day."). Captions are 13px, in sentence case.
- **Voice notes in the chat** (`components/ChatDrawer.tsx`, `useVoiceRecorder.ts`; `POST /api/chat/voice`, multipart field `audio`): the message row's button is the mic (a green icon button, 72px wide like Send, "Record a voice note") while the box is empty and Send once there is text. Tapping it asks for the microphone and records (MediaRecorder: webm/opus, else ogg/opus, else mp4, filed as `voice.webm`/`.ogg`/`.m4a`); the box is disabled and a line above the row shows a pulsing rose dot, "Recording" and the time as `0:07 / 2:00`; the mic turns into "Stop and send" (a stop icon) with a ghost "Cancel recording" (x) beside it. It stops and sends by itself at 2:00 and every track is stopped afterwards. While it uploads the person's bubble reads "🎙 Voice note…", then the reply list shows exactly as a typed message's (buttons, Undo). A refusal (413 too long, 415, 429, 503) removes that bubble and says the server's words in a quiet rose line above the row. With no microphone API or MediaRecorder, or permission refused, the mic stays but dimmed (`aria-disabled`) and a tap shows, once, the muted line "Mic isn't available here — send a voice note in the Telegram chat instead."
- **How Nexus talks card** (Settings, in the Notifications group, across the grid's full width; `GET`/`PUT /api/settings/voice`): the title, then "Pick a vibe, then fine-tune. Only changes wording — never what Nexus can do." Five vibe buttons (Default first; a label and a one-line blurb; the chosen one with a green edge, `aria-pressed`; two across on a phone), three segmented dials (Emoji None/Some/Lots, Length Short/Normal/Detailed, Humour Off/Light/Playful; a white thumb on the input surface, 40px tall) and an "Anything else?" field (200 characters, a counter under it with "Your note applies in chat", saved when left or on Enter; an empty field clears it). Every tap saves at once: the screen changes first and is put back, with a rose line under the card, if the server refuses. Choosing a vibe takes that vibe's own dials. Under it a Preview of three made-up exchanges ("grab 12", "rent paid", "how's my food budget?") written in the browser (`voice.ts`) from the vibe and dials, so it follows each tap with no request: Emoji none strips them, some keeps one, lots adds more; Short drops the second clause and Detailed adds one; Humour off drops a vibe's joke and Playful adds a quip. The note is not previewed. The segmented buttons and vibe buttons give a selection tick in Telegram.
- **Notifications page** (`/settings/notifications`, from the bell on Home or the Notifications card in Settings; inside Settings like Receipts by email: a quiet "Back to Settings" link above the title, no department tabs, Settings marked in the rail, Telegram's back button to Settings): the title "Notifications" with one caption, "Urgent ones always come. The rest respect your quiet hours and daily limit, and what's left is gathered into one message." Under it the last 30 days (`GET /api/notifications/history`), a block per day in the user's timezone, newest first and titled Today, Yesterday, then "Tue, Oct 20" (with the year once it isn't this one). A day's card is rows (the usual icon tile (no tile in Paper), the message, a caption line under it): the tile is a bell, or the alert icon in an amber tile for an urgent message, which also says "Urgent" in amber caption text; the message is up to two lines of its own words (folded, it runs on as one paragraph so the clamp's single "…" never follows a full stop at a line break; opened, the line breaks are kept) with a small "Show more" / "Show less" button (`aria-expanded`) when there is more, and is a link to its `link` when it has one; the caption line holds the time and a status word: "Sent" (green), "Held until 8:00am" (amber; "tomorrow 8:00am" or a date when it isn't today; "Held for the next digest" with no time), "In a digest" (green) and "Not sent — Telegram not linked" (quiet grey), which wraps rather than spilling on a narrow phone. With nothing: "Nothing sent in the last 30 days."
- **Model costs page** (`/settings/costs`, owner only: a Model costs card with an Open button sits last under Your data for the owner and for no one else, and the page says "Model costs aren't available." to anyone else, as does a 404 from `GET /api/ops/costs?days=`; inside Settings like the Notifications page): the title, one caption and a 7 / 30 / 90 days segmented control (the usual `.tabs`, `aria-pressed`, 30 by default; it refetches and keeps the old figures up meanwhile). Three tiles: This month so far (with "Day 28 of 31"), Projected for the month, Per active user per month. Then blocks titled Last N days (a bar per day, oldest first, zero days a hairline; hovering, focusing or tapping a bar names its day, cost and calls on the line above, the latest day until then; first and last date under it), By feature (friendly label, cost, a share meter and "61% · 900 calls"; an unknown key is shown as it is), By user and By model (name, cost, then calls, and tokens in and out for a model). Money is US dollars: cents ("US$0.41"), four decimals under a cent ("US$0.0042"). It ends with a caption: "Exact costs reported by OpenRouter. Search and Maps APIs are billed separately and aren't included."

### Chat

- **Prime's answer**: prose first (Newsreader, 1.0625rem, `--text-secondary`, no bubble, no avatar tile, full width of the column, figures inside it in Bricolage), short: one or two sentences that say the thing ("You have about 702.62 of room. Spend more than that on everyday things and November ends below zero."). Then, when there are figures, a view (a soft section) with rows: labels left in `--text-muted`, figures right-aligned, Bricolage, tabular, the last row ("Room left") ink and 600; and under it, if needed, one caption in Newsreader ("This counts rent on the 1st, Netflix and the SP bill. It doesn't guess your everyday spending."). No sparkle or magic icon anywhere on the assistant. Reply buttons are text buttons or outline chips.
- **User**: a green bubble (`--accent`, white text 8.1:1 light and 5.2:1 dark, Bricolage UI at 0.9375rem, since it is the person's own words in a control-like shape), right-aligned, at most 78% wide, 18px radius with a 4px bottom-right corner, 10px 16px padding. The bubble is the one place the accent fills a non-button. A quoted echo of what someone said inside Prime's prose is Newsreader italic.
- **Chrome**: the chat is a sheet over the page (a panel from 1024px), with a header (a "Done" text button at the left, "Nexus" centred, 600) and the ask field at the bottom in the same style as Home's ask bar with a **Send** pill; an empty chat offers four suggested questions as outline chips (36px, `--border-edge`) or plain text rows (see Chat suggestions) with no "Ask anything" line above them.

### Transaction ledger

- **Structure**: heading (Display, "Money") with a compact primary "Add" pill (named "Add transaction") and a "More" menu button beside it, then a row of chips (All, Spent, Received, Pending: the current one filled ink, the rest outlined; no tray) and a search field (a 42px pill on `--bg-card`) with a Dates select; then the rows. Transfers sit under All with the word "Transfer". Import statement and Export CSV are in More. The Add button stays because the Ledger has no other way to add; Home and the Money overview have their own.
- **Rows**: merchant or source in Newsreader with a muted sub-line (category and the card that paid), the figure right-aligned in Bricolage and tabular, signed ("-12.50" out in ink, "+3,200.00" in in `--emerald-accent`); there is no Type column or badge. Pending, Transfer and Deleted are a word in the muted sub-line, "Pending" in `--status-warning`. On wide screens the rows are columns of the same (select, merchant, category, amount), under a Label header row, inside one soft section.
- **Dates**: the list comes newest first and is grouped by day on every width: a heading row (a real `h3` in the user's timezone: Today, Yesterday, then "Mon 9 Nov", with the year for another year) with the day's total right-aligned and tabular on the same line, then that day's rows, which do not repeat the date. A group is separated from the one before by space, not a card.
- **More menu** (`components/Menu.tsx`): a button with `aria-haspopup="menu"` and `aria-expanded`; the list is `role="menu"` with links or buttons as `menuitem`s, 44px tall, under the button on its right edge. Opening focuses the first item; Arrow keys, Home and End move; Escape closes and returns focus to the button; Tab, a pick or a press outside closes it.
- **Variants**: all, outgoing, incoming, IOU/pending
- **Spacing**: `--space-4` card padding, `--space-2` control gaps
- **States**: loading, empty, filtered-empty, error, populated, selected
- **Accessibility**: semantic table on wide screens, labelled controls (the Dates select is labelled "Dates"), visible focus, keyboard-reachable rows and actions; the Category column is hidden on phones, so its caption under the merchant carries the category there
- **Motion**: 200ms opacity/transform panel entry; no layout animation
- **Layout**: fixed-sidenav-shell; main viewport owns vertical scroll, table wrapper owns dense table overflow

### Transaction entry sheet

- **Structure**: title, direction switcher, amount/currency, counterparty, type, date, notes, actions
- **Variants**: money out, money in, edit
- **Spacing**: `--space-3` field padding, `--space-4` field groups
- **States**: default, focus, disabled, submitting, success, error
- **Accessibility**: explicit labels, first-field focus, Escape/backdrop close, error text associated with the form
- **Motion**: 280ms bottom-sheet entry on mobile and opacity/transform entry on desktop
- **Layout**: bottom-sheet on mobile, centered modal on desktop; dialog owns internal scroll

### Paid with and card details

- **What it is**: which wallet paid for an expense, groundwork for tracking miles and cashback per card. Only money out has one; money in and moves never do. Investment and savings wallets are never offered (`payingWallets` in `wallets.ts`: cards, then the Main account, Cash, Other wallets).
- **Cards**: a wallet of kind Card has Bank, Card (the product), Network (Visa, Mastercard, American Express, Other) and Last 4 digits. A card is written "Citi PremierMiles ·· 4321" everywhere (`walletLabel`); without digits it is just its name. Last 4 digits is a numeric input (`inputMode="numeric"`, no `maxLength`, which would keep the first four of a paste): whatever is typed or pasted is cut to its digits and then to the last four, with "Only the last 4 digits are kept." beneath when digits were dropped. Full card numbers are never sent or kept.
- **Cash and Main account**: every user has one Cash wallet; like the Main account it can be renamed but not deleted or given another kind. Neither counts as "somewhere money was saved", so Cash alone does not bring back the Saved tile.
- **Settings, Wallets card**: a "Usual card" select (None, then the wallets that can pay; "Used when you don't say which card") and a "Paid with" group with the month picker (`MonthPicker`, kept in the card, this month to start) listing each paying wallet with "SGD 1,240.00 this month · 38 purchases" ("in October 2026" for another month) and a small "See in ledger" link to `/accounting/ledger?paid_with=<id>`. The usual card wears a "Usual card" chip in the Manage list, where a card's bank, product and network sit under its name.
- **Entry sheet**: a "Paid with" select under Category for money out only, listing the same wallets with "Not set" last. A new entry starts on the usual card; an old one on what it was paid with. Nothing is sent for a choice nobody made (the server then applies the usual card); picking changes sends `paid_with_wallet_id`, and Not set sends `null`.
- **Ledger**: the card is a caption under the merchant on every width ("Citi PremierMiles ·· 4321", "Cash"). A "Paid with" select beside the Dates select (a row of its own on a phone) lists "Paid with: any", the wallets that can pay and "Not set"; the choice is kept in the address as `?paid_with=<wallet id>|none`, shows as a removable chip like the category one, and goes into Export CSV with the other filters.

### Settlement control

- **Structure**: participant name, amount due, status, settlement action
- **Variants**: pending, partially paid, paid, unavailable
- **Spacing**: `--space-2` internal row spacing
- **States**: pending, submitting, success, error, disabled
- **Accessibility**: action names include participant and amount; status is text, not color alone
- **Motion**: action-swap from pending to paid; reduced motion falls back to an immediate label change
- **Layout**: stack inside transaction detail and compact row on the ledger

### Status badge

- **Structure**: a word in the status colour (`--emerald-accent`, `--status-warning`, `--rose-accent`) or muted text, set inline in a row's sub-line or beside a figure; never a pill, fill or border
- **Variants**: outgoing, incoming, pending, paid, completed, error, now (the amber word "Now" on a Today row that needs the person now)
- **Spacing**: `--space-1` vertical and `--space-2` horizontal padding
- **States**: default, focus when interactive
- **Accessibility**: text always names the state; contrast target is WCAG 2.2 AA
- **Motion**: none unless status changes, then opacity crossfade
- **Layout**: inline cluster item

### Trip page
- **Structure**: on Plan, a cover (a photo with only light round buttons on it: a Trips back pill, Share, the Add button from 1024px and a ⋯ menu, and the photo credit behind a round info button), and under the photo, on white, the destination in ink, a meta row with dates, a when-pill and companion initials, the Next up line and, on a shared trip, the latest change. On the other tabs, and on Plan once the photo has scrolled behind it, the cover is replaced by a slim sticky bar: a back arrow, a 36px thumbnail of the photo, the destination (the page's h1 there) with its dates, then the same actions. Under it a segmented tab bar, Plan, Ideas, Money and Prep (the open tab is in the address as `?tab=`, and the open day as `?day=`), which sticks under the slim bar, or to the top while the cover is showing; the tab's content; the Add button. The ⋯ menu holds Edit trip, Getting around and directions, the photo choices (Another photo, No photo or Show a photo) and Delete trip
- **Variants**: Plan (a stops row, each stop with its dates and nights and a travel marker between stops, with Edit stops beside it; the day pills and the day carousel in one card, a day at a time, swiped or picked, each day as tall as its plans, the pills one scrolling row on a phone (a fade at an edge with more days beyond it) and wrapped onto as many lines as they need from 1024px; a rail dot, the day's heading ("Today · Day 3 of 6 · Fri, Oct 23" on today), its weather on one line, the night's stay as a compact strip (hotel name, Maps and Copy address, with address, check-out and booking reference under a fold) and the day's plans, flights and trains, travel times between them, a name for the day and plans moved by their grip or onto a day pill; a tap on a plan, flight, train or stay opens it in place (address with Maps and Copy, Google Maps, link, note, booking reference and a quiet Change that opens the editor) and a second tap folds it, while a press that moves more than 8px or lands as the days scroll does nothing, so a swipe never opens an editor; the map beside it from 1024px when the trip has one (with no map the day takes the whole width), stuck in view while the day scrolls, and full screen on a phone when asked, showing one day or all, with an Ask Nexus about this trip button underneath; while the trip is on, Plan opens on today; the day is shown once, with no separate card above it), Ideas (saved places without a day as quiet rows: a name, one meta line, a cost when there is one and one action, Add to day or the day it is on; a row opens to its note, Google Maps link, rating, Change and Remove; the lists as chips once there are two, an Arrange button that shows the drag grips only while it is on, a List and Map switch where maps are set up, and the map beside the list from 1024px; a Find ideas button above them opens the finder in a sheet), Money (the page's full width; one summary card of what is spent, booked and planned against the budget, a To do card for costs to split and people to settle with, then Details, a list of sections of which one is open at a time: Where it goes, Planned costs, Setting money aside, Bookings paid, Expenses, Paid by others, Travellers; once the trip is over To do comes first, then what it cost), Prep (the same width; Getting ready, one list of what's still to sort, what Nexus suggests and the to-dos, then Cover and documents, the packing list as checkbox rows, the weather for the trip and the notes)
- **Add sheet**: the Add button opens "Add to <place>" with a booking, a plan or an idea, and quick ways: Type it, Screenshot or photo, Find a place. Money has its own forms (a planned cost, someone else paid) instead of the sheet. On Prep the button is "Add to prep" and opens a small choice sheet of A to-do, Cover or a document and Something to pack; each takes you to its field or, for cover, to its own sheet
- **Getting around and directions**: the owner's ⋯ menu item, on a trip with maps, opens a small sheet with Getting around (Public transport or Hire car, for hops with no mode picked) and the app directions open in, which is remembered on the device. A member sees no picker, only a quiet line under the map: "Getting around: public transport"
- **Share sheet**: Share in the header opens "Share the plan", with People above the Read-only link
  - People lists everyone on the trip, the owner first, each with "You", "Owner" or "Member" under the name. The owner's Invite someone (soft) makes a single-use link, shown once in a field with Copy and the note "Works once, for 7 days."; links not yet used are listed with the dates they were made and expire, and Cancel. Remove beside a member is a quiet rose button and asks first
  - A member sees the same list, titled "People on this trip" (the header button says People), with no Invite, no Remove and no read-only link, and a quiet rose Leave trip that asks first; leaving goes back to Trips
  - Read-only link makes a link to the days, plans and ideas, never money, references, notes or who's going; a switch shows bookings, and Create a link, then Copy, is the sheet's one primary, and the link can also be renewed or stopped
- **Member view**: a trip someone else owns shows their name under the title ("Shared by Alex T."), the faces in the meta row are the people on the trip, owner first, and the tabs are Plan, Ideas and Prep. There is no Money tab (its address opens Plan), no ⋯ menu (so no photo choices or Getting around picker), no cost or currency field in the add forms, and nothing about a budget; Share becomes People. On Prep a member reads and adds to-dos, cover and documents but sees no cost on a cover and no Log it, and the cover sheet has no cost or currency field. A member who is no longer on the trip sees "You're no longer on this trip." with a button to their trips
- **Activity**: a trip with other people on it shows its latest change under Next up in the cover's text, on Plan only, in one quiet line ("Alex T. added Dinner at Sushi Ten · 5 min ago"), only when the change is from the last 7 days. Tapping it opens the Recent changes sheet, the last 20 changes, newest first, each with how long ago. Nothing shows on a trip nobody else is on
- **Place photos**: a linked Google Maps place shows its photo, 240px wide with a credit line under it, in the place's Details on a stop. A 64px thumbnail with its credit (`PlaceThumb`) exists but no page shows it yet; its credit wraps to six lines at that width, so shorten the credit before using it
- **Cover**: the destination photo on its own, 190px tall on a phone (full width) and 240px on a wide screen (a card with the page's radius), with no fade or text over it; the title and details sit below it on white. With no photo it is a gradient from the destination's name, 120px tall. Buttons on the photo are light glass (white at 94%, dark text, a soft shadow) so they read on any photo; the photo credit shows from the round info button and links to the photo's Commons page. Once the photo has scrolled behind the 56px slim bar, the slim bar takes over and the cover's buttons are hidden and inert
- **Next up**: one quiet line of text in the cover's text on Plan only, one ghost text button (the action, in accent text) at its right, 44px tall on touch; it is not on the other tabs, and once the trip is over it says who still owes
- **Spacing**: `--space-4` card padding and between cards, `--space-2` timeline gaps
- **States**: loading, error, empty sections ("None yet", "No ideas yet", "Free day"), imported from a screenshot (a banner asking whether it looks right), adding, editing; after the trip there is no Add button, Money opens first and Next up (on Plan) is about settling up
- **Accessibility**: the tabs are a labelled navigation with `aria-current`; Next up is one labelled region with one button; the cover's buttons are hidden from assistive tech while the slim bar stands in, and the page has one h1 (the cover's title, or the slim bar's); the day pills are buttons with `aria-current`, and each day is a labelled slide; the day rail is decorative; the Add button is named for what it adds ("Add to Day 2"); the info button and every icon-only button have names; sheets are `role="dialog"` and close on Escape or the backdrop; weather icons carry a text label
- **Motion**: chips and buttons change colour at Micro timing; the slim bar fades in over 160ms (none for reduced motion), the Add button fades down out of the way while a phone scrolls down, and its press scale is removed for reduced motion; the day carousel scrolls smoothly unless reduced motion is on
- **Layout**: from 1024px Plan and Ideas put the day or the list on the left (60%) and the map on the right (40%, at least 300px), and the map sticks below the slim bar and tab bar (112px) with a canvas of at most 600px, so it stays in view; on phones they stack. With no map (no Google Maps key) Plan and Ideas are one column, not two with an empty one. The cover, the tab bar and every tab's content share one content width (the page's 1420px at most), so no wide cover sits over a narrow body; Money and Prep use all of it. The slim bar (56px) and the tab bar (56px) stick to the top of the scroll area (`--trip-sticky-top`, 112px); the day pills stick under them on a phone, where they scroll sideways, and scroll away with the page from 1024px, where they wrap. Under 1024px a day's pencil sits right beside its name (not at the far right), so the floating Add button never covers it; tap targets stay 44px From 1024px the Add button sits in the header beside Share; below that it floats at the right of the screen, and on phones 20px above the bottom bar, with room under the last item so it covers nothing

### Travel home
- **Structure**: the heading "Your trips", one count line under it ("1 on now · 4 coming up", left out when there is nothing to count; a guest's reads "The trips you were invited to."), and one primary at the right, New trip with a plus
- **Trip card**: a photo on top (140px; a gradient from the destination's name without one), then on the ground the destination in ink (Bricolage) at 26px (the link; the whole card is clickable) beside a when-chip (pale blue today; a `--bg-raised` pill with ink text in Paper), one line of dates with days and nights, and the companions as small round initials at the right. A card on a trip the person was added to also says "Shared by <owner>" and shows no budget. Cards in a row are equally tall
- **Grid**: one column on a phone, two from 720px, three from 1280px, with `--space-4` between cards
- **Order**: On now, Coming up, Shared with you, Where to next, bookings not on a trip, Research, then Past trips, then the footer line. Groups with nothing in them are left out
- **Where to next**: not a card: a title, a place-and-when field with Research it (handed to the chat), and example chips with Add a trip in one row that scrolls sideways (hidden scrollbar). With no trips it is the whole page body under the heading (no separate empty card repeating it)
- **Past trips**: one button, "Past trips · 3" with a chevron, shut until pressed (`aria-expanded`); open, the trips are compact rows with a 56px desaturated thumbnail, the name (the link) and the dates, with no card
- **Footer**: one centred caption at the foot, "Each trip keeps its bookings, plans and money together. Nexus never books anything."; a guest does not get it
- **Research**: each researched place is listed under the trips, with its date; see Research page
- **States**: loading, error, and no trips: "Where to next?" and New trip are the ways to start (a guest with no trips is told to open an invite link)

### Shared trip page
`/shared/<token>`, the read-only link, signed out. A centred column of at most 760px (a card from 720px, a full-width band on a phone).

- **Cover**: the trip's photo (or gradient) with the credit button and a white glass chip, "Shared with you · read only"; under it the title in ink (36px, 48px from 720px) and one line of dates and stops ("Nov 10 – Nov 14 · Tokyo and Kyoto") with the when-chip
- **Days**: one card each: a meta line ("Day 2 · Wed, Nov 11"), the day's name in ink (its label, else the stop), then rows divided by hairlines. A plan's row is a 48px time column, the title with one quiet line (address, or the kind and address) and a ghost Maps link; a flight or a stay has its line icon in place of the time, and a stay a Check in or Check out badge. A day with nothing says "Free day"; with bookings hidden, a day a hidden booking falls on says "Travel day"
- **Bookings hidden**: a quiet note under the cover says "Bookings aren't shown on this link."
- **Foot**: "Times are local." and a centred caption saying that no money, booking references, notes or travellers are shown. No buttons: nothing on the page can be changed

### Research page
`/travel/research/<run>`: a back link to Trips, the place in ink (36px, 48px from 900px) with one line ("Jan 10 to Jan 17 · 7 nights · 2 travellers").

- **One primary**: Make it a trip. Once a trip is made it is replaced by a soft Open the trip
- **Estimated cost**: the first card, a label, the range large ("SGD 4,602–6,760"), "for 7 nights, 2 travellers", the budget line ("Fits your budget of SGD 6,800"), what makes it up, and the put-aside sentence with its cash-flow verdict
- **Then**: When to go, Costs (a row each: the label with its source number, per person or per day under it, the range at the right, wrapping under the label on a phone), Where to stay (a Save its ideas box per area, and the soft Add to a trip…) and Getting around
- **Sources**: one card at the foot that is shut, "Sources · 2" with a chevron (`aria-expanded`); open, it says other people's pages are not booked from and lists them, each with the day it was checked. Source numbers ([1]) are 13px or more

### Sheets
One overlay (`web/src/components/overlay/`) is the base of every sheet, dialog and panel, so a behaviour or a look is changed once. It has two shapes. The **sheet** is a centred dialog, and a bottom sheet at 720px and below; `Sheet` (`components/Sheet.tsx`) is its layer, with the header, body and footer, and it is the dialog for every Travel screen that is not a page (Add, Getting around and directions, the pin prompt, Recent changes, the day picker, Share, Stops, the finder, the cover form and the Add to prep choice) as well as the Ledger filters and the entry form (`as="form"`). The **panel** is the chat: a side panel, full screen at 480px and below, modal only there.

- **Gestures**: on a phone drag the grab bar or the title down to close; pull down from the top of a sheet's body (a pull that starts part-way down just scrolls); a quick flick closes it too. The chat is dragged by its header only, since a pull down in a chat reads older messages.
- **Keys and focus**: Escape closes the newest overlay or inline form first, then the one beneath it. Focus goes in on open, is trapped inside a modal overlay, and returns to the opener on close. The page behind is locked, so it does not scroll, even when the keyboard opens.
- **Structure**: a header (an optional back arrow, the title in 17px semibold, a 44px close X), a body that scrolls on its own, and an optional footer that stays in view. On a phone a short grab bar tops it.
- **Layout**: on phones (up to 720px) a bottom sheet, full width, at most 90% of the screen's height, with 20px top corners, sliding up over 280ms and clear of the bottom bar and the home indicator. From 721px a centred dialog 640px wide (at most the screen less 48px) and at most 85% of its height, fading in. The page behind is dimmed and does not scroll, even when the keyboard opens.
- **Behaviour**: it is `role="dialog"` and `aria-modal`, named by its title. Escape and a tap on the dimmed backdrop close it, as does the X; the back arrow (shown only where a sheet has two views, as Add does) steps back to the first view. Focus goes to the first field when it opens (not on a phone's Type it, so the keyboard stays down) or to the dialog itself, and returns to the button that opened it when it closes. A sheet never opens another sheet or dialog on top of itself: a choice that needs a second step happens inside it, as a view, a menu or a confirmation box.
- **Forms**: a sheet can be the form itself (`as="form"`), with its primary button in the footer. It has at most one primary button in view, and fields are 16px on a phone.

### Travel parts
These are the rules the Travel pages follow. New Travel screens keep to them. Colour and shape follow sections 2 and 8: where a line below still names pale blue, a blue primary, an icon tile or a sparkle (the soft button, the day pill's on state, the `.way` icon tile, the Next up and suggestion sparkles), the component PR replaces it with the Paper equivalent (a `--bg-raised` pill, an ink-filled chip for the on state, ink green for the primary, no tile, no sparkle). Cards named below (a day, a Money summary, Getting ready) become soft sections.

- **Buttons**: one filled green primary pill per view. A secondary button for a row or a card (Add to day, Find ideas, Open day) is `.btn-soft`: a `--bg-raised` pill with ink text (it is pale blue today). Quiet ghost buttons (`.btn-ghost`) carry a 16px icon and text, at least 40px tall. Plain grey `.btn` is only for cancel and back. Destructive is a quiet rose button (`btn btn-ghost btn-danger`: transparent, rose text), never filled. A ghost button's hover is the faint `--bg-card-hover`, never a grey fill. A ghost button that starts a line (See costs, Details, Take off, Make a new link) is pulled 12px left so its words line up with the text above it. Icon-only buttons (a packing item's remove) are at least 40px, 44px on touch.
- **One chip**: `.day-pill` is the only chip, for days, stops, lists, scopes and themes. It is a pill with a `--border-edge` outline; on is the ink-filled chip of the Chips rule (it is pale blue, `--accent-soft`, today). A stop's or list's colour shows only as a dot. 40px tall on touch. A choice with many options is one chip with a ▾ that opens the options, not a row of chips.
- **Icons, not emoji**: use the app's line icons (`Icon.tsx`). Weather icons carry a text label. Map markers use the letters F and T for flights and trains (and H for a stay) because Google's classic markers can't take SVG.
- **Rows**: an Ideas row is quiet: a coloured list dot, the name (a button that opens the row) over one meta line of address, kind and "Near Day 2 · 1.2 km", the cost at the right when there is one, then the row's one action as a 44px button. Rows are divided by a hairline and carry no card, badge or chip. What a row opens to (note, Open in Google Maps, rating and Details, Change and Remove) sits under it, indented to the name. Drag grips show only while Arrange is on, with a line saying how; a row's own button keeps working then.
- **Find ideas**: the Ideas tab has one Find ideas button (soft, with a search icon, 44px), beside the List and Map switch on a phone and on its own line from 1024px. It opens the finder in a Sheet titled "Find ideas": a search field with its Search button, then one scope chip, then the themes in one row that scrolls sideways, then the results. A result is a 56px tile (the place's photo, or an icon for its kind), the name, one meta line ("Rated 4.6 (2,310) · Jung-gu · Google Maps", or "From a guide" for an idea from an article, with the source linked) and one soft button, Save to Ideas (and Add to Day N when the search is near a day). A saved result turns into a disabled green "Saved" button and the sheet stays open, so several can be kept; closing it shows the ideas.
- **Scope chip and menu**: the finder's scope is one chip, "In Tokyo ▾" (its name is "Look in: In Tokyo"), that opens a menu of Whole trip, each stop and Near Day N, with a tick on the one in use. The menu is a popover under the chip (`role="menu"` of radio items), closed by Escape, a choice or a tap elsewhere; Escape closes the menu first and the sheet on the next press. It is the pattern for any choice with many options, in place of a row of chips.
- **Getting ready**: the first card on Prep, one list with hairlines between rows of 56px at least, in this order: what's still to sort (a warning icon, the text and one soft button, Add or Set, as Next up's), then Nexus's suggestions (the text over one quiet line, a soft Add and a ghost "Not needed" with an x; on a phone the two buttons sit on their own line under the text, in line with it), then the to-dos not done, then the done ones. The card's heading has "N to do" at the right; with nothing to do it says what is sorted. A to-do is a round 24px checkbox (accent when ticked) named by its text, an optional line under it ("By Tue 8 Dec", or "Overdue · Tue 8 Dec" in the warning colour and semibold once past and not done) and a quiet 40px (44px on touch) x that removes it. Ticking one sinks it to the bottom, muted and struck through. Under the list a hairline and the add form: a text field, a date field labelled "By (optional)" and a soft Add (disabled until there is text), with the note "With a date, Nexus reminds you the day before." Once the trip is over nothing is added, and the card is left out when there is nothing to show.
- **Cover and documents**: the card under it, for insurance, visas and other documents. Each is a 56px row: a line icon (a shield for insurance, a stamp for a visa, a page for the rest), the name over one quiet line ("Insurance · TX-4471 · 2–9 Dec"; the name is the button that opens the cover) and, for the owner when it has a cost, the cost at the right with a soft Log it under it, or "Logged" with a tick. Under the row, in line with the name, are quiet Call +65 6123 4567 (a `tel:` link) and Copy (the reference) buttons; Log it opens a confirm view in place, "Record SGD 89.00 as spent on Travel? Nexus only records it.", with a primary Log it and Not now (the same box on Money's Bookings paid). The card ends with a ghost "Add cover or a document" and, outside a guest's view, a caption that says it can be done by chat. A member sees no cost, Logged or Log it.
- **Cover sheet**: a `Sheet` form titled "Add cover or a document" or "Change <name>": a Kind chip row (Insurance, Visa, Document, Other: one radio group of `.day-pill`s), the name (labelled Insurer for insurance), Policy or reference, Emergency phone, From and To, for the owner Cost and Currency (home currency to start with), and Note. Its footer holds Save, the one primary, at the right and, when changing, a quiet rose Delete at the left, in line with the fields; Delete asks first in a confirm view that says an expense already logged stays. A member's has no cost fields.
- **Add to prep choice**: a `Sheet` titled "Add to prep" of three `.way` rows, each a 40px icon tile, the title and one caption: A to-do, Cover or a document and Something to pack.
- **To do**: the card on Money that holds what needs doing with the people going, and only appears when there is something: "N costs to split" (the total and the names, a soft Split button and See costs to list them with Split and Keep as just mine on each) and one row per person to settle with ("You owe Ann SGD 45.00" or "Ann owes you SGD 135.00", a soft Settle up button and Details for what makes it up). Splitting and settling confirm in place, in a confirm view under the row (a soft section, no tint), never a dialog: a sentence saying what will be recorded (and that Nexus doesn't move money), the choice where there is one ("Also record my share as spent"), one primary (Split evenly, Mark settled) and a ghost Not now. A line under the card's title says Nexus records what you say happened. The card is hidden when nobody else is going.
- **Details accordion**: Money's sections are rows in one card, each a button with its title at the left, a one-line summary at the right ("2 categories", "None yet", "You and Ann") and a chevron, 56px tall, divided by hairlines. One is open at a time (opening one closes the other, with `aria-expanded` on the button and the content a labelled region), and all start closed. Sections with nothing to show (Setting money aside once the trip has started, Bookings paid with no costs, Paid by others with no payments) are left out. A section's form (a planned cost, someone else paid) opens inside its section; the Add button opens the section it belongs to.
- **Money**: always the ISO code, through `formatMoney`, never a symbol. A range is "SGD 4,602–6,760". A foreign amount is followed by its home amount when known: "JPY 2,000 · SGD 18.00". A sentence that would show zero is left out.
- **Type**: 13px (0.8125rem) is the floor everywhere in Travel. Headings and labels are sentence case, with no all-caps. A trip's title is ink, one weight, like any title; the accent-coloured title (`.accent-serif`) is removed in the component PR.
- **Warmth**: it comes from the trip's own photos. Travel adds no colours and no accent word.
- **The Add button**: white on `--accent` (ink green), a pill with a plus and the word "Add", 52px tall, named for what it adds. Below 1024px it floats at the right; on phones it sits 20px above the bottom bar. From 1024px it moves to the trip's header, beside Share, and is the only Add on the page. Every tab has one except after the trip.
- **Trip invite page**: `/trip-invite/<token>` is a small centred card on the sign-in page's background. Signed out: "You've been invited to a trip" with "Sign in with Telegram to join." and the Telegram button (inside Telegram it signs in at once and the page only shows if that was refused, with a line saying the invite couldn't be used). Signed in: "Joining the trip…", then the trip opens with a short notice ("You've joined the trip to Kyoto."; their own link says "That's your own invite link. Send it to the person you want on the trip." and joins nothing; a trip they are already on opens with nothing said). A link that is used, cancelled, expired or unknown shows "This invite doesn't work any more" with "Ask the trip's owner for a new link." and one primary, Go to Home, or Go to Trips for a guest; any other failure shows "Couldn't join the trip", the reason and Try again
- **Guest app**: someone brought in by an invite with no account of their own sees Travel only: Trips (titled with "The trips you were invited to.") and the trips they are on. A slim header holds the app name, linking to Trips, and at the right their name and Sign out. There is no rail, no bottom bar and no chat, so no Ask Nexus, no New trip, no Where to next, no loose bookings or research and no Type it in the add sheet. Every other address goes back to Trips. With no trips yet: "You're not on any trips yet. Open an invite link to join one."
- **Sign-in page and the demo**: signed out, `/login` is a small centred card: "Nexus", one line ("An AI lifestyle manager you talk to, on Telegram and the web."), a primary **Try the live demo** link to `/demo`, then "Already using Nexus? Sign in with Telegram." and the Telegram button (an invite link keeps its own line and no demo button). `/demo` is the same card: "Setting up your demo…", then Home. It says "The demo is resting right now" with the Telegram button when demos are off, "Too many demos from this network — try again in a bit." on a 429, and "Couldn't set up the demo" with Try again on a network error. Someone already signed in goes straight to Home.
- **Demo banner**: while `me.demo` is set, a slim bar in a row of its own over the rail and the page, in `--bg-raised` with ink text: "Demo · made-up data · resets in 23 h · Sign in with Telegram to use your own" (the link signs the demo out and opens the sign-in page; under an hour it counts minutes). A × closes it for the browser session. The chat's header says "N messages left", and Settings leaves out Receipts by email and Shared trips; the rail leaves out Invite someone.
- **Chat suggestions**: an empty chat offers four plain text-row questions under its hint ("How's my dining budget?", "Plan Saturday in Kyoto", "I spent 12.50 on lunch at Kopi Corner", "What moved in my portfolio today?"); tapping one sends it, and they go once there is a conversation.
- **Sources under a web answer**: Nexus names the source in the reply's words ("per HardwareZone, 11 May") and the pages it used come as up to three small link chips under the text (`.src-chip`, from reply buttons whose data is `src:<https url>`; Telegram shows the same as inline URL buttons, two to a row). A chip is a pill on `--bg-card-hover` with a `--border-card` edge, 13px `--text-secondary` text, the site's name and a `↗` the screen reader skips (the link's name is the site alone); on hover the edge goes `--accent-border` and the text `--accent-text`. It is 32px tall with a 40px tap area around it, and it opens the page outside the app like other links. They are links, not actions, so they are never the big blue `url:` button, and one site shows once even if several of its pages were used. Reply buttons from before a reload are not kept, so the chips show on the live reply only.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 120ms | ease-out | Press and status changes |
| Standard | 220ms | ease-in-out | Tabs, filters, modal opacity |
| Emphasis | 280ms | cubic-bezier(0.16, 1, 0.3, 1) | Bottom-sheet entry |
| Reveal | 360ms | cubic-bezier(0.16, 1, 0.3, 1) | A card rising 10px into view, 35ms apart, up to 3 at once |
| Fill | 700–1200ms | cubic-bezier(0.16, 1, 0.3, 1) | Bars, meters and rings filling as their card arrives |
| Count | 650ms | ease-out cubic | A headline figure counting up from zero, the first time it's seen |

### Rules

- Animate only `transform` and `opacity` for movement.
- Every new interactive control has hover, active, focus, disabled, and loading behavior where applicable.
- Respect `prefers-reduced-motion: reduce` by removing movement and retaining state changes.
- **Reveal** (`motion.tsx`): cards, the brief and trip panels fade and rise into place the first time they're scrolled into view; their bars, meters and rings fill as they arrive. Figures that count up keep their format (currency, separators, decimals).
- On phones the bottom bar is fixed to the bottom edge above the safe area; nothing blurs, to keep scrolling smooth. The page's scroll area ends with padding of the bar's measured height (the shell keeps it in `--bar-h`, safe-area inset included; 68px plus the inset until measured) and 24px more, so the last line on any page scrolls clear of the bar.

## 7. Depth & Surface

### Strategy

Flat and soft. Structure comes from tinted sections and space, not elevation. Do not add a new shadow recipe to individual components.

- Sections: `--bg-card` on `--bg-shell` with a 14 to 22px radius and `--border-card` hairlines between rows. No border, no shadow.
- Sheets, dialogs and menus: `--bg-card` with a `--border-edge` edge and `--shadow-modal` (warm black at low opacity), over the `--overlay` dim.
- A dragged item uses `--shadow-drag`; a button on a photo uses `--shadow-thumb`. Nothing else has a shadow.
- Status colour (money green, attention rust, error red) is text or a thin mark, never a tinted background, and no shadow is coloured.
- The app frame, card, tab, bar and slim-bar shadows (`--shadow-frame`, `-card`, `-tab`, `-bar`, `-slim`) go in the token PR.

## 8. Patterns we don't use

These are the habits that make an interface look generated. Each one is out, with the reason. A review rejects them even when the contrast passes.

| Pattern | Why not |
|---------|---------|
| Gradient heroes or washes | A gradient behind the headline is decoration that competes with the figure. The figure on the ground, in ink, is clearer and has a known contrast |
| An italic or coloured accent word in titles ("Good *morning*") | It is ornament, it makes the colour ambiguous (green means you can press it), and it gives the title two voices. Newsreader italic is kept only for quoting what someone said or wrote, never for emphasis or a title |
| Sparkle or magic icons for the assistant | They say "AI" instead of saying what the button does. A labelled **Send** button does |
| Icons in pastel tiles | The tile adds a coloured box per row with no information. A row's title and sub-line say what it is |
| A card around every section, or cards inside cards | Boxes inside boxes lose the hierarchy and waste width on a phone. A soft section with hairline rows is one level; a view never nests another |
| Hard-bordered or shadowed cards | Paper separates by tint and space. Only a sheet, dialog, menu or photo has an edge or a shadow |
| Tinted pill badges for status | Colour on a tinted fill is hard to hold at 4.5:1 and makes every row a row of pills. Write the word in the status colour ("Pending", "Look") |
| Glow or coloured shadows | They are decoration that fails in dark and under Telegram's themes, and they suggest things are pressable when they are not |
| Neon colours (Lime, Digital Teal) | They fail as text on light and say "tech product", not "personal". Marks and text use the one accent and the status colours |
| Decorative emoji | They are not part of the type system, render differently per platform and read as filler. Use words, or the app's line icons where an icon carries meaning |
| Proportional or old-style digits in money | Columns of figures do not line up and a count-up jitters. Money is always `tabular-nums lining-nums` |
| Filler copy that narrates the UI ("8 things need you below", "Ask anything", "I've prepared a summary for you") | It tells the person what they can already see. Show the rows; label a control with what it does, write empty states as one plain fact ("Nothing for today."), and have Prime say the answer in a sentence |
| More than one accent colour | One green means "you can press this" or "this is yours". A second accent dilutes it. Status colours (rust, red) are for status, as text |
| Prime inventing interface | Prime composes the canvas from hand-built views (ADR 0002); it does not choose colours, faces or layout, or emit markup |

## 9. Accessibility Constraints & Accepted Debt

### Constraints

- WCAG 2.2 AA target.
- Body text contrast floor 4.5:1; large text and controls 3:1 minimum.
- Every action must be keyboard reachable and have a visible focus state.
- Direction and settlement state must be conveyed by text as well as color.
- Respect reduced motion and 200% text zoom without losing primary actions.

### Accepted Debt

| Item | Location | Why accepted | Owner / Exit |
|------|----------|--------------|--------------|
| None currently | — | The rebuilt cockpit (M4) replaced the legacy showcase and its query-string identity with authenticated sessions | — |

