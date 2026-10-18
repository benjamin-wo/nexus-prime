# Nexus Prime Design System

## 1. Atmosphere & Identity

Nexus Prime is a focused financial command center: light, cool, and quick to scan. Its
palette is True Summer: muted blues on an icy off-white page. Home opens on an indigo hero
(the month's one big figure and Nexus's brief, not in a card) that fades into the page;
every other segment is its own white card, its title above it. Indigo is the action
signal; emerald marks money in, amber attention or pending work, rose a budget gone over.
The bottom bar is deep slate with Nexus in its middle.

## 2. Color

### Palette

| Role | Token | Value | Usage |
|------|-------|-------|-------|
| Surface/primary | --bg-shell | #f1f4f8 | Page background (icy off-white) |
| Surface/secondary | --bg-frame | #ffffff | The rail, the chat panel |
| Surface/elevated | --bg-card | #ffffff | Cards, tables, sheets |
| Surface/interactive | --bg-card-hover | #f5f7fb | Hovered controls and rows; tiles inside a card |
| Input surface | --bg-input | #f3f6fa | Form controls |
| Text/primary | --text-primary | #1b2333 | Main content (deep slate) |
| Text/strong | --text-white | #0f1522 | Headings and emphasis (white on the hero and photos) |
| Text/secondary | --text-secondary | #4d5e80 | Supporting content (slate; 5.9:1 on the page) |
| Text/tertiary | --text-muted | #5f6b85 | Metadata and hints (4.9:1 on the page, 5.4:1 on cards) |
| Border/default | --border-card | #e1e7ef | Card and table boundaries |
| Border/subtle | --border-subtle | #e8edf3 | Rails and dividers |
| Accent | --accent | #3e52b6 | Primary actions (white text, 6.8:1) and money out |
| Accent/hover | --accent-hover | #34469d | Primary hover state |
| Accent/soft | --accent-soft | rgba(62,82,182,0.10) | Money-out surfaces, pills, the soft button, an "on" chip |
| Accent/border | --accent-border | rgba(62,82,182,0.30) | Focus rings, money-out control edge |
| Accent/text | --accent-text | #3e52b6 | Accent words on light surfaces (pills, the current month) |
| Accent/soft-hover | (none, in `.btn-soft:hover`) | rgba(62,82,182,0.16) | Soft secondary button on hover |
| Accent/glow-shadow | (none, in `.trip-fab-button`) | rgba(62,82,182,0.6) | Shadow under the trip's Add button |
| Scrim/info | (none, in `.photo-credit-button`) | rgba(27,35,51,0.45) | Round info button on a photo (0.65 on hover) |
| Scrim/credit | (none, in `.photo-credit`) | rgba(9,9,11,0.8) | The photo credit that the info button opens |
| Accent/glow | --accent-glow | #d8e7ed | Soft icy fills |
| Status/success | --emerald-accent | #047857 | Money in and completed states |
| Status/success-soft | --emerald-soft | rgba(5,150,105,0.12) | Money-in surfaces |
| Status/success-border | --emerald-border | rgba(5,150,105,0.35) | Money-in control edge |
| Status/warning | --status-warning | #b45309 | Pending and attention states |
| Status/warning-soft | --status-warning-soft | rgba(245,158,11,0.12) | Pending surfaces |
| Status/warning-border | --status-warning-border | rgba(217,119,6,0.35) | Pending control edge |
| Status/error | --rose-accent | #c0365c | Errors, deleting, a month over budget |
| Status/info | --cyan-accent | #4a93a3 | Informational accents, links to receipts |
| Surface/raised | --bg-raised | #e9eef5 | Secondary buttons, icon tiles inside cards |
| Chart/second | --sky-accent | #73b5d9 | A second chart series |
| Surface/glass | --bg-glass | #ffffff | Cards |
| Hero/top | --hero-top | #3e52b6 | Home hero, top (and Telegram's header on Home) |
| Hero/mid | --hero-mid | #6370c5 | Home hero before it fades into the page (white text 4.5:1) |
| Bar/background | --bar-bg | #1b2333 | The phone's bottom bar |
| Bar/text | --bar-text | #9ca8b8 | Bottom bar icons (white when active) |

The palette itself (True Summer), for charts and swatches: `--pal-slate` #4d5e80, `--pal-teal` #4a93a3, `--pal-sage` #6796a2, `--pal-sky` #73b5d9, `--pal-cornflower` #92b0d9, `--pal-iris` #6370c5, `--pal-mist` #bbcdde, `--pal-indigo` #3e52b6; accents `--pal-icy` #d8e7ed, `--pal-periwinkle` #9ca8b8, `--pal-dusty-pink` #e4d8da. Category swatches go indigo, sky, iris, teal, then mist for the rest; past months are mist.

