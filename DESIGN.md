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
| Text/tertiary | --text-muted | #71717a | Metadata and hints |
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

### Rules

- Use the existing charcoal and ember direction; do not introduce a second visual theme.
- Accent colors communicate action or transaction direction, not decoration.
- New colors must be added here before they are used in CSS.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| Display | 2.25rem | 700 | 1.2 | Page title |
| H2 | 1.25rem | 700 | 1.3 | Major card heading |
| H3 | 0.95rem | 700 | 1.4 | Card and modal heading |
| Body | 0.875rem | 400 | 1.5 | Default copy |
| Body/sm | 0.8rem | 400 | 1.45 | Secondary copy |
| Caption | 0.7rem | 600 | 1.35 | Metadata and labels |
| Data | 0.85rem | 600 | 1.4 | Amounts and identifiers |

### Font Stack

- Primary: Plus Jakarta Sans, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif
- Mono: JetBrains Mono, monospace

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

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 120ms | ease-out | Press and status changes |
| Standard | 220ms | ease-in-out | Tabs, filters, modal opacity |
| Emphasis | 280ms | cubic-bezier(0.16, 1, 0.3, 1) | Bottom-sheet entry |

### Rules

- Animate only `transform` and `opacity` for movement.
- Every new interactive control has hover, active, focus, disabled, and loading behavior where applicable.
- Respect `prefers-reduced-motion: reduce` by removing movement and retaining state changes.

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
| Existing emoji-based legacy surfaces | `showcase/index.html` | Outside the unified transaction slice | Replace during broader cockpit icon pass |
| Query-string user identity | `showcase/app.js` and dashboard routes | Single-user-first prototype compatibility | Replace with authenticated session before multi-user launch |
