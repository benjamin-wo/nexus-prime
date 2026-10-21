# Nexus Prime Design System

## 1. Atmosphere & Identity

Nexus Prime is a focused financial command center: light, cool, and quick to scan. Its
palette is True Summer: muted blues on an icy off-white page. Home is a Today page: it opens on
an indigo hero (the month's one big figure and Nexus's brief, not in a card) that fades into the
page, with what needs the person directly under it; every other segment is its own white card,
its title above it. Indigo is the action
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
- Home's overview is not a card: a hero on solid indigo (full-bleed at the top on phones, fading into the page; a rounded panel on desktop) with the day and greeting, this month's spending as the one big figure with an arrow, how it stands in words and the brief, plus round buttons for Log expense and Settings. The ask box and the one-tap questions are not on it: they are their own card further down (see Today).
- Buttons are filled: primary indigo with white text, secondary `--bg-raised`; no outlines. In Travel the secondary is the soft button (`.btn-soft`, pale indigo with indigo text) and grey `--bg-raised` is only for cancel and back; see Travel parts.
- Department tabs are a rounded segmented control on one row, sharing the width on phones; keep a department to five tabs or fewer (one-off tasks like Import are reached from the page that needs them).
- The accent is for actions (the main button, the active tab, today) and status, not decoration: figures in the brief are white and bold, links in text keep the text's colour with an underline, and a section's heading actions (Details, Open, See all, Edit) are all small buttons.
- In Telegram the app behaves natively: Telegram's back button on a page inside a section (a trip, a stock, a plan, Import), a light haptic tap on the main button and a tick when changing tab or day, Telegram's header in the hero's indigo on Home and the page colour elsewhere, its bottom bar deep slate like ours, and no swipe-to-close while scrolling.
- The phone's bottom bar is deep slate with rounded top corners: Home, Accounting, the indigo ✦ Nexus button in the middle (it opens the chat), Investment, Travel; icons only, names for screen readers. Settings is the cog at the top of Home (and in the rail on a wide screen, under the indigo Ask Nexus button).
- No floating chat bubble: Nexus lives in the bar. The only floating button is a trip page's labelled Add button (white on indigo, a plus and "Add"), 20px above the bottom bar on a phone, where it steps aside while the page scrolls down and comes back on the way up, and in the trip's header, beside Share, from 1024px.
- An amount never breaks inside its figure: tile figures size to their box and wrap, if they must, between the currency and the number. Differences are said in words, not with a minus sign in green.
- Say a figure once per screen: Home's hero gives this month's spending and how it stands, so its Money this month card adds only the pace; the Accounting overview's Spending by month card shows the trend and adds what the tiles around it don't (a usual month; the biggest category is "Where it went", beside it).
- Empty sections are one short line, left-aligned, with one action; a secondary way in (adding a holding by hand, recording a trade) stays behind a small button until asked for.
- Charts say one thing: past months are quiet mist bars, rose stripes only mark a month over budget, this month is solid indigo over the dashed iris outline of a usual month, and the legend lists only what's drawn.
- Ledger on a phone: no tick boxes until Select; dates are chips (All, This month, Last month, Custom), with the date boxes only for Custom.
- Touch targets: on touch screens small buttons and chips are at least 40px tall and filter tabs 38px.
- One heading style: sentence case, no emoji. Small capitals (eyebrow) are only for labels inside a section.
- Page padding 40px 48px on desktop, 16px on phones.
- On phones a page's actions sit under its title and share the width (a primary action gets its own row); a section's note sits under its heading; form buttons fill the row.

### Home hero

- **Structure**: the day and greeting with round Log expense and Settings buttons; this month's spending as the big figure (counting up) with an arrow (down when it's the better side); how it stands in words (budget left, or against last month by this date); the brief
- **Content**: the brief is written in code from the user's own figures (`brief.ts`), never a model's words; figures in it are bold. It spans the areas in this order, each only when there is something to say: money (left to spend when it is the tighter figure), one market clause (the held stock that moved most in the latest US session, when it moved by 3% or more: "NVDA is down 5% today", "NVDA fell 5% in the last session"), the trip ("You're on day 3 of 6 in Tokyo", "Your Tokyo trip is in 12 days"), then "N things need you below", where N is the whole of Needs you, which is the next thing on the page
- **Surface**: solid indigo from `--hero-top` to `--hero-mid`, fading into the page on phones