### Rules

- One theme: icy off-white page, white cards, deep slate text, indigo for actions and the Home hero; do not introduce a second visual theme.
- Light text sits only on the hero (4.5–6.8:1) and on photos (under a dark fade).
- Accent colors communicate action or transaction direction, not decoration.
- New colors must be added here before they are used in CSS.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| Display | 2rem | 600 | 1.2 | Page title (1.75rem on phones) |
| Figure | 2.125rem | 600 | 1.1 | A card's headline amount |
| Brief | 1.5rem | 500 | 1.4 | The Nexus brief (1.25rem on phones) |
| H2 | 1.125rem | 600 | 1.3 | Card heading (the same on phones) |
| H3 | 1rem | 600 | 1.4 | Sub-heading |
| Body | 0.9375rem | 400 | 1.5 | Default copy |
| Caption | 0.8125rem | 500 | 1.4 | Metadata and labels; nothing smaller than this |
| Data | 0.9rem | 600 | 1.4 | Amounts and identifiers |

### Font Stack

- Primary: Geist, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif
- Mono: Geist Mono, monospace (small figures only; large amounts use Geist with tabular figures)
- Accent: Instrument Serif italic, one word at the end of a page title only ("Good *morning*", "This *month*"), never in body copy or figures

### Rules

- Use tabular figures for amounts and identifiers.
- Keep labels sentence case and concise.
- Body copy must remain readable at narrow widths; wrap long counterparties and notes.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a 4px base unit.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Icon-to-label spacing |
| --space-2 | 8px | Tight control groups |
| --space-3 | 12px | Form field padding |
| --space-4 | 16px | Standard card padding |
| --space-5 | 20px | Comfortable grouping |
| --space-6 | 24px | Major card padding |
| --space-8 | 32px | Section separation |

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

### Radius and surfaces (theme v2)

- Cards 20px (18px on phones), inner tiles and controls 12px, pills fully round. Every segment is its own white card with a soft shadow and room either side; where it helps scanning (Home, the Accounting overview) the title sits above the card, with its action (Details, Open, See all, Edit) on the right.
- Home's overview is not a card: a hero on solid indigo (full-bleed at the top on phones, fading into the page; a rounded panel on desktop) with the day and greeting, this month's spending as the one big figure with an arrow, how it stands in words, the brief, one-tap questions and the ask box, plus round buttons for Log expense and Settings.
- Buttons are filled: primary indigo with white text, secondary `--bg-raised`; no outlines. In Travel the secondary is the soft button (`.btn-soft`, pale indigo with indigo text) and grey `--bg-raised` is only for cancel and back; see Travel parts.
- Department tabs are a rounded segmented control on one row, sharing the width on phones; keep a department to five tabs or fewer (one-off tasks like Import are reached from the page that needs them).
- The accent is for actions (the main button, the active tab, today) and status, not decoration: figures in the brief are white and bold, links in text keep the text's colour with an underline, and a section's heading actions (Details, Open, See all, Edit) are all small buttons.
- In Telegram the app behaves natively: Telegram's back button on a page inside a section (a trip, a stock, a plan, Import), a light haptic tap on the main button and a tick when changing tab or day, Telegram's header in the hero's indigo on Home and the page colour elsewhere, its bottom bar deep slate like ours, and no swipe-to-close while scrolling.
- The phone's bottom bar is deep slate with rounded top corners: Home, Accounting, the indigo ✦ Nexus button in the middle (it opens the chat), Investment, Travel; icons only, names for screen readers. Settings is the cog at the top of Home (and in the rail on a wide screen, under the indigo Ask Nexus button).
- No floating chat bubble: Nexus lives in the bar. The only floating button is a trip page's labelled Add button (white on indigo, a plus and "Add"), 20px above the bottom bar on a phone, where it steps aside while the page scrolls down and comes back on the way up, and in the tab row from 1024px.
- An amount never breaks inside its figure: tile figures size to their box and wrap, if they must, between the currency and the number. Differences are said in words, not with a minus sign in green.
- Say a figure once per screen: Home's hero gives this month's spending and how it stands, so the Spending card shows the trend and adds what the hero doesn't (a usual month, the biggest category).
- Empty sections are one short line, left-aligned, with one action; a secondary way in (adding a holding by hand, recording a trade) stays behind a small button until asked for.
- Charts say one thing: past months are quiet mist bars, rose stripes only mark a month over budget, this month is solid indigo over the dashed iris outline of a usual month, and the legend lists only what's drawn.
- Ledger on a phone: no tick boxes until Select; dates are chips (All, This month, Last month, Custom), with the date boxes only for Custom.
- Touch targets: on touch screens small buttons and chips are at least 40px tall and filter tabs 38px.
- One heading style: sentence case, no emoji. Small capitals (eyebrow) are only for labels inside a section.
- Page padding 40px 48px on desktop, 16px on phones.
- On phones a page's actions sit under its title and share the width (a primary action gets its own row); a section's note sits under its heading; form buttons fill the row.

