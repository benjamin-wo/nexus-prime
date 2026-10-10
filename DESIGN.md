# Nexus Prime Design System

## 1. Atmosphere & Identity

Nexus Prime is a focused financial command center: dark, quiet, and quick to scan. The
signature is the ember accent used as a deliberate action signal against layered charcoal
surfaces. Financial direction carries meaning: ember marks money out, emerald marks money
in, and amber marks attention or pending work.

## 2. Color

### Palette

| Role | Token | Dark | Usage |
|------|-------|------|-------|
| Surface/primary | --bg-shell | #09090b | Browser and page background |
| Surface/secondary | --bg-frame | #0d0d10 | Application frame |
| Surface/elevated | --bg-card | #151518 | Cards, tables, sheets |
| Surface/interactive | --bg-card-hover | #1b1b1f | Hovered controls and rows |
| Input surface | --bg-input | #121215 | Form controls |
| Text/primary | --text-primary | #f4f4f5 | Main content |
| Text/strong | --text-white | #ffffff | Headings and emphasis |
| Text/secondary | --text-secondary | #a1a1aa | Supporting content |
| Text/tertiary | --text-muted | #8b8b94 | Metadata and hints (lightened from #71717a to pass 4.5:1 on cards) |
| Border/default | --border-card | #202024 | Card and table boundaries |
| Border/subtle | --border-subtle | #222226 | Rails and dividers |
| Accent/primary | --orange-primary | #f97316 | Primary actions and money out |
| Accent/hover | --orange-hover | #ea580c | Primary hover state |
| Accent/soft | --orange-soft | rgba(249,115,22,0.15) | Money-out surfaces |
| Accent/border | --orange-border | rgba(249,115,22,0.35) | Money-out control edge |
| Status/success | --emerald-accent | #10b981 | Money in and completed states |
| Status/success-soft | --emerald-soft | rgba(16,185,129,0.15) | Money-in surfaces |
| Status/success-border | --emerald-border | rgba(16,185,129,0.35) | Money-in control edge |
| Status/warning | --status-warning | #f59e0b | Pending and attention states |
| Status/warning-soft | --status-warning-soft | rgba(245,158,11,0.10) | Pending surfaces |
| Status/warning-border | --status-warning-border | rgba(245,158,11,0.35) | Pending control edge |
| Status/error | --rose-accent | #f43f5e | Destructive actions and errors |
| Status/info | --cyan-accent | #06b6d4 | Informational accents |
| Surface/raised | --bg-raised | #1f1f23 | Secondary buttons, icon tiles inside cards |
| Accent/text | --orange-text | #fb923c | Figures highlighted inside sentences (the brief, nudges) |
| Accent/glow | --orange-glow | #7c2d12 | The corner glow of the Nexus brief card only |
| Chart/second | --sky-accent | #38bdf8 | The second chart series (within budget), hatched or solid |
| Surface/glass | --bg-glass | rgba(21,21,24,0.74) | Cards: the elevated surface, see-through to the ribbons |
| Ribbon/spark | --ribbon-spark | #fdba74 | The light running along the background ribbons |

### Rules

- Use the existing charcoal and ember direction; do not introduce a second visual theme.
- Accent colors communicate action or transaction direction, not decoration.
- New colors must be added here before they are used in CSS.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| Display | 2rem | 600 | 1.2 | Page title (1.625rem on phones) |
| Figure | 2.125rem | 600 | 1.1 | A card's headline amount |
| Brief | 1.5rem | 500 | 1.4 | The Nexus brief (1.1875rem on phones) |
| H2 | 1.125rem | 600 | 1.3 | Card heading |
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

- Cards 20px (18px on phones), inner tiles and controls 12px, pills fully round.
- Buttons are filled: primary orange with dark text, secondary `--bg-raised`; no outlines.
- Department tabs are a rounded segmented control; they wrap on phones rather than scroll.
- Page padding 40px 48px on desktop, 16px on phones.

### Nexus brief (Home)

- **Structure**: Nexus mark and "Your brief" pill, two or three sentences, one-tap question chips, the ask box
- **Content**: written in code from the user's own figures (`brief.ts`), never a model's words; figures in `--orange-text`
- **Behaviour**: a chip or the ask box opens the chat with that question
- **Surface**: the only element with the corner glow; two faint rings, decorative
- **Layout**: chips wrap on phones; the card never scrolls sideways