### Today (Home)

- **Order on a phone**: the hero, the trip card while a trip is on, Needs you, Working on (only while research runs), Ask anything, Get set up (only while unfinished), then Money this month, Portfolio today and Next trip. From 1024px two columns (3 to 2): Needs you, Working on, Ask anything and Get set up on the left, the three cards at a glance on the right, and the trip card across the top of both
- **Needs you**: a titled block of rows (icon tile, text, a caption naming the area: Accounting, Investment or Travel). The API sorts by `when`; the page keeps its order and shows the first five, then a ghost "Show all (n)" button under the list (`aria-expanded`; "Show fewer" once open) opens the rest in place. An item that needs the person now (`when: "now"`) has the alert icon in an amber tile and a small amber "Now" tag at the right; an item about today says "· Today" after its area, in caption text, with no other mark; the rest say neither. A row links to where it is settled, and its buttons (the first one primary) settle it in place. With nothing: "Nothing needs you right now."
- **Working on**: a compact card under Needs you, up to three runs, each a title, its progress line and a thin bar, with Cancel while it runs
- **Ask anything**: a card with the ask box (the input surface, an indigo send button) and the suggested questions as chips; each opens the chat
- **Get set up**: shown while the server's checklist is not dismissed and has a step left; it goes by itself when every step is done. A line says how many steps are left; each step is a row, ticked with "Done" when done, else an empty ring and a soft "Set up" link to the page where it is done. "Get receipts in automatically" also has a quiet "Ask Nexus" button, since its sentence is a request for help; the other sentences (`ask`) carry example values (a payday, a stock, a budget) and are never sent as if they were the person's. "Hide" in the heading calls `POST /api/setup/dismiss` and the card goes; if that fails it says so under the list and stays
- **At a glance**: three small titled cards, each with one link at the right. Money this month: spent (the figure the hero also shows, as a card needs it), then with an overall budget the share used against the share of the month gone as a meter with "Ahead of pace" (amber), "On pace" or "Under pace" (more than 5 points apart), without one "Last month by now: SGD 1,200.00"; Details opens Accounting. Portfolio today: the value in the home currency, the day's change in green or rose and the `PriceWhen` caption (live dot, close); with no holdings "No holdings yet. Add your stocks."; Open opens Investment. Next trip: "Tokyo in 12 days" (or "tomorrow") with its dates and any nights with no place to stay; with none "No trip coming up. Plan a trip."
- **Trip mode**: while the next trip is on, a titled card ("Day 3 in Tokyo", Open trip at the right) leads above Needs you and Next trip gives way to it. It has up to three lines, each only when the trip's data has it: Next (the first plan today still to come, with its time; else one with no time; else "Nothing more planned today."), Spent today with what is left per day of the trip's budget, and Next booking (the next flight, train or stay after today). Nothing here asks the server for more than the trip page does
- **Left out of Home**: the six-month chart (now on the Accounting overview), the Budgets card (Plan) and the Today investment card (Investment)

### Spending by month (Accounting overview)

- Six bars: mist for past months, striped rose over the overall budget, solid indigo for this month so far over the dashed outline of a usual month; the budget as a dashed line
- Placed in the left column of the overview, under Where it went
- Two small tiles underneath: budget left (or money received) and a usual month; the biggest category is Where it went, beside it
- Every bar's month and amount is in text for screen readers; the legend names every mark

### Rows

- Icon tile (42px, `--bg-raised`), title and caption, value on the right; rows divided by `--border-card`
- Used for what needs you, holdings, the latest transactions and budgets

### Investment