### Home hero

- **Structure**: the day and greeting with round Log expense and Settings buttons; this month's spending as the big figure (counting up) with an arrow (down when it's the better side); how it stands in words (budget left, or against last month by this date); the brief; one-tap question chips; the ask box
- **Content**: the brief is written in code from the user's own figures (`brief.ts`), never a model's words; figures in it are bold
- **Behaviour**: a chip or the ask box opens the chat with that question
- **Surface**: solid indigo from `--hero-top` to `--hero-mid`, fading into the page on phones; chips and the ask box are white on it
- **Layout**: chips wrap on phones; nothing scrolls sideways

### Spending by month (Home)

- Six bars: mist for past months, striped rose over the overall budget, solid indigo for this month so far over the dashed outline of a usual month; the budget as a dashed line
- Three small tiles underneath: budget left (or money received), a usual month, biggest category
- Every bar's month and amount is in text for screen readers; the legend names every mark

### Rows

- Icon tile (42px, `--bg-raised`), title and caption, value on the right; rows divided by `--border-card`
- Used for what needs you, holdings, the latest transactions and budgets

### Transaction ledger

- **Structure**: heading, direction filter, type filter, search, primary action, transaction table/list
- **Variants**: all, outgoing, incoming, IOU/pending
- **Spacing**: `--space-4` card padding, `--space-2` control gaps
- **States**: loading, empty, filtered-empty, error, populated, selected
- **Accessibility**: semantic table on wide screens, labelled controls, visible focus, keyboard-reachable rows and actions
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

### Settlement control

- **Structure**: participant name, amount due, status, settlement action
- **Variants**: pending, partially paid, paid, unavailable
- **Spacing**: `--space-2` internal row spacing
- **States**: pending, submitting, success, error, disabled
- **Accessibility**: action names include participant and amount; status is text, not color alone
- **Motion**: action-swap from pending to paid; reduced motion falls back to an immediate label change
- **Layout**: stack inside transaction detail and compact row on the ledger

### Status badge

- **Structure**: short text label with semantic color
- **Variants**: outgoing, incoming, pending, paid, completed, error
- **Spacing**: `--space-1` vertical and `--space-2` horizontal padding
- **States**: default, focus when interactive
- **Accessibility**: text always names the state; contrast target is WCAG 2.2 AA
- **Motion**: none unless status changes, then opacity crossfade
- **Layout**: inline cluster item

### Trip page
- **Structure**: a compact photo cover (Trips back link, Share, a ⋯ menu with Edit trip, the photo choices (Another photo, No photo or Show a photo) and Delete trip, the destination as the title, a meta row with dates, a when-pill and companion initials, and the photo credit behind a round info button); a Next up strip; sticky tabs Plan, Ideas, Money and Prep (the open tab is in the address as `?tab=`, and the open day as `?day=`); the tab's content; the Add button
- **Variants**: Plan (a stops row, each stop with its dates and nights and a travel marker between stops, with Edit stops beside it; the day pills and the day carousel in one card, a day at a time, swiped or picked; a rail dot and the day's stay, plans, flights and trains, travel times between them, a name for the day and plans moved by their grip or onto a day pill; the map beside it on wide screens and full screen on a phone when asked, showing one day or all, with an Ask Nexus about this trip button underneath; while the trip is on, today comes first), Ideas (saved places without a day in lists, filtered by list chips; Add to day, or the day it is on; a List and Map switch where maps are set up, and the map beside the list on wide screens; the finder to look for places in the whole trip, a stop or near a day, with theme chips), Money (spending against the budget, planned against actual, planned costs, setting money aside, travellers, split costs, costs others paid, settle up, expenses; settling up comes first once the trip is over), Prep (what's still to sort, the packing list, the weather for the trip, the notes)
- **Add sheet**: the Add button opens "Add to <place>" with a booking, a plan or an idea, and quick ways: Type it, Screenshot or photo, Find a place. Money and Prep have their own forms (a planned cost, someone else paid, a packing item) instead of the sheet
- **Share sheet**: Share on the cover makes a link to the days, plans and ideas, never money, references, notes or who's going; a switch shows bookings, and the link can be copied, renewed or stopped
- **Place photos**: a linked Google Maps place shows its photo, 240px wide with a credit line under it, in the place's Details on a stop. A 64px thumbnail with its credit (`PlaceThumb`) exists but no page shows it yet; its credit wraps to six lines at that width, so shorten the credit before using it
- **Cover**: the destination photo under a dark fade to the page background, or a gradient from the destination's name when there's no photo; text sits on the fade, never on bare photo; the photo credit shows from the round info button and links to the photo's Commons page
- **Spacing**: `--space-4` card padding and between cards, `--space-2` timeline gaps
- **States**: loading, error, empty sections ("None yet", "No ideas yet", "Free day"), imported from a screenshot (a banner asking whether it looks right), adding, editing; after the trip there is no Add button, Money opens first and Next up is about settling up
- **Accessibility**: the tabs are a labelled navigation with `aria-current`; Next up is one strip with one button; the day pills are buttons with `aria-current`, and each day is a labelled slide; the day rail is decorative; the Add button is named for what it adds ("Add to Day 2"); the info button and every icon-only button have names; sheets are `role="dialog"` and close on Escape or the backdrop; weather icons carry a text label
- **Motion**: chips and buttons change colour at Micro timing; the Add button fades down out of the way while a phone scrolls down, and its press scale is removed for reduced motion; the day carousel scrolls smoothly unless reduced motion is on
- **Layout**: Plan pairs the itinerary and the map on wide screens and stacks them on phones; Ideas pairs the list and the map from 1024px; tabs stick to the top of the scroll area; from 1024px the Add button sits at the right of the tab row; below that it floats at the right of the screen, and on phones 20px above the bottom bar