### Spending by month (Home)

- Six bars, hatched `--sky-accent` within the overall budget, hatched orange over it, solid orange for this month so far; the budget as a dashed line
- Three small tiles underneath: budget left (or money received), against last month by the same date, biggest category
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
- **Structure**: photo cover (back button, actions, destination, meta row with a when-pill and companion initials, photo credit), sticky pill tabs (Overview, Itinerary, Money), tab content, quick-add button above the chat button
- **Variants**: Overview (next-up boarding pass with an orange band, stay card with nights booked, getting-ready ring with the checklist beside a money card, weather (a temperature range, a scrolling strip of days with icon, high, low and rain chance; rain of 50% or more in sky blue; credited to Open-Meteo) beside the packing list (sky meter, checkboxes, add and Suggest), full-width "Ask Nexus about this trip", reservation counts, notes, collapsible sections), Itinerary (at-a-glance strip: days planned, nights booked, booked; sticky day strip; a rail of numbered day dots, filled for the first and last day, outlined orange for planned days, dashed for empty ones), Money (existing spending cards)
- **Thumbnails**: linked Google Maps places show a 64px rounded photo with a small credit line under it, at the right of a stop and in the stay card; unlinked stops show a plain tile when places are set up
- **Cover**: a Photo menu (Another photo, No photo, or Show a photo) beside the actions; the destination photo under a dark fade to the page background, or a gradient from the destination's name when there's no photo; text sits on the fade, never on bare photo; the credit links to the photo's Commons page
- **Spacing**: `--space-4` cover and card padding, `--space-4` between overview cards, `--space-2` timeline gaps
- **States**: loading, error, empty sections ("None yet"), "Nothing planned yet" days, imported (banner asking whether it looks right), adding, editing
- **Accessibility**: tabs are `role="tab"` with `aria-selected`; the next-up card is a region named for what's next; the ring has a text label and the count is repeated as text; the day rail is decorative (the day headings carry the dates); the day strip and reservation counts are labelled navigation; check-in and check-out are text badges; the quick-add menu is a labelled menu with an `aria-expanded` trigger
- **Motion**: tab background at Standard timing; quick-add press scale at Micro, removed for reduced motion
- **Layout**: overview cards pair on desktop (3:2) and stack under 720px; cover buttons shrink on phones; tabs and day strip stick to the top of the scroll area; the quick-add button sits above the chat button (higher on mobile, above the bottom navigation)

### Travel home
- **Structure**: title and one line, trips on now and coming up as photo cards, "Where to next?" (a place and when, handed to the chat to research, three example chips and Add a trip), bookings not on a trip, past trips (smaller, desaturated), research
- **Trip card**: cover photo or gradient, a when-chip, destination (the link; the whole card is clickable), dates with days and nights, budget and companions; a grid of cards at least 300px wide

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 120ms | ease-out | Press and status changes |
| Standard | 220ms | ease-in-out | Tabs, filters, modal opacity |
| Emphasis | 280ms | cubic-bezier(0.16, 1, 0.3, 1) | Bottom-sheet entry |
| Reveal | 760ms | cubic-bezier(0.16, 1, 0.3, 1) | A card rising into view, 70ms apart, up to 6 at once |
| Fill | 900–1200ms | cubic-bezier(0.16, 1, 0.3, 1) | Bars, meters and rings filling as their card arrives |
| Count | 900ms | ease-out cubic | A headline figure counting up from zero, the first time it's seen |
| Drift | 26–42s | ease-in-out, alternating | The background ribbons |

### Rules

- Animate only `transform` and `opacity` for movement.
- Every new interactive control has hover, active, focus, disabled, and loading behavior where applicable.
- Respect `prefers-reduced-motion: reduce` by removing movement and retaining state changes.
- **Ambient ribbons** (`components/Ribbons.tsx`): bundles of fine ember and amber strands with a soft glow, drifting slowly behind every page, darkened toward the edges so text stays on charcoal. Decoration only: hidden from screen readers, never catching a tap, still for reduced motion.
- **Reveal** (`motion.tsx`): cards, the brief and trip panels fade and rise into place the first time they're scrolled into view; their bars, meters and rings fill as they arrive. Figures that count up keep their format (currency, separators, decimals).
- On phones the tab bar floats as a glass pill above the safe area; cards blur what's behind them only on desktop (hover-capable screens), to keep scrolling smooth on phones.

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