- **Prices**: every price says when it is from, in one muted caption (13px, `.caption`) built by `priceWhen` in `format.ts` and shown with `PriceWhen`: "Live · 10:42pm" while the US market is open (with a 6px emerald dot, the only mark of live), "Close (provisional) · 4:00am" after the close until the official close arrives, and "Close of Fri 16 Oct" otherwise. Times are in the browser's timezone. The label sits in the Holdings card's heading row, under the price on the watchlist and stock page, and under the total on Home's Portfolio today card; a holding whose price is of another kind than the card's says so under its price. While a price is live and the page is in view, Portfolio, Watchlist, a stock and Home's Portfolio today card ask again every 60 seconds (`livePolling`) and on window focus; a close is not polled.
- **Today card**: how the portfolio did in the latest US session, at the top of Portfolio (a card under the heading); Home has no such card, only the day's change on Portfolio today. The title follows the session: "Today" while the market is open (with the `PriceWhen` label and its live dot), "Today's session" after the close, "Last session" before the next open. The change in the home currency and its percentage are the one big figure, green or rose as gains are everywhere else; under it up to three movers, each with the stock as a link, its move, its price and the day's newest headline as a quiet 13px line (a link out when it has a url), and a ghost "Why did it move?" button that reads the day's headlines and answers in place in 2 to 3 sentences with "From today's headlines" beneath ("Try again in a minute" after a 429, the server's short reason for a 404 or 422, else "Couldn't read that move just now"). It asks again every 60 seconds while live and in view, and is hidden when nothing is held or watched. It adds no primary action.
- **Stock page**: the Price card holds the price, then under it a quiet list of up to three facts against the levels ("1.2% below resistance at 131.00", "10.4% above its 50-day average (117.25)") in caption text, with no heading of their own. The page's one primary is Make a plan.
- **Plan page and Plans list**: under the title, a price line ("Price 182.40", then the muted `PriceWhen` caption: a live dot and "Live · 10:42pm", "Close (provisional) · 4:00am" or "Close of Fri 17 Oct"), left out for a plan made before prices were kept; then the usual "Closing price" line, and, quietly in caption text, "Refreshed from the plan of 7 Oct" (a link to that plan) when the plan replaced an older one. The verdict card carries the backend's price notes as amber callouts with a warning sign ("The price is already under the buy zone: …"). Under it, an open plan has a card with one switch, "Keep this plan fresh" (the same checkbox-in-a-label `toggle` as "Telegram alerts for this plan", 44px tall) and the caption "Nexus re-runs it when the price moves a lot, after earnings, or once a week."; it changes at once and is put back, with the server's words in red under it, if refused; a finished or refreshed plan has no such card. A refreshed plan shows a muted "Refreshed" badge where target, stopped and ran out show, and "A newer plan replaced this one" as a link under the title. In the Plans list an open plan with the switch on has a small indigo "Fresh" tag beside its status, and a refreshed plan its "Refreshed" badge; refreshed plans stay in the list but not in the track record. There is no popup when a plan is made: the plan page, where the result is read, is where the switch is offered.
- **Settings**: the investment fields sit in the Telegram updates card under their own "Investments" heading and each saves alone with only the field that changed: Quiet hours (two time inputs, From and To, default 23:00 to 08:00; "Nexus holds messages in these hours. A broken stop on a stock you hold still comes through."), Big move alerts (a number input, 1 to 20%, saved when the field is left or on Enter; the server's refusal shows beneath and the saved value stays) and a Morning investment summary switch ("At 8am after each US trading day."). Captions are 13px, in sentence case.

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
- **Variants**: outgoing, incoming, pending, paid, completed, error, now (the amber tag on a Needs you item that needs the person now)
- **Spacing**: `--space-1` vertical and `--space-2` horizontal padding
- **States**: default, focus when interactive
- **Accessibility**: text always names the state; contrast target is WCAG 2.2 AA
- **Motion**: none unless status changes, then opacity crossfade
- **Layout**: inline cluster item

### Trip page
- **Structure**: on Plan, a cover (a photo with only light round buttons on it: a Trips back pill, Share, the Add button from 1024px and a ⋯ menu, and the photo credit behind a round info button), and under the photo, on white, the destination in the serif italic, a meta row with dates, a when-pill and companion initials, the Next up line and, on a shared trip, the latest change. On the other tabs, and on Plan once the photo has scrolled behind it, the cover is replaced by a slim sticky bar: a back arrow, a 36px thumbnail of the photo, the destination (the page's h1 there) with its dates, then the same actions. Under it a segmented tab bar, Plan, Ideas, Money and Prep (the open tab is in the address as `?tab=`, and the open day as `?day=`), which sticks under the slim bar, or to the top while the cover is showing; the tab's content; the Add button. The ⋯ menu holds Edit trip, Getting around and directions, the photo choices (Another photo, No photo or Show a photo) and Delete trip
- **Variants**: Plan (a stops row, each stop with its dates and nights and a travel marker between stops, with Edit stops beside it; the day pills and the day carousel in one card, a day at a time, swiped or picked, each day as tall as its plans and the pills a sticky strip under the tab bar; a rail dot and the day's stay, plans, flights and trains, travel times between them, a name for the day and plans moved by their grip or onto a day pill; a tap on a plan, flight, train or stay opens it in place (address, Google Maps, link, note, booking reference and a quiet Change that opens the editor) and a second tap folds it, while a press that moves more than 8px or lands as the days scroll does nothing, so a swipe never opens an editor; the map beside it from 1024px, stuck in view while the day scrolls, and full screen on a phone when asked, showing one day or all, with an Ask Nexus about this trip button underneath; while the trip is on, today comes first), Ideas (saved places without a day as quiet rows: a name, one meta line, a cost when there is one and one action, Add to day or the day it is on; a row opens to its note, Google Maps link, rating, Change and Remove; the lists as chips once there are two, an Arrange button that shows the drag grips only while it is on, a List and Map switch where maps are set up, and the map beside the list from 1024px; a Find ideas button above them opens the finder in a sheet), Money (a column no wider than 760px; one summary card of what is spent, booked and planned against the budget, a To do card for costs to split and people to settle with, then Details, a list of sections of which one is open at a time: Where it goes, Planned costs, Setting money aside, Bookings paid, Expenses, Paid by others, Travellers; once the trip is over To do comes first, then what it cost), Prep (the same column; Getting ready, one list of what's still to sort, what Nexus suggests and the to-dos, then Cover and documents, the packing list as checkbox rows, the weather for the trip and the notes)
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
- **Next up**: one quiet line of text in the cover's text on Plan only, a sparkle icon at its left and one ghost text button (the action, in accent text) at its right, 44px tall on touch; it is not on the other tabs, and once the trip is over it says who still owes
- **Spacing**: `--space-4` card padding and between cards, `--space-2` timeline gaps
- **States**: loading, error, empty sections ("None yet", "No ideas yet", "Free day"), imported from a screenshot (a banner asking whether it looks right), adding, editing; after the trip there is no Add button, Money opens first and Next up (on Plan) is about settling up
- **Accessibility**: the tabs are a labelled navigation with `aria-current`; Next up is one labelled region with one button; the cover's buttons are hidden from assistive tech while the slim bar stands in, and the page has one h1 (the cover's title, or the slim bar's); the day pills are buttons with `aria-current`, and each day is a labelled slide; the day rail is decorative; the Add button is named for what it adds ("Add to Day 2"); the info button and every icon-only button have names; sheets are `role="dialog"` and close on Escape or the backdrop; weather icons carry a text label
- **Motion**: chips and buttons change colour at Micro timing; the slim bar fades in over 160ms (none for reduced motion), the Add button fades down out of the way while a phone scrolls down, and its press scale is removed for reduced motion; the day carousel scrolls smoothly unless reduced motion is on
- **Layout**: from 1024px Plan and Ideas put the day or the list on the left (60%) and the map on the right (40%, at least 300px), and the map sticks below the slim bar and tab bar (112px) with a canvas of at most 600px, so it stays in view; on phones they stack. Money and Prep are a centred column of at most 760px. The slim bar (56px) and the tab bar (56px) stick to the top of the scroll area, and the day strip sticks under them at 112px (`--trip-sticky-top`). From 1024px the Add button sits in the header beside Share; below that it floats at the right of the screen, and on phones 20px above the bottom bar, with room under the last item so it covers nothing

### Travel home
- **Structure**: the heading "Your trips" with "trips" in the serif italic, one count line under it ("1 on now · 4 coming up", left out when there is nothing to count; a guest's reads "The trips you were invited to."), and one primary at the right, New trip with a plus
- **Trip card**: a photo on top (140px; a gradient from the destination's name without one), then on white the destination in the serif at 26px (the link; the whole card is clickable) beside a pale-indigo when-chip, one line of dates with days and nights, and the companions as small round initials at the right. A card on a trip the person was added to also says "Shared by <owner>" and shows no budget. Cards in a row are equally tall
- **Grid**: one column on a phone, two from 720px, three from 1280px, with `--space-4` between cards
- **Order**: On now, Coming up, Shared with you, Where to next, bookings not on a trip, Research, then Past trips, then the footer line. Groups with nothing in them are left out
- **Where to next**: not a card: a title, a place-and-when field with Research it (handed to the chat), and example chips with Add a trip in one row that scrolls sideways (hidden scrollbar)
- **Past trips**: one button, "Past trips · 3" with a chevron, shut until pressed (`aria-expanded`); open, the trips are compact rows with a 56px desaturated thumbnail, the name (the link) and the dates, with no card
- **Footer**: one centred caption at the foot, "Each trip keeps its bookings, plans and money together. Nexus never books anything."; a guest does not get it
- **Research**: each researched place is listed under the trips, with its date; see Research page
- **States**: loading, error, and "No trips yet" with ways to start

### Shared trip page
`/shared/<token>`, the read-only link, signed out. A centred column of at most 760px (a card from 720px, a full-width band on a phone).

- **Cover**: the trip's photo (or gradient) with the credit button and a white glass chip, "Shared with you · read only"; under it the title in the serif (36px, 48px from 720px) and one line of dates and stops ("Nov 10 – Nov 14 · Tokyo and Kyoto") with the when-chip
- **Days**: one card each: a meta line ("Day 2 · Wed, Nov 11"), the day's name in the serif (its label, else the stop), then rows divided by hairlines. A plan's row is a 48px time column, the title with one quiet line (address, or the kind and address) and a ghost Maps link; a flight or a stay has its line icon in place of the time, and a stay a Check in or Check out badge. A day with nothing says "Free day"; with bookings hidden, a day a hidden booking falls on says "Travel day"
- **Bookings hidden**: a quiet note under the cover says "Bookings aren't shown on this link."
- **Foot**: "Times are local." and a centred caption saying that no money, booking references, notes or travellers are shown. No buttons: nothing on the page can be changed

### Research page
`/travel/research/<run>`: a back link to Trips, the place in the serif (36px, 48px from 900px) with one line ("Jan 10 to Jan 17 · 7 nights · 2 travellers").

- **One primary**: Make it a trip. Once a trip is made it is replaced by a soft Open the trip
- **Estimated cost**: the first card, a label, the range large ("SGD 4,602–6,760"), "for 7 nights, 2 travellers", the budget line ("Fits your budget of SGD 6,800"), what makes it up, and the put-aside sentence with its cash-flow verdict
- **Then**: When to go, Costs (a row each: the label with its source number, per person or per day under it, the range at the right, wrapping under the label on a phone), Where to stay (a Save its ideas box per area, and the soft Add to a trip…) and Getting around
- **Sources**: one card at the foot that is shut, "Sources · 2" with a chevron (`aria-expanded`); open, it says other people's pages are not booked from and lists them, each with the day it was checked. Source numbers ([1]) are 13px or more

### Sheets
One component, `Sheet` (`components/Sheet.tsx`), is the dialog for every Travel screen that is not a page: Add, Getting around and directions, the pin prompt, Recent changes, the day picker, Share, Stops, the finder, the cover form and the Add to prep choice.

- **Structure**: a header (an optional back arrow, the title in 17px semibold, a 44px close X), a body that scrolls on its own, and an optional footer that stays in view. On a phone a short grab bar tops it.
- **Layout**: on phones (up to 720px) a bottom sheet, full width, at most 90% of the screen's height, with 20px top corners, sliding up over 280ms and clear of the bottom bar and the home indicator. From 721px a centred dialog 640px wide (at most the screen less 48px) and at most 85% of its height, fading in. The page behind is dimmed and does not scroll, even when the keyboard opens.
- **Behaviour**: it is `role="dialog"` and `aria-modal`, named by its title. Escape and a tap on the dimmed backdrop close it, as does the X; the back arrow (shown only where a sheet has two views, as Add does) steps back to the first view. Focus goes to the first field when it opens (not on a phone's Type it, so the keyboard stays down) or to the dialog itself, and returns to the button that opened it when it closes. A sheet never opens another sheet or dialog on top of itself: a choice that needs a second step happens inside it, as a view, a menu or a confirmation box.
- **Forms**: a sheet can be the form itself (`as="form"`), with its primary button in the footer. It has at most one primary button in view, and fields are 16px on a phone.

### Travel parts
These are the rules the Travel pages follow. New Travel screens keep to them.

- **Buttons**: one filled indigo primary per view. A secondary button for a row or a card (Add to day, Find ideas, Open day) is `.btn-soft`: pale indigo with indigo text. Quiet ghost buttons (`.btn-ghost`) carry a 16px icon and text, at least 40px tall. Plain grey `.btn` is only for cancel and back. Destructive is a quiet rose button (`btn btn-ghost btn-danger`: transparent, rose text), never filled. A ghost button's hover is the faint `--bg-card-hover`, never a grey fill. A ghost button that starts a line (See costs, Details, Take off, Make a new link) is pulled 12px left so its words line up with the text above it. Icon-only buttons (a packing item's remove) are at least 40px, 44px on touch.
- **One chip**: `.day-pill` is the only chip, for days, stops, lists, scopes and themes. It is white; on is pale indigo (`--accent-soft`) with `--accent-text` and `--accent-border`. A stop's or list's colour shows only as a dot. 40px tall on touch. A choice with many options is one chip with a ▾ that opens the options, not a row of chips.
- **Icons, not emoji**: use the app's line icons (`Icon.tsx`). Weather icons carry a text label. Map markers use the letters F and T for flights and trains (and H for a stay) because Google's classic markers can't take SVG.
- **Rows**: an Ideas row is quiet: a coloured list dot, the name (a button that opens the row) over one meta line of address, kind and "Near Day 2 · 1.2 km", the cost at the right when there is one, then the row's one action as a 44px button. Rows are divided by a hairline and carry no card, badge or chip. What a row opens to (note, Open in Google Maps, rating and Details, Change and Remove) sits under it, indented to the name. Drag grips show only while Arrange is on, with a line saying how; a row's own button keeps working then.
- **Find ideas**: the Ideas tab has one Find ideas button (soft, with a search icon, 44px), beside the List and Map switch on a phone and on its own line from 1024px. It opens the finder in a Sheet titled "Find ideas": a search field with its Search button, then one scope chip, then the themes in one row that scrolls sideways, then the results. A result is a 56px tile (the place's photo, or an icon for its kind), the name, one meta line ("Rated 4.6 (2,310) · Jung-gu · Google Maps", or "From a guide" for an idea from an article, with the source linked) and one soft button, Save to Ideas (and Add to Day N when the search is near a day). A saved result turns into a disabled green "Saved" button and the sheet stays open, so several can be kept; closing it shows the ideas.
- **Scope chip and menu**: the finder's scope is one chip, "In Tokyo ▾" (its name is "Look in: In Tokyo"), that opens a menu of Whole trip, each stop and Near Day N, with a tick on the one in use. The menu is a popover under the chip (`role="menu"` of radio items), closed by Escape, a choice or a tap elsewhere; Escape closes the menu first and the sheet on the next press. It is the pattern for any choice with many options, in place of a row of chips.
- **Getting ready**: the first card on Prep, one list with hairlines between rows of 56px at least, in this order: what's still to sort (a warning icon, the text and one soft button, Add or Set, as Next up's), then Nexus's suggestions (a sparkle icon, the text over one quiet line, a soft Add and a ghost "Not needed" with an x; on a phone the two buttons sit on their own line under the text, in line with it), then the to-dos not done, then the done ones. The card's heading has "N to do" at the right; with nothing to do it says what is sorted. A to-do is a round 24px checkbox (accent when ticked) named by its text, an optional line under it ("By Tue 8 Dec", or "Overdue · Tue 8 Dec" in the warning colour and semibold once past and not done) and a quiet 40px (44px on touch) x that removes it. Ticking one sinks it to the bottom, muted and struck through. Under the list a hairline and the add form: a text field, a date field labelled "By (optional)" and a soft Add (disabled until there is text), with the note "With a date, Nexus reminds you the day before." Once the trip is over nothing is added, and the card is left out when there is nothing to show.
- **Cover and documents**: the card under it, for insurance, visas and other documents. Each is a 56px row: a line icon (a shield for insurance, a stamp for a visa, a page for the rest), the name over one quiet line ("Insurance · TX-4471 · 2–9 Dec"; the name is the button that opens the cover) and, for the owner when it has a cost, the cost at the right with a soft Log it under it, or "Logged" with a tick. Under the row, in line with the name, are quiet Call +65 6123 4567 (a `tel:` link) and Copy (the reference) buttons; Log it opens a tinted confirm box in place, "Record SGD 89.00 as spent on Travel? Nexus only records it.", with a primary Log it and Not now (the same box on Money's Bookings paid). The card ends with a ghost "Add cover or a document" and, outside a guest's view, a caption that says it can be done by chat. A member sees no cost, Logged or Log it.
- **Cover sheet**: a `Sheet` form titled "Add cover or a document" or "Change <name>": a Kind chip row (Insurance, Visa, Document, Other: one radio group of `.day-pill`s), the name (labelled Insurer for insurance), Policy or reference, Emergency phone, From and To, for the owner Cost and Currency (home currency to start with), and Note. Its footer holds Save, the one primary, at the right and, when changing, a quiet rose Delete at the left, in line with the fields; Delete asks first in a tinted box that says an expense already logged stays. A member's has no cost fields.
- **Add to prep choice**: a `Sheet` titled "Add to prep" of three `.way` rows, each a 40px icon tile, the title and one caption: A to-do, Cover or a document and Something to pack.
- **To do**: the card on Money that holds what needs doing with the people going, and only appears when there is something: "N costs to split" (the total and the names, a soft Split button and See costs to list them with Split and Keep as just mine on each) and one row per person to settle with ("You owe Ann SGD 45.00" or "Ann owes you SGD 135.00", a soft Settle up button and Details for what makes it up). Splitting and settling confirm in place, in a tinted box under the row, never a dialog: a sentence saying what will be recorded (and that Nexus doesn't move money), the choice where there is one ("Also record my share as spent"), one primary (Split evenly, Mark settled) and a ghost Not now. A line under the card's title says Nexus records what you say happened. The card is hidden when nobody else is going.
- **Details accordion**: Money's sections are rows in one card, each a button with its title at the left, a one-line summary at the right ("2 categories", "None yet", "You and Ann") and a chevron, 56px tall, divided by hairlines. One is open at a time (opening one closes the other, with `aria-expanded` on the button and the content a labelled region), and all start closed. Sections with nothing to show (Setting money aside once the trip has started, Bookings paid with no costs, Paid by others with no payments) are left out. A section's form (a planned cost, someone else paid) opens inside its section; the Add button opens the section it belongs to.
- **Money**: always the ISO code, through `formatMoney`, never a symbol. A range is "SGD 4,602–6,760". A foreign amount is followed by its home amount when known: "JPY 2,000 · SGD 18.00". A sentence that would show zero is left out.
- **Type**: 13px (0.8125rem) is the floor everywhere in Travel. Headings and labels are sentence case, with no all-caps. The serif italic (`.accent-serif`) is Travel's accent for a trip's title: the trip page's cover and slim bar, the trip cards, the shared page and the Research page use it.
- **Warmth**: it comes from the trip's own photos and the serif. Travel adds no colours.
- **The Add button**: white on indigo, with a plus and the word "Add", 52px tall, named for what it adds. Below 1024px it floats at the right; on phones it sits 20px above the bottom bar. From 1024px it moves to the trip's header, beside Share, and is the only Add on the page. Every tab has one except after the trip.
- **Trip invite page**: `/trip-invite/<token>` is a small centred card on the sign-in page's background. Signed out: "You've been invited to a trip" with "Sign in with Telegram to join." and the Telegram button (inside Telegram it signs in at once and the page only shows if that was refused, with a line saying the invite couldn't be used). Signed in: "Joining the trip…", then the trip opens with a short notice ("You've joined the trip to Kyoto."; their own link says "That's your own invite link. Send it to the person you want on the trip." and joins nothing; a trip they are already on opens with nothing said). A link that is used, cancelled, expired or unknown shows "This invite doesn't work any more" with "Ask the trip's owner for a new link." and one primary, Go to Home, or Go to Trips for a guest; any other failure shows "Couldn't join the trip", the reason and Try again
- **Guest app**: someone brought in by an invite with no account of their own sees Travel only: Trips (titled with "The trips you were invited to.") and the trips they are on. A slim header holds the app name, linking to Trips, and at the right their name and Sign out. There is no rail, no bottom bar and no chat, so no Ask Nexus, no New trip, no Where to next, no loose bookings or research and no Type it in the add sheet. Every other address goes back to Trips. With no trips yet: "You're not on any trips yet. Open an invite link to join one."

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