### Travel home
- **Structure**: title and one line, a New trip button, trips on now and coming up as photo cards, "Where to next?" (a place and when, handed to the chat to research, example chips and Add a trip), bookings not on a trip, past trips, research
- **Trip card**: cover photo or gradient, a when-chip, destination (the link; the whole card is clickable), dates with days and nights, budget and companions; a grid of cards at least 300px wide; past trips are smaller and desaturated
- **Research**: each researched place is listed under the trips; its page gives the budget, when to go, costs, where to stay and the sources, with a button to make a trip of it or open the one already made
- **States**: loading, error, and "No trips yet" with ways to start
- **Layout**: groups stack in the order On now, Coming up, Where to next, loose bookings, Past, Research

### Travel parts
These are the rules the Travel pages follow. New Travel screens keep to them.

- **Buttons**: one filled indigo primary per view. A secondary button for a row or a card (Add to day, Find ideas, Open day) is `.btn-soft`: pale indigo with indigo text. Quiet ghost buttons (`.btn-ghost`) carry an icon and text, at least 40px tall. Plain grey `.btn` is only for cancel and back. Destructive is a quiet rose button, never filled.
- **One chip**: `.day-pill` is the only chip, for days, stops, lists, scopes and themes. It is white; on is pale indigo (`--accent-soft`) with `--accent-text` and `--accent-border`. A stop's or list's colour shows only as a dot. 40px tall on touch. A choice with many options is one chip with a ▾ that opens the options, not a row of chips.
- **Icons, not emoji**: use the app's line icons (`Icon.tsx`). Weather icons carry a text label. Map markers use the letters F and T for flights and trains (and H for a stay) because Google's classic markers can't take SVG.
- **Money**: always the ISO code, through `formatMoney`, never a symbol. A range is "SGD 4,602–6,760". A foreign amount is followed by its home amount when known: "JPY 2,000 · SGD 18.00". A sentence that would show zero is left out.
- **Type**: 13px (0.8125rem) is the floor everywhere in Travel. Headings and labels are sentence case, with no all-caps. The serif italic (`.accent-serif`) is Travel's accent for a trip's title; the cover and trip cards do not use it yet.
- **Warmth**: it comes from the trip's own photos and the serif. Travel adds no colours.
- **The Add button**: white on indigo, with a plus and the word "Add", 52px tall, named for what it adds. Below 1024px it floats at the right; on phones it sits 20px above the bottom bar. From 1024px it moves to the tab row. Every tab has one except after the trip.

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
- On phones the bottom bar is fixed to the bottom edge above the safe area; nothing blurs, to keep scrolling smooth.

## 7. Depth & Surface

### Strategy

Mixed: subtle borders define dense data regions, while tonal surfaces and tinted shadows define
cards and sheets. Do not add a new shadow recipe to individual components.

- Application frame: existing prominent tinted shadow.
- Cards: `--border-card` plus `--bg-card`.
- Elevated dialogs: `--bg-card-hover` plus existing modal shadow.
- Directional status: emerald and ember tint at low opacity, never as a full background.

## 8. Accessibility Constraints & Accepted Debt

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
