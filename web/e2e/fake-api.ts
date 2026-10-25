import type { Page, Route } from "@playwright/test";

import type { Setup } from "../src/api";

type WalletRef = { id: string; name: string; kind: string };

type Tx = {
  id: string;
  direction: "in" | "out" | "move";
  from_wallet?: WalletRef | null;
  to_wallet?: WalletRef | null;
  amount: { amount: string; currency: string };
  occurred_at: string;
  counterparty: string | null;
  category_id: string | null;
  notes: string | null;
  status: "confirmed" | "pending";
  source: string;
  deleted: boolean;
  has_receipt?: boolean;
  split?: unknown;
  links?: unknown[];
  own?: unknown;
  duplicate?: unknown;
};

/** An in-memory stand-in for the API, so journeys exercise the real UI in a browser. */
const PLAN_BRIEF = {
  id: "p1",
  symbol: "AMD",
  verdict: "wait",
  verdict_text: "Wait for a dip to buy",
  headline: "AMD: Wait for a dip to buy",
  reason: "It's above the buy zone; support at the 20-day average is a better price.",
  summary_line: "AMD: Wait for a pullback to the entry zone. Entry 124.75 to 125.65, stop 122.95, target 131.00. Valid until 12 Oct.",
  created_at: "2026-09-28T04:00:00Z",
  valid_until: "2026-10-12",
  expired: false,
  status: "open",
  entered_on: null,
  outcome_day: null,
  outcome_price: null,
  result_percent: null,
  alerts: true,
  followed: true,
  keep_fresh: false,
  refreshed_from: null,
  price: "129.50",
  price_at: null,
  price_kind: "close",
};

const FINISHED_PLAN = {
  ...PLAN_BRIEF,
  id: "p0",
  symbol: "MSFT",
  headline: "MSFT: Keep holding",
  verdict: "hold",
  verdict_text: "Keep holding",
  status: "target",
  entered_on: "2026-09-14",
  outcome_day: "2026-09-22",
  outcome_price: "441.00",
  result_percent: "4.6",
};

/** The older plan the made-up p1 replaced when `state.planRefreshed` is on: closed as refreshed. */
const REFRESHED_PLAN = {
  ...PLAN_BRIEF,
  id: "p2",
  headline: "AMD: Wait for a pullback",
  verdict_text: "Wait for a pullback",
  created_at: "2026-09-21T04:00:00Z",
  valid_until: "2026-10-05",
  status: "refreshed",
  alerts: false,
  keep_fresh: false,
  price: "127.80",
};

/** The made-up research's areas (Tokyo): what the ideas endpoint files under a list per area. */
export const RESEARCH_AREAS = [
  { name: "Shinjuku", why: "Central, with late food.", things: ["Gyoen garden"], source: 1 },
  { name: "Asakusa", why: "Old Tokyo, temples and street food.", things: ["Senso-ji", "Nakamise street", "Kappabashi"], source: 1 },
];

/** The signed-in user's name on the trips they own, as `owner_name` and the members list give it. */
const OWNER_NAME = "Ben";

/** A trip the signed-in user was added to (they are a member; the owner is `ownerName`). A test puts it
 * in `state.trips`. */
export function sharedTrip(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "shared1", destination: "Lisbon", start: "2026-11-10", end: "2026-11-12", days: 3, currency: "EUR", budget: null,
    companions: [], set_aside: null, planned: {}, status: "upcoming", days_until: 43, day_number: null, notes: null,
    day_labels: {}, stops: [], split_evenly: true, role: "member", owner_name: "Alex T.", packing: [], ...over,
  };
}

export async function fakeApi(
  page: Page,
  {
    signedIn = true,
    /** Signed in as a guest, someone a trip's owner brought in: only the trip routes, /me and sign-out
     * answer; every other route is refused with a 403 and noted in `state.forbidden`. */
    guest = false,
    emailConnected = false,
    /** GET /me/export answers 429, as the server does when it is asked too often. */
    exportLimited = false,
    /** POST /me/delete answers 422 even for a right confirmation (to show how a refusal reads). */
    deleteRefused = false,
    forwarding = false,
    splitBill = false,
    twins = false,
    running = false,
    research = false,
    chatHistory = false,
    spendingOnly = false,
    planWarning = false,
    /** The user has an IBKR wallet, which statement rows and emails can name. */
    ibkr = false,
    /** Two scheduled moves due on 25 Sep that haven't shown up: the Home nudges. */
    missedMoves = false,
    /** A pending email that may have been a move to the IBKR wallet (needs emailConnected). */
    emailMove = false,
    /** Two entries that look like moves, for the review on the Wallets card. */
    likelyMoves = false,
    /** Home's Today items: a stop reached, a big move, earnings, a flight tomorrow and trip prep, in the order the server sorts them. */
    todayItems = false,
    /** A trip that is on, day 3 of 6 in Tokyo (the dates follow today): a stay, a late plan today, a flight home,
     * and today's spending against its budget. Home leads with it. */
    tripMode = false,
    /** Whether the zone the browser reports on start moves the user's zone, as the real server does. Off by
     * default so the date-bound journeys stay on Singapore whatever zone this machine is in; the report is
     * still noted in `state.zonePosts`. */
    phoneFollows = false,
  } = {},
) {
  let session = signedIn;
  /** What the made-up quotes are right now: live, or (after the close) provisional. */
  const quoteKind = () => (state.market === "open" ? "live" : "provisional_close");
  /** AMD's price on its stock page: its quote while the market is "open" or "after_close", else
   * its close, with the short facts against its levels (support 121.00, resistance 131.00, 50-day 117.25). */
  const amdPrice = () => {
    const quote = state.market === "closed" ? undefined : state.quotes.AMD;
    const price = quote ? Number(quote.price) : 129.5;
    const levels: [number, string][] = [[121, "support"], [112.4, "support"], [131, "resistance"]];
    const below = levels.filter(([v]) => v <= price).sort((a, b) => b[0] - a[0])[0];
    const above = levels.filter(([v]) => v > price).sort((a, b) => a[0] - b[0])[0];
    const near = [below && { level: below, under: true }, above && { level: above, under: false }]
      .filter((n): n is { level: [number, string]; under: boolean } => Boolean(n))
      .map((n) => ({ ...n, gap: Math.abs(price - n.level[0]) / price }))
      .filter((n) => n.gap <= 0.05)
      .sort((a, b) => a.gap - b.gap)
      .map((n) => `${(n.gap * 100).toFixed(1)}% ${n.under ? "above" : "below"} ${n.level[1]} at ${n.level[0].toFixed(2)}`);
    const average = ((price - 117.25) / 117.25) * 100;
    const facts = [...near, `${Math.abs(average).toFixed(1)}% ${average >= 0 ? "above" : "below"} its 50-day average (117.25)`].slice(0, 3);
    return {
      price: price.toFixed(2),
      price_day: quote ? "2026-09-28" : "2026-09-25",
      price_kind: quote ? quoteKind() : "close",
      price_at: quote ? quote.quoted_at : null,
      now_vs_levels: facts,
    };
  };
  type FakeBudget = { id: string; category_id: string | null; limit: number; spent: number };
  type FakeBill = {
    id: string;
    name: string;
    spending?: boolean;
    wallet?: WalletRef | null;
    amount: { amount: string; currency: string } | null;
    cadence: string;
    due: string;
    days_until: number;
    snoozed: boolean;
  };
  type FakePayment = {
    id: string;
    person: string;
    amount: { amount: string; currency: string };
    note: string | null;
    paid_on: string;
    split_with: string[];
    my_share: { amount: string; currency: string };
    settled: boolean;
    settled_at: string | null;
  };
  type FakeItem = {
    transaction_id: string;
    day: string;
    counterparty: string | null;
    category: string;
    amount: { amount: string; currency: string };
    home: { amount: string; currency: string } | null;
    linked: boolean;
  };
  type FakeTodo = { id: string; text: string; due: string | null; done: boolean };
  /** A cover as stored: `cost` is the owner's, and `logged` is set by POST .../covers/{id}/log. */
  type FakeCover = {
    id: string;
    kind: string;
    name: string;
    reference: string | null;
    phone: string | null;
    starts: string | null;
    ends: string | null;
    cost: { amount: string; currency: string } | null;
    logged: boolean;
    note: string | null;
  };
  type FakeMember = { id: string; name: string; role: "owner" | "member"; added_at: string | null; you: boolean };
  type FakeInvite = { id: string; created_at: string; expires_at: string };
  type FakeRule = { id: string; pattern: string; category_id: string; category_name: string; explanation: string };
  type FakeSalary = { rule: string; day: number | null; anchor: string | null; usual: string | null };
  let annRepaid = false;
  /** Counts the to-dos and covers made here, for their ids. */
  let coverCount = 0;
  let dailyAt = "21:00";
  const marketAlerts = { quiet_start: "23:00", quiet_end: "08:00", move_alert_percent: "5.0", market_summary: true, daily_cap: 6 };
  /** The user's time zone, as /me/timezone changes it. Home is Singapore. */
  const zone = {
    timezone: "Asia/Singapore",
    home: "Asia/Singapore",
    source: "home" as "home" | "phone" | "chat" | "trip",
    setAt: null as string | null,
  };
  const userBody = () => ({
    telegram_user_id: 1,
    role: guest ? "guest" : "owner",
    home_currency: "SGD",
    timezone: zone.timezone,
    home_timezone: zone.home,
    timezone_source: zone.source,
    timezone_set_at: zone.setAt,
    display_name: guest ? "Gus L." : "Sam R.",
  });
  const state: {
    /** How many times GET /me/export was asked for (429s included). */
    exports: number;
    /** Every POST to /me/delete, in order: the body sent and the status it got. */
    deletes: { body: { confirm?: unknown } | null; status: number }[];
    /** Every POST to /me/timezone and /me/timezone/home, in order: the path and the body sent. */
    zonePosts: { path: string; body: { timezone?: string; source?: string } | null }[];
    txs: Tx[];
    lastPress?: string;
    chatSent: string[];
    runs: { id: string; status: string; progress: string; [key: string]: unknown }[];
    holdings: { symbol: string; quantity: string; average_cost: { amount: string; currency: string }; cost: { amount: string; currency: string }; updated_at: string }[];
    draft: Record<string, unknown> | null;
    screenshots: number;
    watching: string[];
    /** How many readings of a move were asked for per symbol; the second is "cached". */
    whyAsked: Record<string, number>;
    /** The US market in the fake: "closed" shows the daily closes (the default), "open" the live
     * quotes below, "after_close" those quotes as provisional closes. Tests change it. */
    market: "closed" | "open" | "after_close";
    /** The made-up latest quote per symbol; move `quoted_at` (an ISO instant) to test the times. */
    quotes: Record<string, { price: string; prev_close: string; quoted_at: string }>;
    trips: Record<string, unknown>[];
    trades: Record<string, unknown>[];
    tripItems: string[];
    looseBookings: Record<string, unknown>[];
    movedBookings: string[];
    /** The bodies of PUT /travel/trips/{id}: the whole trip, as the form and the tabs send it. */
    tripPuts: Record<string, unknown>[];
    /** Every trip carries one made-up flight on 10 Nov; false leaves it off. */
    flight: boolean;
    plans: Record<string, unknown>[];
    /** The browser key for the trip map; null: no map (as when it isn't set up). */
    mapKey: string | null;
    hopModes: string[];
    /** A day out from the hotel checked into that day: there and back again. */
    backToHotel: boolean;
    /** Moves sent from the trip page, as "id>day|places@after". */
    moves: string[];
    placeSearches: string[];
    /** Each Google Maps search with where it looked: its trip, stop and day, as sent. */
    placeScopes: { q: string; trip_id: string | null; stop: string | null; day: string | null }[];
    /** Each quick-ideas search with its stop and day, as sent. */
    ideaScopes: { q: string; stop: string | null; day: string | null }[];
    /** The bodies of POST /travel/research/{run}/ideas, with the run they went to. */
    researchIdeaPosts: { run: string; trip_id: string; areas: string[] }[];
    /** The stops sent to PUT /travel/trips/:id/stops, in order. */
    stopPuts: { name: string; start: string; end: string }[][];
    ideaSearches: string[];
    photoChoices: string[];
    shares: Record<string, string>;
    /** Whether a trip's link shows flights, stays and tickets (on unless turned off). */
    shareBookings: Record<string, boolean>;
    shareCount: number;
    /** People added to a trip (besides its owner, the signed-in user), by trip id; a test may fill it. */
    members: Record<string, FakeMember[]>;
    /** A trip's unused invite links, by trip id, with the token each was made with. */
    invites: Record<string, (FakeInvite & { token: string })[]>;
    /** Invite tokens that, accepted, join the signed-in user to a trip (token to trip id): what a
     * test fills in, as the fake user already owns every trip it makes. */
    joinable: Record<string, string>;
    /** Requests a guest made that the server refuses a guest ("METHOD /path"). */
    forbidden: string[];
    /** A shared trip's recent changes by trip id, newest first; a test may fill it. */
    activity: Record<string, { actor: string; summary: string; at: string }[]>;
    /** The bodies of PUT /travel/trips/{id}/notes, in order. */
    notesPuts: Record<string, unknown>[];
    /** A trip's to-dos by trip id, as PUT /travel/trips/{id}/todos last saved them (a test may fill it). */
    todos: Record<string, FakeTodo[]>;
    /** A trip's cover and documents by trip id (a test may fill it). */
    covers: Record<string, FakeCover[]>;
    /** The suggestions marked "Not needed", by trip id. */
    dismissed: Record<string, string[]>;
    /** Every request to the Prep routes ("METHOD /path" and its body), in order. */
    prepRequests: { request: string; body: unknown }[];
    /** Expenses made by logging a cover's cost, by trip id: they count in the trip's spending. */
    coverItems: Record<string, FakeItem[]>;
    /** Whether Settings tells the user when someone changes a trip they share (GET and PUT /trip-alerts). */
    tripAlerts: boolean;
    inviteCount: number;
    /** Expenses split evenly from the trip page, by transaction id. */
    splitDone: string[];
    /** Expenses marked "just mine", by trip id. */
    justMine: Record<string, string[]>;
    /** What fellow travellers paid, by trip id. */
    paidByOthers: Record<string, FakePayment[]>;
    /** People settled up with, as "trip id:name". */
    settledWith: string[];
    /** The bodies of POST /travel/trips/{id}/split, /keep-mine and /settle, in order. */
    splitPosts: Record<string, unknown>[];
    keepMinePosts: Record<string, unknown>[];
    settlePosts: Record<string, unknown>[];
    planStarted: boolean;
    planAlerts: boolean;
    /** Whether the made-up plan p1 is kept fresh (PUT /investments/plans/p1/keep-fresh). */
    planKeepFresh: boolean;
    /** Whether p1 replaced an older plan, p2, that was closed as refreshed. */
    planRefreshed: boolean;
    cancelled: string[];
    budgets: FakeBudget[];
    bills: FakeBill[];
    salary: FakeSalary | null;
    rules: FakeRule[];
    imports: { id: string; file_name: string; added: number; created_at: string; undone_at: string | null }[];
    /** What each import was sent: the ticked rows, and which of them are moves. */
    importBodies: { include: number[]; moves: { row: number; as_move: string | null }[] }[];
    /** Scheduled moves that haven't shown up, as Home nudges: bill id and due date. */
    missed: { bill: string; due: string }[];
    /** Home's setup checklist, as GET /setup answers; POST /setup/dismiss sets `dismissed`. */
    setup: Setup;
    /** What an ongoing trip's spending says about today (null: nothing, as for a trip that isn't on). */
    tripNow: { today: { amount: string; currency: string }; per_day_left: { amount: string; currency: string } } | null;
    /** Emails answered "Move": the email and what was sent. */
    emailMoves: { id: string; body: Record<string, unknown> }[];
    memories: { id: string; kind: string; text: string; happened_on: string | null; updated_at: string }[];
    frequency: string;
    subs: { id: string; name: string; status: string; amount: string }[];
    email: {
      connections: {
        id: string;
        provider: string;
        address: string;
        status: string;
        last_checked: string | null;
        last_received: string | null;
      }[];
      emails: Record<string, unknown>[];
    };
  } = {
    exports: 0,
    deletes: [],
    zonePosts: [],
    runs: running
      ? [
          {
            id: "r1",
            department: "investment",
            kind: "investment.plan",
            title: "Plan for NVDA",
            status: "running",
            progress: "reading the news",
            steps_done: 1,
            steps_total: 3,
            result: null,
            error: null,
            created_at: "2026-09-28T03:00:00Z",
            finished_at: null,
          },
        ]
      : [],
    cancelled: [],
    holdings: [],
    watching: [],
    whyAsked: {},
    market: "closed",
    quotes: {
      NVDA: { price: "131.50", prev_close: "130.25", quoted_at: "2026-09-28T14:41:00Z" },
      AMD: { price: "131.75", prev_close: "129.50", quoted_at: "2026-09-28T14:41:00Z" },
    },
    trips: [],
    shares: {},
    shareBookings: {},
    shareCount: 0,
    members: {},
    invites: {},
    joinable: {},
    forbidden: [],
    activity: {},
    notesPuts: [],
    todos: {},
    covers: {},
    dismissed: {},
    prepRequests: [],
    coverItems: {},
    tripAlerts: true,
    inviteCount: 0,
    splitDone: [],
    justMine: {},
    paidByOthers: {},
    settledWith: [],
    splitPosts: [],
    keepMinePosts: [],
    settlePosts: [],
    chatSent: [],
    trades: [],
    tripItems: ["k1", "k2"],
    looseBookings: [
      {
        id: "bk2",
        trip_id: null,
        kind: "hotel",
        title: "Hotel Sakura, 2 nights",
        provider: null,
        starts: "2026-11-20",
        ends: "2026-11-22",
        segments: [],
        hotel: "Hotel Sakura",
        address: "1-2-3 Nishi-Shinjuku",
        check_in: "2026-11-20",
        check_out: "2026-11-22",
        cost: null,
        logged: false,
      },
    ],
    movedBookings: [],
    tripPuts: [],
    flight: true,
    plans: [],
    mapKey: null,
    hopModes: [],
    backToHotel: false,
    moves: [],
    placeSearches: [],
    placeScopes: [],
    ideaScopes: [],
    researchIdeaPosts: [],
    stopPuts: [],
    ideaSearches: [],
    photoChoices: [],
    planStarted: false,
    planAlerts: true,
    planKeepFresh: false,
    planRefreshed: false,
    draft: null,
    screenshots: 0,
    txs: [
      { ...mk("t1", "out", "12.40", "Maxwell Food Centre", "food"), has_receipt: true },
      mk("t2", "out", "25.00", "Grab", null),
      mk("t3", "in", "4200.00", "Employer", null),
      // Money moved to an investment wallet: neither spent nor received.
      {
        ...mk("t100", "move", "800.00", null, null),
        from_wallet: { id: "w-spending", name: "Spending", kind: "spending" },
        to_wallet: { id: "w-investments", name: "Investments", kind: "investment" },
      },
    ],
    budgets: [],
    bills: [],
    salary: null,
    rules: [],
    imports: [],
    importBodies: [],
    missed: [],
    setup: {
      dismissed: false,
      items: [
        { key: "payday", label: "Set your payday", done: false, link: "/accounting/budgets", ask: "Help me set my payday" },
        { key: "receipts", label: "Get receipts in automatically", done: false, link: "/settings/email", ask: "Help me get my receipts in from email automatically" },
        { key: "investments", label: "Add your stocks", done: true, link: "/investment", ask: "Help me add my stocks" },
        { key: "budget", label: "Set a monthly budget", done: false, link: "/accounting/budgets", ask: "Help me set a monthly budget" },
      ],
    },
    tripNow: null,
    emailMoves: [],
    memories: [
      { id: "m1", kind: "fact", text: "Ann is the user's sister.", happened_on: null, updated_at: "2026-09-28T06:00:00Z" },
      { id: "m2", kind: "preference", text: "Wants short replies.", happened_on: null, updated_at: "2026-09-28T06:00:00Z" },
      { id: "m3", kind: "episode", text: "The Grab ride was for work.", happened_on: "2026-09-27", updated_at: "2026-09-28T06:00:00Z" },
    ],
    frequency: "daily",
    subs: [
      { id: "s1", name: "Netflix", status: "active", amount: "17.98" },
      { id: "s2", name: "Spotify", status: "proposed", amount: "10.98" },
    ],
    email: {
      connections: [
        ...(emailConnected
          ? [
              {
                id: "c1",
                provider: "gmail",
                address: "ann@gmail.com",
                status: "active",
                last_checked: "2026-09-28T04:00:00Z",
                last_received: null,
              },
            ]
          : []),
        ...(forwarding
          ? [
              {
                id: "c2",
                provider: "forward",
                address: "nexus-3f9a2c7e1b04@agentmail.to",
                status: "active",
                last_checked: "2026-09-28T04:00:00Z",
                last_received: "2026-09-27T09:30:00Z",
              },
            ]
          : []),
      ],
      emails: emailConnected
        ? [
            {
              id: "e1",
              received_at: "2026-09-27T04:00:00Z",
              sender: "no-reply@grab.com",
              subject: "Your Grab e-receipt",
              status: "pending",
              reason: null,
              amount: "18.5000",
              currency: "SGD",
              merchant: "Grab",
              received: false,
              transaction_id: null,
              actionable: true,
            },
            {
              id: "e2",
              received_at: "2026-09-26T04:00:00Z",
              sender: "deals@shop.com",
              subject: "50% off everything",
              status: "not_receipt",
              reason: "promotion",
              amount: null,
              currency: null,
              merchant: null,
              received: false,
              transaction_id: null,
              actionable: true,
            },
            {
              id: "e3",
              received_at: "2026-09-25T04:00:00Z",
              sender: "alerts@bank.test",
              subject: "Card transaction alert",
              status: "failed",
              reason: "took too long to read",
              amount: "42.10",
              currency: "SGD",
              merchant: null,
              received: false,
              transaction_id: null,
              actionable: true,
            },
            ...(emailMove
              ? [
                  {
                    id: "e4",
                    received_at: "2026-09-26T08:00:00Z",
                    sender: "alerts@bank.test",
                    subject: "Transfer to IBKR",
                    status: "pending",
                    reason: null,
                    amount: "500.0000",
                    currency: "SGD",
                    merchant: "IBKR",
                    received: false,
                    transaction_id: null,
                    actionable: true,
                    move_wallet_id: "w-ibkr",
                    move_wallet: "IBKR",
                  },
                ]
              : []),
          ]
        : [],
    },
  };
  if (likelyMoves) {
    state.txs.unshift(
      { ...mk("t201", "out", "500.00", "IBKR Cash Deposit", null), occurred_at: "2026-09-12T04:00:00Z" },
      { ...mk("t202", "in", "200.00", "FAST Transfer", null), occurred_at: "2026-09-18T04:00:00Z" },
    );
  }
  if (splitBill) {
    const bill = { ...mk("t4", "out", "30.00", "Hotpot Place", "food"), occurred_at: "2026-09-25T12:00:00Z" };
    const back = { ...mk("t5", "in", "10.00", "Wei Ming", null), notes: "Paid back" };
    const sgd = (amount: string) => ({ amount, currency: "SGD" });
    bill.split = {
      own_share: sgd("10.0000"),
      people: [
        { name: "Wei Ming", share: sgd("10.0000"), repaid: sgd("10.0000") },
        { name: "Ann", share: sgd("10.0000"), repaid: sgd("0") },
      ],
    };
    bill.links = [
      { transaction_id: "t5", counterparty: null, occurred_at: back.occurred_at, name: "Wei Ming", amount: sgd("10.0000") },
    ];
    bill.own = sgd("20.0000");
    back.links = [
      { transaction_id: "t4", counterparty: "Hotpot Place", occurred_at: bill.occurred_at, name: "Wei Ming", amount: sgd("10.0000") },
    ];
    back.own = sgd("0.0000");
    state.txs.push(bill, back);
  }
  if (twins) {
    const alert = { ...mk("t6", "out", "23.40", "Grab* A-7KXPLMQZRTWB", "transport"), notes: "Card alert" };
    const receipt = { ...mk("t7", "out", "23.40", "Grab Singapore", "transport"), notes: "Your Grab e-receipt" };
    const twin = (t: Tx) => ({ transaction_id: t.id, counterparty: t.counterparty, occurred_at: t.occurred_at, amount: t.amount });
    alert.duplicate = twin(receipt);
    receipt.duplicate = twin(alert);
    state.txs.push(alert, receipt);
  }
  if (tripMode) {
    const sgd = (amount: string) => ({ amount, currency: "SGD" });
    const base = Date.parse(new Date().toLocaleDateString("en-CA"));
    const at = (offset: number) => new Date(base + offset * 86400000).toISOString().slice(0, 10);
    const [start, day, end] = [at(-2), at(0), at(3)];
    const plan = { provider: null, segments: [], hotel: null, address: null, check_in: null, check_out: null, name: null, day: null, at: null, note: null, reference: null, booked_via: null, category: null, scheduled: true, cost: null, logged: false, manual: true };
    state.trips = [
      {
        id: "tripnow", destination: "Tokyo", start, end, days: 6, currency: "JPY", budget: sgd("2400.0000"), companions: [], set_aside: null, planned: {},
        status: "ongoing", days_until: 0, day_number: 3, notes: null, day_labels: {}, stops: [], split_evenly: true, role: "owner", owner_name: OWNER_NAME, packing: [],
      },
    ];
    state.flight = false;
    state.tripNow = { today: sgd("42.0000"), per_day_left: sgd("380.0000") };
    state.plans.push(
      { ...plan, id: "pl-stay", trip_id: "tripnow", kind: "hotel", title: "Hotel Kumo Shinjuku", starts: start, ends: end, hotel: "Hotel Kumo Shinjuku", address: "1-2-3 Shinjuku", check_in: start, check_out: end, reference: "HK4471", booked_via: "Agoda" },
      { ...plan, id: "pl-early", trip_id: "tripnow", kind: "activity", title: "Early market walk", starts: day, ends: day, name: "Early market walk", day, at: "00:01" },
      { ...plan, id: "pl-late", trip_id: "tripnow", kind: "activity", title: "Late ramen at Fuji", starts: day, ends: day, name: "Late ramen at Fuji", day, at: "23:59" },
      {
        ...plan, id: "pl-home", trip_id: "tripnow", kind: "flight", title: "ZZ13 NRT → SIN", provider: "Acme Air", starts: end, ends: end, manual: false, reference: "ZK9R2M", booked_via: "Acme Air",
        segments: [{ number: "ZZ13", origin: "NRT", destination: "SIN", departs: `${end}T18:10`, arrives: `${end}T23:55` }],
      },
    );
  }
  const categories = [
    { id: "food", name: "Dining Out" },
    { id: "transport", name: "Transport" },
    { id: "other", name: "Other" },
    { id: "income", name: "Income" },
  ];
  const wallets = [
    { id: "w-spending", name: "Spending", kind: "spending", match_words: [] as string[] },
    ...(spendingOnly
      ? []
      : [
          { id: "w-investments", name: "Investments", kind: "investment", match_words: [] as string[] },
          { id: "w-savings", name: "Savings", kind: "savings", match_words: [] as string[] },
          { id: "w-card", name: "Card", kind: "card", match_words: [] as string[] },
          ...(ibkr ? [{ id: "w-ibkr", name: "IBKR", kind: "investment", match_words: ["ibkr"] }] : []),
        ]),
  ];
  const walletRef = (w: { id: string; name: string; kind: string }): WalletRef => ({ id: w.id, name: w.name, kind: w.kind });
  if (missedMoves) {
    const target = (id: string) => walletRef(wallets.find((x) => x.id === id)!);
    const scheduled = (id: string, name: string, amount: string, wallet: string) => ({
      id,
      name,
      spending: false,
      wallet: target(wallet),
      amount: { amount, currency: "SGD" },
      cadence: "monthly",
      due: "2026-09-25",
      days_until: -3,
      snoozed: false,
    });
    state.bills.push(
      scheduled("move1", "IBKR top-up", "1000.0000", "w-ibkr"),
      scheduled("move2", "Savings top-up", "300.0000", "w-savings"),
    );
    state.missed.push({ bill: "move1", due: "2026-09-25" }, { bill: "move2", due: "2026-09-25" });
  }
  const movesOf = (walletId: string) =>
    live().filter((t) => t.direction === "move" && (t.from_wallet?.id === walletId || t.to_wallet?.id === walletId));
  /** What deleting a wallet does to its moves: re-pointed at ``into``, or dropped if they'd join it to itself. */
  const walletFold = (walletId: string, intoId: string | null) => {
    const mine = movesOf(walletId);
    const dropped = intoId ? mine.filter((t) => t.from_wallet?.id === intoId || t.to_wallet?.id === intoId) : [];
    return { mine, dropped };
  };
  const categoryName = (id: string) => categories.find((c) => c.id === id)?.name ?? id;
  const live = () => state.txs.filter((t) => !t.deleted);
  /** The made-up plan p1 as the list and its page give it now. */
  const currentPlan = () => ({
    ...PLAN_BRIEF,
    alerts: state.planAlerts,
    keep_fresh: state.planKeepFresh,
    refreshed_from: state.planRefreshed ? { id: REFRESHED_PLAN.id, created_at: REFRESHED_PLAN.created_at } : null,
  });
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = request.method();
    const body = request.postDataJSON?.() ?? null;
    if (path === "/auth/webapp" && method === "POST") {
      // Stands in for the server's signature check on the Mini App launch data.
      if (body?.init_data !== "user=%7B%22id%22%3A1%7D&hash=ok")
        return json(route, { detail: "bad signature" }, 401);
      session = true;
      return json(route, { user: { ...userBody(), role: "owner", display_name: "Sam R." }, csrf_token: "csrf-1" });
    }
    if (method !== "GET" && request.headers()["x-csrf-token"] !== "csrf-1") {
      return json(route, { detail: "missing or wrong CSRF token" }, 403);
    }
    // A guest is let into the trip routes, /me and sign-out only, like the server's TripAuth.
    const guestMay =
      path === "/config" ||
      path === "/me" ||
      path === "/auth/logout" ||
      path.startsWith("/shared/") ||
      /^\/travel\/(trips|photos|places|currency|invites)(\/|$)/.test(path) ||
      /^\/travel\/bookings\/[^/]+/.test(path);
    if (guest && session && !guestMay) {
      state.forbidden.push(`${method} ${path}`);
      return json(route, { detail: "guests can only open the trips they are on" }, 403);
    }
    if (path === "/config")
      return json(route, { bot_username: "nexus_test_bot" });
    if (path === "/me") {
      if (!session) return json(route, { detail: "not signed in" }, 401);
      return json(route, { user: userBody(), csrf_token: "csrf-1" });
    }
    if (path === "/me/timezone" && method === "POST") {
      state.zonePosts.push({ path, body });
      if (!session) return json(route, { detail: "not signed in" }, 401);
      const known = (z: unknown) => {
        try {
          return typeof z === "string" && Boolean(new Intl.DateTimeFormat("en", { timeZone: z }));
        } catch {
          return false;
        }
      };
      if (!known(body?.timezone) || !["phone", "manual"].includes(body?.source)) return json(route, { detail: "unknown time zone" }, 422);
      const recentlyChosen = zone.source === "chat" && zone.setAt !== null && Date.now() - Date.parse(zone.setAt) < 86_400_000;
      const moves = body.source === "manual" || (phoneFollows && !recentlyChosen);
      const changed = moves && body.timezone !== zone.timezone;
      if (moves) {
        zone.timezone = body.timezone;
        zone.source = body.source === "manual" ? "chat" : "phone";
        zone.setAt = new Date().toISOString();
      }
      return json(route, { user: userBody(), csrf_token: "csrf-1", changed });
    }
    if (path === "/me/timezone/home" && method === "POST") {
      state.zonePosts.push({ path, body: null });
      const changed = zone.timezone !== zone.home;
      zone.timezone = zone.home;
      zone.source = "home";
      zone.setAt = null;
      return json(route, { user: userBody(), csrf_token: "csrf-1", changed });
    }
    if (path === "/me/export" && method === "GET") {
      state.exports += 1;
      if (!session) return json(route, { detail: "not signed in" }, 401);
      if (exportLimited) return json(route, { detail: "too many exports, try again later" }, 429);
      const d = new Date();
      const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
      // Just the zip signature and an empty directory's end record: enough to look like a zip to a download.
      const empty = Buffer.from([0x50, 0x4b, 0x05, 0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
      return route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/zip",
          "content-disposition": `attachment; filename="nexus-export-${stamp}.zip"`,
        },
        body: empty,
      });
    }
    if (path === "/me/delete" && method === "POST") {
      if (!session) {
        state.deletes.push({ body, status: 401 });
        return json(route, { detail: "not signed in" }, 401);
      }
      if (body?.confirm !== "DELETE" || deleteRefused) {
        state.deletes.push({ body, status: 422 });
        return json(route, { detail: "type DELETE to confirm" }, 422);
      }
      state.deletes.push({ body, status: 204 });
      session = false;
      return route.fulfill({ status: 204 });
    }
    if (path === "/auth/logout") {
      session = false;
      return route.fulfill({ status: 204 });
    }
    const usd = (amount: string) => ({ amount, currency: "USD" });
    const position = (symbol: string, quantity: string, cost: string) => ({
      symbol,
      quantity,
      average_cost: usd(cost),
      cost: usd((Number(quantity) * Number(cost)).toFixed(4)),
      updated_at: new Date().toISOString(),
    });
    if (path === "/investments/trades" && method === "GET") return json(route, [...state.trades].reverse());
    if (path === "/investments/trades" && method === "POST") {
      const symbol = String(body.symbol).toUpperCase();
      const held = state.holdings.find((h) => h.symbol === symbol);
      const quantity = Number(body.quantity);
      let realised = null;
      if (body.side === "sell") {
        if (!held || Number(held.quantity) < quantity) return json(route, { detail: `you don't hold enough ${symbol}` }, 422);
        if (body.price) realised = usd((quantity * (Number(body.price) - Number(held.average_cost.amount))).toFixed(4));
        const left = Number(held.quantity) - quantity;
        state.holdings = left ? state.holdings.map((h) => (h.symbol === symbol ? position(symbol, String(left), held.average_cost.amount) : h)) : state.holdings.filter((h) => h.symbol !== symbol);
      }
      const trade = { id: `tr${state.trades.length + 1}`, symbol, side: body.side, quantity: String(body.quantity), price: body.price ? usd(String(body.price)) : null, traded_on: body.traded_on ?? "2026-09-28", realised };
      state.trades.push(trade);
      return json(route, trade, 201);
    }
    if (path === "/investments/dividends" && method === "GET") {
      const nvda = state.holdings.find((h) => h.symbol === "NVDA");
      return json(route, {
        received: [],
        received_home: null,
        this_year_home: null,
        expected: nvda ? [{ symbol: "NVDA", per_share: usd("0.0400"), payments: 4, net: usd((Number(nvda.quantity) * 0.04 * 0.7).toFixed(4)), yield_on_value: "0.03", yield_on_cost: "0.03" }] : [],
        expected_home: nvda ? { amount: (Number(nvda.quantity) * 0.04 * 0.7 * 1.3).toFixed(4), currency: "SGD" } : null,
      });
    }
    if (path === "/investments" && method === "GET") {
      // Made-up closes: NVDA has one, AAPL doesn't yet. 1 USD = 1.30 SGD. While the market is
      // "open" or "after_close", a stock with a quote is priced at it (see state.market).
      const closes: Record<string, [string, string]> = { NVDA: ["130.25", "128.00"] };
      const sgd = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
      let total = 0;
      let gain = 0;
      const missing: string[] = [];
      let newest: string | null = null;
      const holdings = state.holdings.map((h) => {
        const close = closes[h.symbol];
        const quote = state.market === "closed" ? undefined : state.quotes[h.symbol];
        if (!close && !quote) {
          missing.push(h.symbol);
          return { ...h, price: null, price_day: null, price_kind: null, price_at: null, value: null, gain: null, gain_percent: null, day_change: null, day_percent: null, value_home: null, earnings: null };
        }
        const price = quote ? quote.price : close[0];
        const before = quote ? quote.prev_close : close[1];
        if (quote && (!newest || quote.quoted_at > newest)) newest = quote.quoted_at;
        const value = Number(h.quantity) * Number(price);
        const up = value - Number(h.cost.amount);
        total += value * 1.3;
        gain += up * 1.3;
        return {
          ...h,
          price: usd(price),
          price_day: quote ? "2026-09-28" : "2026-09-25",
          price_kind: quote ? quoteKind() : "close",
          price_at: quote ? quote.quoted_at : null,
          value: usd(value.toFixed(4)),
          gain: usd(up.toFixed(4)),
          gain_percent: ((up / Number(h.cost.amount)) * 100).toFixed(2),
          day_change: usd((Number(h.quantity) * (Number(price) - Number(before))).toFixed(4)),
          day_percent: (((Number(price) - Number(before)) / Number(before)) * 100).toFixed(2),
          value_home: sgd(value * 1.3),
          earnings: { day: "2026-10-29", timing: "after close" },
        };
      });
      const priced = holdings.length > missing.length;
      const kinds = holdings.map((h) => h.price_kind);
      return json(route, {
        holdings,
        totals: {
          value: priced ? sgd(total) : null,
          cost: priced ? sgd(total - gain) : null,
          gain: priced ? sgd(gain) : null,
          gain_percent: priced ? ((gain / (total - gain)) * 100).toFixed(2) : null,
          day_change: null,
          day_percent: null,
          as_of: priced ? (newest ? "2026-09-28" : "2026-09-25") : null,
          as_of_at: newest,
          price_kind: kinds.includes("live") ? "live" : kinds.includes("provisional_close") ? "provisional_close" : "close",
          missing,
          realised: state.trades.some((t) => t.realised) ? sgd(1.3 * state.trades.reduce((n, t) => n + Number((t.realised as { amount: string } | null)?.amount ?? 0), 0)) : null,
          dividends: null,
          total_return: priced && state.trades.some((t) => t.realised) ? sgd(gain + 1.3 * state.trades.reduce((n, t) => n + Number((t.realised as { amount: string } | null)?.amount ?? 0), 0)) : null,
        },
        draft: state.draft,
        screenshots: true,
        prices: true,
      });
    }
    if (path === "/investments/today" && method === "GET") {
      // What moved today, from the same made-up closes and quotes as the portfolio. NVDA has a
      // headline once the market has opened; the session follows state.market.
      const closes: Record<string, [string, string]> = { NVDA: ["130.25", "128.00"] };
      const live = state.market !== "closed";
      const rows = state.holdings.flatMap((h) => {
        const quote = live ? state.quotes[h.symbol] : undefined;
        const close = closes[h.symbol];
        if (!quote && !close) return [];
        const price = quote ? quote.price : close[0];
        const before = quote ? quote.prev_close : close[1];
        const percent = ((Number(price) - Number(before)) / Number(before)) * 100;
        return [{ h, price, before, percent, quote }];
      });
      const biggest = [...rows].sort((a, b) => Math.abs(b.percent) - Math.abs(a.percent)).slice(0, 3);
      const change = rows.reduce((n, r) => n + Number(r.h.quantity) * (Number(r.price) - Number(r.before)), 0);
      const worth = rows.reduce((n, r) => n + Number(r.h.quantity) * Number(r.before), 0);
      return json(route, {
        session: state.market === "open" ? "live" : state.market === "after_close" ? "closed_today" : "previous",
        day: live ? "2026-09-28" : "2026-09-25",
        change: rows.length ? { amount: (change * 1.3).toFixed(4), currency: "SGD" } : null,
        percent: rows.length ? ((change / worth) * 100).toFixed(2) : null,
        price_kind: state.market === "open" ? "live" : state.market === "after_close" ? "provisional_close" : "close",
        as_of_at: live ? "2026-09-28T14:41:00Z" : null,
        holds: state.holdings.length > 0,
        movers: biggest.map((r) => ({
          symbol: r.h.symbol,
          held: true,
          price: Number(r.price).toFixed(2),
          day_percent: r.percent.toFixed(2),
          price_kind: r.quote ? quoteKind() : "close",
          price_at: r.quote ? r.quote.quoted_at : null,
          price_day: r.quote ? "2026-09-28" : "2026-09-25",
          headline:
            live && r.h.symbol === "NVDA"
              ? { headline: "Nvidia wins a big order", source: "Wire", url: "https://news.example/nvda/1", summary: "", published_at: "2026-09-28T14:00:00Z" }
              : null,
        })),
        prices: true,
      });
    }
    const why = path.match(/^\/investments\/today\/([A-Za-z.]+)\/why$/);
    if (why && method === "POST") {
      const symbol = why[1].toUpperCase();
      if (!state.holdings.some((h) => h.symbol === symbol) && !state.watching.includes(symbol)) {
        return json(route, { detail: `${symbol} isn't a stock you hold or watch` }, 404);
      }
      const asked = (state.whyAsked[symbol] ?? 0) + 1;
      state.whyAsked[symbol] = asked;
      return json(route, {
        symbol,
        day: "2026-09-28",
        day_percent: "0.96",
        text:
          symbol === "NVDA"
            ? "Nvidia won a big order, which may explain the rise. Chip stocks were also mostly higher."
            : `No headlines from today explain the move in ${symbol}.`,
        headlines: [],
        cached: asked > 1,
      });
    }
    if (path === "/investments/watchlist" && method === "GET") {
      return json(route, {
        stocks: state.watching.map((symbol) => {
          const quote = state.market === "closed" ? undefined : state.quotes[symbol];
          if (quote && symbol === "AMD") {
            return {
              symbol,
              price: quote.price,
              price_day: "2026-09-28",
              price_kind: quoteKind(),
              price_at: quote.quoted_at,
              day_percent: (((Number(quote.price) - Number(quote.prev_close)) / Number(quote.prev_close)) * 100).toFixed(2),
              earnings: null,
            };
          }
          return {
            symbol,
            price: symbol === "AMD" ? "129.50" : null,
            price_day: symbol === "AMD" ? "2026-09-25" : null,
            price_kind: symbol === "AMD" ? "close" : null,
            price_at: null,
            day_percent: symbol === "AMD" ? "0.39" : null,
            earnings: null,
          };
        }),
        prices: true,
        news: true,
      });
    }
    if (path === "/investments/watchlist" && method === "POST") {
      const symbol = String(body.symbol).toUpperCase();
      const added = !state.watching.includes(symbol);
      if (added) state.watching = [...state.watching, symbol].sort();
      return json(route, { added });
    }
    const unwatch = path.match(/^\/investments\/watchlist\/([A-Z.]+)$/);
    if (unwatch && method === "DELETE") {
      state.watching = state.watching.filter((s) => s !== unwatch[1]);
      return route.fulfill({ status: 204 });
    }
    const stockPage = path.match(/^\/investments\/stocks\/([A-Za-z.]+)$/);
    if (stockPage && method === "GET") {
      const symbol = stockPage[1].toUpperCase();
      return json(route, {
        symbol,
        held: null,
        watching: state.watching.includes(symbol),
        levels:
          symbol === "AMD"
            ? {
                as_of: "2026-09-25",
                close: "129.50",
                averages: { "20": "124.75", "50": "117.25" },
                trend: null,
                rsi: "71.20",
                atr: "1.80",
                atr_percent: "1.39",
                support: ["121.00", "112.40"],
                resistance: ["131.00"],
                year_high: "131.00",
                year_low: "99.00",
                days: 60,
              }
            : null,
        ranges:
          symbol === "AMD"
            ? [
                { days: 5, label: "1 week", low_68: "124.10", high_68: "135.14", low_90: "120.86", high_90: "138.76" },
                { days: 21, label: "1 month", low_68: "118.90", high_68: "141.05", low_90: "112.50", high_90: "149.07" },
                { days: 63, label: "3 months", low_68: "111.20", high_68: "150.81", low_90: "100.98", high_90: "166.08" },
              ]
            : [],
        history:
          symbol === "AMD"
            ? [
                "Change in price: 1 week +2.1%, 1 month +6.4%, 3 months +18.9%",
                "Typical daily move: 1.4% over the last month against 1.6% over the year (about usual)",
              ]
            : [],
        earnings: symbol === "AMD" ? { day: "2026-10-29", timing: "after close" } : null,
        news:
          symbol === "AMD"
            ? [{ headline: "Acme rival opens a plant", source: "Wire", url: "https://news.example/1", summary: "", published_at: "2026-09-27T09:00:00Z" }]
            : [],
        prices: true,
        news_enabled: true,
        plan: symbol === "AMD" && state.planStarted ? PLAN_BRIEF : null,
        plans_enabled: true,
        ...(symbol === "AMD" ? amdPrice() : { price: null, price_day: null, price_kind: null, price_at: null, now_vs_levels: [] }),
      });
    }
    const startPlan = path.match(/^\/investments\/stocks\/([A-Za-z.]+)\/plan$/);
    if (startPlan && method === "POST") {
      state.planStarted = true;
      return json(route, { run_id: "r9", title: `Plan for ${startPlan[1].toUpperCase()}` });
    }
    if (path === "/investments/plans/record" && method === "GET") {
      return json(route, {
        finished: 1,
        targets: 1,
        stopped: 0,
        expired: 0,
        never_entered: 0,
        average_result: "4.6",
        open: state.planStarted ? 1 : 0,
        odds_plans: 1,
        odds_said: 41,
        odds_happened: 100,
        text: "1 finished: 1 hit their target, 0 were stopped out, 0 ran out. Average result +4.6% per plan that was bought or held.",
      });
    }
    if (path === "/investments/plans" && method === "GET") {
      return json(
        route,
        state.planStarted
          ? [currentPlan(), FINISHED_PLAN, ...(state.planRefreshed ? [REFRESHED_PLAN] : [])]
          : [FINISHED_PLAN],
      );
    }
    if (path === "/investments/plans/p1/alerts" && method === "POST") {
      state.planAlerts = Boolean(body.on);
      return route.fulfill({ status: 204 });
    }
    if (path === "/investments/plans/p1/keep-fresh" && method === "PUT") {
      state.planKeepFresh = Boolean(body.on);
      return route.fulfill({ status: 204 });
    }
    if ((path === "/investments/plans/p1" || (path === "/investments/plans/p2" && state.planRefreshed)) && method === "GET") {
      const closes = Array.from({ length: 60 }, (_, i) => ({
        day: new Date(Date.UTC(2026, 6, 28 + i)).toISOString().slice(0, 10),
        close: (100 + i * 0.5).toFixed(2),
      }));
      return json(route, {
        brief: path.endsWith("/p2") ? REFRESHED_PLAN : currentPlan(),
        replaced_by: path.endsWith("/p2") ? { id: "p1", created_at: currentPlan().created_at } : null,
        closes,
        plan: {
          symbol: "AMD",
          as_of: "2026-09-25",
          close: "129.50",
          verdict: "wait",
          verdict_text: "Wait for a dip to buy",
          reason: "It's above the buy zone; support at the 20-day average is a better price.",
          entry_low: "124.75",
          entry_high: "125.65",
          entry_why: "20-day average",
          stop: "122.95",
          risk: "2.25",
          targets: [
            { price: "131.00", reward_risk: "2.67", why: "resistance" },
            { price: "132.00", reward_risk: "3", why: "3 times the risk" },
          ],
          stop_why: "a typical day's move below the 20-day average",
          trail_to: "125.20",
          average_cost: null,
          playbook: [
            { kind: "buy", title: "Buy", price: "124.75 to 125.65", detail: "Buy at 124.75 to 125.65, on a dip to the 20-day average (3.0% below today).", change: ["-3.0%"] },
            { kind: "take_profit", title: "Take profit", price: "131.00 / 132.00", detail: "Sell part at 131.00 (+1.2%, resistance), and the rest at 132.00 (+1.9%).", change: ["+1.2%", "+1.9%"] },
            { kind: "cut_loss", title: "Cut losses", price: "122.95", detail: "Sell if a day closes below 122.95 (-5.1%), a typical day's move below the 20-day average.", change: ["-5.1%"] },
            { kind: "trail", title: "After the first target", price: "125.20", detail: "Once it closes above 131.00, raise your stop to 125.20 so the rest can't turn into a loss from here.", change: [] },
            { kind: "review", title: "Valid until 12 Oct", price: null, detail: "Earnings are on 08 Oct, inside this window: prices can jump either way, so check the plan before then.", change: [] },
          ],
          valid_until: "2026-10-12",
          earnings_in_window: "2026-10-08",
          trend: null,
          held: null,
          held_gain_percent: null,
          levels: ["Close 129.50 on 25 Sep 2026", "RSI(14): 71.20"],
          technical: "A steady climb above both averages.",
          news: [{ text: "A rival opened a plant.", sources: [1] }],
          risks: ["Earnings on 08 Oct 2026."],
          bull: ["The trend is intact."],
          bear: ["It's stretched."],
          summary: "Wait for a pullback to the entry zone. The trend is up.",
          invalidation: "A daily close below 122.95.",
          sources: [{ id: 1, headline: "Acme rival opens a plant", source: "Wire", url: "https://news.example/1", published_at: "2026-09-27T09:00:00Z" }],
          odds: {
            reference: "125.20",
            stop: "122.95",
            days: 11,
            targets: [
              { price: "131.00", chance: 41, typical_days: 6 },
              { price: "132.00", chance: 35, typical_days: 7 },
            ],
            stop_first: 38,
            neither: 21,
            paths: 2000,
          },
          ranges: ["In 1 month: 118.90 to 141.05 two times in three, 112.50 to 149.07 nine times in ten"],
        },
      });
    }
    if (path === "/investments/screenshot" && method === "POST") {
      state.screenshots += 1;
      state.draft = {
        id: "d1",
        positions: [position("AAPL", "5", "190.0000"), position("NVDA", "10", "118.4000")],
        changes: [],
        first: true,
      };
      return json(route, state.draft);
    }
    const draftAction = path.match(/^\/investments\/drafts\/(\w+)\/(save|discard)$/);
    if (draftAction && method === "POST") {
      const positions = (state.draft?.positions ?? []) as typeof state.holdings;
      if (draftAction[2] === "save") state.holdings = positions;
      state.draft = null;
      return draftAction[2] === "save" ? json(route, positions) : route.fulfill({ status: 204 });
    }
    const holding = path.match(/^\/investments\/holdings\/([A-Z.]+)$/);
    if (holding && method === "PUT") {
      state.holdings = [
        ...state.holdings.filter((h) => h.symbol !== holding[1]),
        position(holding[1], body.quantity, body.average_cost),
      ].sort((a, b) => a.symbol.localeCompare(b.symbol));
      return route.fulfill({ status: 204 });
    }
    if (holding && method === "DELETE") {
      state.holdings = state.holdings.filter((h) => h.symbol !== holding[1]);
      return route.fulfill({ status: 204 });
    }
    const home = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
    if (path === "/travel/currency") {
      // Made-up lookups: a few places, and one that isn't found.
      const place = (url.searchParams.get("place") ?? "").toLowerCase();
      const known: Record<string, [string, string]> = { tokyo: ["JPY", "Japan"], osaka: ["JPY", "Japan"], japan: ["JPY", "Japan"], seoul: ["KRW", "South Korea"], bali: ["IDR", "Indonesia"] };
      const hit = Object.entries(known).find(([k]) => place.startsWith(k));
      return json(route, hit ? { currency: hit[1][0], country: hit[1][1] } : { currency: null, country: null });
    }
    // What the server refuses a member of a trip: the owner's own routes and everything about money.
    const ownerOnly = (method: string, rest: string) =>
      (method === "PUT" && rest === "") ||
      (method === "DELETE" && rest === "") ||
      /^\/(share|invites|photo|split-evenly|split|keep-mine|paid-by-others|settle|expenses)(\/|$)/.test(rest);
    const asMember = path.match(/^\/travel\/trips\/([^/]+)(\/.*)?$/);
    if (asMember && state.trips.find((t) => t.id === asMember[1])?.role === "member" && ownerOnly(method, asMember[2] ?? "")) {
      return json(route, { detail: "only the trip's owner can do that" }, 403);
    }
    if (path === "/travel/trips" && method === "GET") return json(route, state.trips);
    if (path === "/travel/photos/ph1") {
      // A 1x1 PNG stands in for the photo.
      const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
      return route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from(png, "base64") });
    }
    if (path === "/travel/trips" && method === "POST") {
      const sgdOrNull = (v: unknown) => (v ? home(Number(v)) : null);
      const trip = {
        id: `trip${state.trips.length + 1}`,
        destination: body.destination,
        start: body.start,
        end: body.end,
        days: Math.round((Date.parse(String(body.end)) - Date.parse(String(body.start))) / 86400000) + 1,
        currency: String(body.currency).toUpperCase(),
        budget: sgdOrNull(body.budget),
        companions: body.companions,
        set_aside: sgdOrNull(body.set_aside),
        planned: Object.fromEntries(Object.entries(body.planned as Record<string, string>).map(([k, v]) => [k, home(Number(v))])),
        status: Date.parse(String(body.start)) > Date.parse("2026-09-28") ? "upcoming" : "ongoing",
        days_until: Math.round((Date.parse(String(body.start)) - Date.parse("2026-09-28")) / 86400000),
        day_number: null,
        notes: body.notes ?? null,
        day_labels: {} as Record<string, string>,
        stops: [] as { name: string; start: string; end: string }[],
        split_evenly: true,
        role: "owner",
        owner_name: OWNER_NAME,
        // Made up, in the shape the photo search keeps.
        photo: {
          url: "/api/travel/photos/ph1",
          credit: "Photo: A. Photographer, CC BY-SA 4.0, via Wikimedia Commons",
          page: "https://commons.wikimedia.org/wiki/File:Example.jpg",
          licence_url: "https://creativecommons.org/licenses/by-sa/4.0",
          spot: "Example Tower",
        },
      };
      state.trips = [trip, ...state.trips];
      return json(route, trip, 201);
    }
    // A day in order, roughly as the server does it: by the plans' own order once
    // they have one, else by time (a hotel check-in at 15:00).
    const timeOf = (b: Record<string, unknown>) =>
      String(b.at ?? (b.segments as { departs: string | null }[] | undefined)?.[0]?.departs?.slice(11) ?? (b.kind === "hotel" ? "15:00" : "00:00"));
    type Leg = { origin?: string; destination?: string; departs: string | null; arrives: string | null };
    const legsOf = (b: Record<string, unknown>) => (b.segments as Leg[] | undefined) ?? [];
    // A flight on a day it only lands: shown at its landing.
    const landsOn = (b: Record<string, unknown>, day: string) =>
      (b.kind === "flight" || b.kind === "rail") && b.starts !== day && legsOf(b).some((s) => s.arrives?.slice(0, 10) === day);
    const timeOn = (b: Record<string, unknown>, day: string) => (landsOn(b, day) ? String(legsOf(b).at(-1)?.arrives?.slice(11)) : timeOf(b));
    const dayEntries = (all: Record<string, unknown>[], day: string) =>
      all
        .filter((b) => b.scheduled && (b.starts === day || landsOn(b, day)))
        .sort((a, b) => {
          if (a.order != null && b.order != null) return Number(a.order) - Number(b.order);
          return timeOn(a, day).localeCompare(timeOn(b, day));
        });
    const placesInOrder = () =>
      state.plans.filter((p) => p.kind === "activity" && !p.scheduled).sort((a, b) => Number(a.order ?? 999) - Number(b.order ?? 999));
    // Made-up notes: two plans that overlap, and a free morning before the first plan.
    const notesFor = (entries: Record<string, unknown>[], day = "") => {
      const notes: Record<string, unknown>[] = [];
      // Landing well before the hotel's check-in.
      const landed = entries.find((b) => landsOn(b, day));
      const hotel = entries.find((b) => b.kind === "hotel");
      if (landed && hotel) {
        const at = String(legsOf(landed).at(-1)?.arrives?.slice(11, 16));
        notes.push({ kind: "arrival", text: `Land ${at}, check-in at ${String(hotel.hotel)} from 15:00`, ids: [landed.id, hotel.id], start: at, end: "15:00" });
        return notes;
      }
      const plans = entries.filter((b) => b.kind === "activity" && b.at);
      for (let i = 1; i < plans.length; i += 1) {
        const [a, b] = [plans[i - 1], plans[i]];
        if (a.ends_at && String(a.ends_at) > String(b.at)) {
          notes.push({ kind: "clash", text: `${String(a.title)} (${String(a.at)} to ${String(a.ends_at)}) runs into ${String(b.title)} at ${String(b.at)}`, ids: [a.id, b.id] });
        }
      }
      const first = plans.map((p) => String(p.at)).sort()[0];
      if (first && first >= "12:00") notes.push({ kind: "free", text: `Free 09:00 to ${first}`, ids: [], start: "09:00", end: first });
      return notes;
    };
    const FLIGHT: Record<string, unknown> = {
      id: "bk1",
      trip_id: null,
      kind: "flight",
      title: "ZZ12 SIN → NRT",
      provider: "Acme Air",
      starts: "2026-11-10",
      ends: "2026-11-10",
      segments: [{ number: "ZZ12", origin: "SIN", destination: "NRT", departs: "2026-11-10T08:25", arrives: "2026-11-10T16:05" }],
      hotel: null,
      address: null,
      check_in: null,
      check_out: null,
      reference: "ZK4P7Q",
      booked_via: "Acme Air",
      category: null,
      scheduled: true,
      cost: home(820),
      logged: false,
      manual: false,
    };
    // The stops the hotels suggest, as the server works them out: a run of stays in one place
    // is a stop, named by the linked place's city, else the end of the address, else the
    // destination; the first starts with the trip and the last ends with it.
    const suggestedStops = (trip: Record<string, unknown>) => {
      const [start, end] = [String(trip.start), String(trip.end)];
      const stays = (state.plans as { kind: string; check_in: string; check_out: string | null; address?: string | null; place_id?: string | null }[])
        .filter((p) => p.kind === "hotel" && p.check_in)
        .sort((a, b) => a.check_in.localeCompare(b.check_in));
      const stops: { name: string; start: string; end: string }[] = [];
      for (const stay of stays) {
        const nextDay = new Date(Date.parse(stay.check_in) + 86400000).toISOString().slice(0, 10);
        const from = stay.check_in < start ? start : stay.check_in;
        const to = (stay.check_out ?? nextDay) > end ? end : (stay.check_out ?? nextDay);
        if (from > end || to < start) continue;
        const city = stay.place_id ? PLACES[stay.place_id]?.city : null;
        const address = (stay.address ?? "").split(",").map((part) => part.replace(/\b\S*\d\S*\b/g, "").trim()).filter(Boolean).at(-1);
        const name = String(city ?? address ?? trip.destination).slice(0, 40);
        const last = stops.at(-1);
        if (last && last.name.toLowerCase() === name.toLowerCase()) last.end = to > last.end ? to : last.end;
        else if (to > from || from > start) stops.push({ name, start: last && from < last.end ? last.end : from, end: to });
      }
      if (stops.length === 0) return [{ name: String(trip.destination).slice(0, 40), start, end }];
      stops[0].start = start;
      stops[stops.length - 1].end = end;
      return stops;
    };
    // The made-up trip's money with other people. Yen are worth 0.009 SGD; nothing else has a rate.
    const rateOf = (currency: string) => (currency === "SGD" ? 1 : currency === "JPY" ? 0.009 : null);
    const unitsOf = (currency: string) => (currency === "JPY" ? 1 : 100);
    const moneyOf = (value: number, currency: string) => ({ amount: value.toFixed(4), currency });
    const homeOf = (m: { amount: string; currency: string }) => {
      const rate = rateOf(m.currency);
      return rate === null ? null : home(Number(m.amount) * rate);
    };
    /** ``parts`` equal parts in the currency's smallest unit; the earlier ones take the leftover. */
    const allocate = (m: { amount: string; currency: string }, parts: number) => {
      const unit = unitsOf(m.currency);
      const total = Math.round(Number(m.amount) * unit);
      const base = Math.floor(total / parts);
      const extra = total - base * parts;
      return Array.from({ length: parts }, (_, i) => moneyOf((base + (i < extra ? 1 : 0)) / unit, m.currency));
    };
    const firstShare = (m: { amount: string; currency: string }, parts: number) => allocate(m, parts)[0];
    const settledWith = (trip: Record<string, unknown>, name: string) => state.settledWith.includes(`${String(trip.id)}:${name}`);
    const tripCosts = () =>
      [
        { transaction_id: "k1", day: "2026-09-28", counterparty: "Ichiran", category: "Dining Out", amount: { amount: "2000.0000", currency: "JPY" }, linked: false },
        { transaction_id: "k2", day: "2026-08-01", counterparty: "Air ticket", category: "Travel", amount: home(800), linked: true },
      ].filter((i) => state.tripItems.includes(i.transaction_id));
    const balancesFor = (trip: Record<string, unknown>) => {
      type Part = { kind: "iou" | "payment"; id: string; label: string | null; amount: { amount: string; currency: string }; home: { amount: string; currency: string } | null; on: string };
      const people = new Map<string, { owes_you: Part[]; you_owe: Part[] }>();
      const of = (name: string) => {
        if (!people.has(name)) people.set(name, { owes_you: [], you_owe: [] });
        return people.get(name)!;
      };
      const companions = (trip.companions as string[]) ?? [];
      // The dinner Ann owes for, from before this trip page learned to split.
      if (companions.includes("Ann") && !settledWith(trip, "Ann")) {
        const amount = { amount: "15000.0000", currency: "JPY" };
        of("Ann").owes_you.push({ kind: "iou", id: "iou-dinner", label: "Dinner", amount, home: homeOf(amount), on: "2026-09-20" });
      }
      for (const cost of tripCosts().filter((c) => state.splitDone.includes(c.transaction_id))) {
        // The user's share comes first, so they take the leftover; then each person in the trip's order.
        const shares = allocate(cost.amount, companions.length + 1).slice(1);
        companions.forEach((name, n) => {
          if (settledWith(trip, name)) return;
          of(name).owes_you.push({ kind: "iou", id: `iou-${cost.transaction_id}-${name}`, label: cost.counterparty, amount: shares[n], home: homeOf(shares[n]), on: cost.day });
        });
      }
      for (const p of state.paidByOthers[String(trip.id)] ?? []) {
        if (p.settled) continue;
        of(p.person).you_owe.push({ kind: "payment", id: p.id, label: p.note, amount: p.my_share, home: homeOf(p.my_share), on: p.paid_on });
      }
      return [...people.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([person, parts]) => {
          const byCurrency = new Map<string, number>();
          for (const d of parts.owes_you) byCurrency.set(d.amount.currency, (byCurrency.get(d.amount.currency) ?? 0) + Number(d.amount.amount));
          for (const d of parts.you_owe) byCurrency.set(d.amount.currency, (byCurrency.get(d.amount.currency) ?? 0) - Number(d.amount.amount));
          const all = [...parts.owes_you, ...parts.you_owe];
          const known = all.every((d) => d.home !== null);
          const net = known ? parts.owes_you.reduce((t, d) => t + Number(d.home!.amount), 0) - parts.you_owe.reduce((t, d) => t + Number(d.home!.amount), 0) : null;
          const sign = net ?? (byCurrency.size === 1 ? [...byCurrency.values()][0] : null);
          return {
            person,
            direction: sign === null ? null : sign > 0 ? "owes_you" : sign < 0 ? "you_owe" : "even",
            net: net === null ? null : home(net),
            net_by_currency: [...byCurrency.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([c, v]) => moneyOf(v, c)),
            ...parts,
          };
        });
    };
    /** What the server suggests, worked out the same way: nothing at home (SGD), else insurance, entry rules,
     * passport and money, each left out once a cover or a to-do covers it or the user said "Not needed". */
    const prepSuggestions = (trip: Record<string, unknown>) => {
      const id = String(trip.id);
      if (trip.currency === "SGD") return [];
      const todos = state.todos[id] ?? [];
      const covers = state.covers[id] ?? [];
      const mentions = (...words: string[]) => todos.some((t) => words.some((w) => t.text.toLowerCase().includes(w)));
      const country = String(trip.destination).split(",").map((part) => part.trim()).filter(Boolean).pop() ?? String(trip.destination);
      const found = [];
      if (!covers.some((c) => c.kind === "insurance")) {
        found.push({ key: "insurance", text: "Travel insurance", sub: "Medical and cancellation cover for the dates", action: "add_cover" });
      }
      if (!covers.some((c) => c.kind === "visa") && !mentions("visa", "entry rule")) {
        found.push({ key: "visa", text: `Check entry rules for ${country}`, sub: "Visas and passport validity", action: "add_todo" });
      }
      if (!mentions("passport")) {
        found.push({ key: "passport", text: "Passport valid 6 months after you're back", sub: "Many countries ask for it at the border", action: "add_todo" });
      }
      if (Number(trip.days) - 1 >= 1 && !mentions("money", "cash", "card")) {
        found.push({ key: "money", text: "Tell your bank / sort a travel card", sub: "So your card works while you're away", action: "add_todo" });
      }
      return found.filter((s) => !(state.dismissed[id] ?? []).includes(s.key));
    };
    const ownerDetail = (trip: Record<string, unknown>) => {
      const own: FakeItem[] = [
        { transaction_id: "k1", day: "2026-09-28", counterparty: "Ichiran", category: "Dining Out", amount: { amount: "2000.0000", currency: "JPY" }, home: home(18), linked: false },
        { transaction_id: "k2", day: "2026-08-01", counterparty: "Air ticket", category: "Travel", amount: home(800), home: home(800), linked: true },
      ].filter((i) => state.tripItems.includes(i.transaction_id));
      const items: FakeItem[] = [...own, ...(state.coverItems[String(trip.id)] ?? [])];
      // A cover's cost counts as booked, like a booking's, until it is logged (the home rates above; no rate: left out).
      const covers = state.covers[String(trip.id)] ?? [];
      const coverCosts = covers.flatMap((c) => (c.cost ? [{ c, home: homeOf(c.cost) }] : [])).filter((x) => x.home !== null);
      const coverBooked = coverCosts.reduce((total, x) => total + Number(x.home!.amount), 0);
      const coverUnlogged = coverCosts.filter((x) => !x.c.logged).reduce((total, x) => total + Number(x.home!.amount), 0);
      const spent = items.reduce((total, i) => total + Number(i.home?.amount ?? 0), 0);
      const budget = trip.budget as { amount: string } | null;
      return {
        trip,
        spending: {
          spent: home(spent),
          left: budget ? home(Number(budget.amount) - spent) : null,
          percent: budget ? Math.floor((spent * 100) / Number(budget.amount)) : null,
          before: home(state.tripItems.includes("k2") ? 800 : 0),
          today: state.tripNow?.today ?? null,
          per_day: null,
          per_day_left: state.tripNow?.per_day_left ?? null,
          categories: items.map((i) => ({ name: i.category, planned: null, spent: i.home })),
          unconverted: 0,
        },
        saving: {
          per_payday: trip.set_aside,
          paydays_done: 0,
          paydays_left: 2,
          saved: trip.set_aside ? home(0) : null,
          by_start: trip.set_aside ? home(Number((trip.set_aside as { amount: string }).amount) * 2) : null,
          covers_budget: trip.set_aside ? false : null,
          suggested: budget ? home(Math.ceil(Number(budget.amount) / 2)) : null,
          fits: trip.set_aside ? true : null,
          next_payday: "2026-10-30",
          pay_schedule: true,
        },
        owed: settledWith(trip, "Ann") ? [] : [{ name: "Ann", amounts: [{ amount: "15000.0000", currency: "JPY" }], home: home(135) }],
        // Costs not split yet (newest first), while the trip splits evenly and others are going.
        to_split:
          trip.split_evenly !== false && ((trip.companions as string[]) ?? []).length > 0
            ? [...tripCosts()]
                .reverse()
                .filter((c) => !state.splitDone.includes(c.transaction_id) && !(state.justMine[String(trip.id)] ?? []).includes(c.transaction_id))
                .map((c) => ({ transaction_id: c.transaction_id, day: c.day, counterparty: c.counterparty, category: c.category, amount: c.amount, home: homeOf(c.amount) }))
            : [],
        just_mine: state.justMine[String(trip.id)] ?? [],
        paid_by_others: state.paidByOthers[String(trip.id)] ?? [],
        balances: balancesFor(trip),
        items,
        bookings: [...(state.flight ? [{ ...FLIGHT, trip_id: trip.id }] : []), ...state.plans],
        booked: home(820 + coverBooked),
        booked_unlogged: home(820 + coverUnlogged),
        todos: state.todos[String(trip.id)] ?? [],
        covers,
        prep_suggestions: prepSuggestions(trip),
        ready: (() => {
          const hotels = state.plans.filter((p) => p.kind === "hotel") as { check_in: string; check_out: string }[];
          const nights: string[] = [];
          for (let t = Date.parse(String(trip.start)); t < Date.parse(String(trip.end)); t += 86400000) {
            const d = new Date(t).toISOString().slice(0, 10);
            if (!hotels.some((h) => h.check_in <= d && d < h.check_out)) nights.push(d);
          }
          const done = (nights.length ? 0 : 1) + 1 + (trip.budget ? 1 : 0);
          return { nights_without_stay: nights, has_transport: true, has_budget: Boolean(trip.budget), done, total: 3 };
        })(),
        to_spend: budget ? home(Number(budget.amount) - spent - 820 - coverUnlogged) : null,
        days: (() => {
          const all = [...(state.flight ? [FLIGHT] : []), ...state.plans];
          const landings = all.flatMap((b) => legsOf(b).map((s) => s.arrives?.slice(0, 10) ?? "")).filter(Boolean);
          const days = [...new Set([...all.filter((b) => b.scheduled).map((b) => String(b.starts)), ...landings])].sort();
          return days.map((day) => {
            const entries = dayEntries(all, day);
            return { day, order: entries.map((b) => b.id), notes: notesFor(entries, day) };
          });
        })(),
        places_order: placesInOrder().map((p) => p.id),
        suggested_stops: suggestedStops(trip),
        places: true,
        ideas: true,
        routes: state.mapKey !== null,
        map_key: state.mapKey,
      };
    };
    /** A trip with `role: "member"` (one the signed-in user was added to) is served as the server serves it
     * to a member: the plan, with no budget, spending, set-aside, costs or who owes what. */
    const tripDetail = (trip: Record<string, unknown>) => {
      const full = ownerDetail(trip);
      if (trip.role !== "member") return full;
      return {
        ...full,
        trip: { ...trip, budget: null, set_aside: null, planned: {} },
        bookings: (full.bookings as Record<string, unknown>[]).map((b) => ({ ...b, cost: null, logged: false })),
        covers: (full.covers as FakeCover[]).map((c) => ({ ...c, cost: null, logged: false })),
        booked: null,
        booked_unlogged: null,
        to_spend: null,
        spending: null,
        saving: null,
        owed: [],
        to_split: [],
        just_mine: [],
        paid_by_others: [],
        balances: [],
        items: [],
        ready: { ...full.ready, has_budget: false },
      };
    };
    // Made-up Google Maps places: names, ratings and reviews are all invented.
    const PLACES: Record<string, Record<string, unknown> & { closed: number | null }> = {
      fakePlaceNoodle01: {
        id: "fakePlaceNoodle01", name: "Hanok Noodle Bar", address: "12 Example-ro, Jung-gu, Seoul", kind: "Noodle shop",
        rating: "4.6", ratings: 2310, price: "Moderate", maps_url: "https://maps.example/noodle", website: null, phone: null,
        summary: "Hand-pulled noodles in a small wooden room.", status: "OPERATIONAL",
        hours: ["Monday: 11:00 AM to 9:00 PM", "Thursday: Closed"],
        reviews: [{ rating: 5, text: "The broth is worth the queue.", author: "A. Reviewer", author_url: "https://maps.example/u/1", when: "a month ago" }],
        photo_url: "/api/travel/places/fakePlaceNoodle01/photo", photo_author: "A. Photographer", photo_author_url: "https://maps.example/u/2",
        lat: 37.5651, lng: 126.9895, area: "Jung-gu", city: "Seoul",
        closed: 4,
      },
      fakePlaceMarket01: {
        id: "fakePlaceMarket01", name: "Namdaemun Market", address: "21 Example-gil, Jung-gu, Seoul", kind: "Market",
        rating: "4.3", ratings: 18000, price: null, maps_url: "https://maps.example/market", website: null, phone: null,
        summary: null, status: "OPERATIONAL", hours: [], reviews: [], lat: 37.5592, lng: 126.9776, area: "Jung-gu", city: "Seoul", closed: null,
      },
    };
    PLACES.fakePlaceLodge001 = {
      id: "fakePlaceLodge001", name: "Hill Lodge", address: "3 Example Cove", kind: "Hotel", rating: "4.5", ratings: 1576, price: null,
      maps_url: "https://maps.example/lodge", website: null, phone: null, summary: null, status: "OPERATIONAL", hours: [], reviews: [],
      lat: 41.93, lng: 3.21, area: "Example Cove", city: "Exampleton", closed: null,
    };
    PLACES.fakePlaceAirport1 = {
      id: "fakePlaceAirport1", name: "Exampleton Airport", address: "Exampleton", kind: "International airport", rating: null, ratings: null,
      price: null, maps_url: "https://maps.example/airport", website: null, phone: null, summary: null, status: "OPERATIONAL", hours: [],
      reviews: [], lat: 41.29, lng: 2.07, area: null, city: "Exampleton", closed: null,
    };
    // Made-up places in two Japanese cities, for stops and day areas. They never turn up in a
    // search (``unlisted``), so they only appear when a test links them to a plan.
    const japan = (id: string, name: string, kind: string, area: string, city: string, lat: number, lng: number) => {
      PLACES[id] = {
        id, name, address: `1 Example-dori, ${area}, ${city}`, kind, rating: "4.4", ratings: 900, price: null, maps_url: `https://maps.example/${id}`,
        website: null, phone: null, summary: null, status: "OPERATIONAL", hours: [], reviews: [], lat, lng, area, city, closed: null, unlisted: true,
      };
    };
    japan("fakePlaceTokyoInn1", "Hotel Kumo Shinjuku", "Hotel", "Shinjuku", "Tokyo", 35.6896, 139.7006);
    japan("fakePlaceKyotoInn1", "Machiya Inn Higashiyama", "Inn", "Higashiyama", "Kyoto", 35.0036, 135.7785);
    japan("fakePlaceTokyoShr1", "Lantern Shrine", "Shinto shrine", "Asakusa", "Tokyo", 35.7148, 139.7967);
    japan("fakePlaceTokyoRmn1", "Counter Ramen Ichi", "Ramen restaurant", "Asakusa", "Tokyo", 35.7121, 139.7961);
    japan("fakePlaceTokyoMus1", "Paper Crane Museum", "Museum", "Ueno", "Tokyo", 35.7189, 139.7745);
    japan("fakePlaceKyotoTmp1", "Moss Garden Temple", "Buddhist temple", "Gion", "Kyoto", 35.0037, 135.7788);
    japan("fakePlaceKyotoTea1", "Kettle Tea House", "Tea house", "Gion", "Kyoto", 35.0049, 135.7752);
    japan("fakePlaceKyotoBmb1", "Bamboo Walk", "Park", "Arashiyama", "Kyoto", 35.0170, 135.6713);
    const placeOut = ({ closed: _closed, unlisted: _unlisted, ...place }: Record<string, unknown>) => place;
    // Where a search looks, as the server works it out: ``stop`` must be one of the trip's stops
    // (as set, else as the hotels suggest) and ``day`` inside the trip; both need a trip.
    const scopeOf = (tripId: string | null, stop: string | null, day: string | null) => {
      if (!stop && !day) return { place: null as string | null };
      if (!tripId) return { error: json(route, { detail: "a stop or a day needs a trip_id" }, 422) };
      const trip = state.trips.find((t) => t.id === tripId);
      if (!trip) return { error: json(route, { detail: "no trip with that id" }, 404) };
      const stops = ((trip.stops as { name: string; start: string; end: string }[] | undefined)?.length
        ? (trip.stops as { name: string; start: string; end: string }[])
        : suggestedStops(trip));
      const named = stop ? stops.find((s) => s.name.toLowerCase() === stop.trim().replace(/\s+/g, " ").toLowerCase()) : undefined;
      if (stop && !named) {
        return { error: json(route, { detail: `'${stop}' isn't one of the trip's stops (${stops.map((s) => s.name).join(", ")})` }, 422) };
      }
      if (day && (day < String(trip.start) || day > String(trip.end))) {
        return { error: json(route, { detail: "that day is outside the trip" }, 422) };
      }
      if (day && named && (day < named.start || day > named.end)) {
        return { error: json(route, { detail: `that day isn't in ${named.name}` }, 422) };
      }
      const there = named ?? stops.filter((s) => day && s.start <= day && day <= s.end).at(-1);
      return { place: there?.name ?? String(trip.destination) };
    };
    if (path === "/travel/places/search" && method === "GET") {
      const [q, tripId] = [url.searchParams.get("q") ?? "", url.searchParams.get("trip_id")];
      const [stop, day] = [url.searchParams.get("stop"), url.searchParams.get("day")];
      const scope = scopeOf(tripId, stop, day);
      if ("error" in scope) return scope.error;
      state.placeSearches.push(q);
      state.placeScopes.push({ q, trip_id: tripId, stop, day });
      return json(route, Object.values(PLACES).filter((p) => !p.unlisted).map(placeOut));
    }
    // Made-up ideas from made-up articles: one matched to Google Maps, one not.
    const tripIdeas = path.match(/^\/travel\/trips\/([^/]+)\/ideas$/);
    if (tripIdeas && method === "GET") {
      const q = url.searchParams.get("q") ?? "";
      const [stop, day] = [url.searchParams.get("stop"), url.searchParams.get("day")];
      const scope = scopeOf(tripIdeas[1], stop, day);
      if ("error" in scope) return scope.error;
      state.ideaSearches.push(q);
      state.ideaScopes.push({ q, stop, day });
      const trip = state.trips.find((t) => t.id === tripIdeas[1]);
      return json(route, {
        query: q,
        destination: scope.place ?? trip?.destination ?? "",
        ideas: [
          {
            name: "Hanok Noodle Bar", area: "Jung-gu", kind: "Food", why: "Hand-pulled noodles worth the queue.",
            source: { url: "https://food.example.com/seoul-noodles", title: "Seoul's best noodles" },
            place: placeOut(PLACES.fakePlaceNoodle01),
          },
          {
            name: "Lantern Alley", area: "Euljiro", kind: "Nightlife", why: "Tiny bars down a lantern-lit lane.",
            source: { url: "https://en.wikivoyage.org/wiki/Seoul", title: "Wikivoyage: Seoul" },
            place: null,
          },
        ],
      });
    }
    const tripPlaces = path.match(/^\/travel\/trips\/([^/]+)\/places$/);
    if (tripPlaces && method === "GET") {
      const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      return json(
        route,
        state.plans
          .filter((p) => p.place_id && PLACES[String(p.place_id)])
          .map((p) => {
            const place = PLACES[String(p.place_id)];
            const weekday = p.day ? new Date(`${String(p.day)}T00:00:00Z`).getUTCDay() : null;
            const warning = weekday !== null && weekday === place.closed ? `Usually closed on ${days[weekday]}s` : null;
            return { booking_id: p.id, place: placeOut(place), warning };
          })
          .concat(
            // Airports found for flights: on the days they're landed at.
            state.plans.flatMap((p) =>
              Object.entries((p.stations as Record<string, string> | undefined) ?? {})
                .filter(([, pid]) => PLACES[pid])
                .map(([station, pid]) => ({
                  booking_id: p.id, place: placeOut(PLACES[pid]), warning: null, station,
                  stops: legsOf(p).filter((s) => `${s.destination} airport` === station).map((s) => ({ day: String(s.arrives).slice(0, 10), side: "to" })),
                })),
            ),
          ),
      );
    }
    // Made-up travel times: a 14-minute walk between each pair of a day's linked plans;
    // public transport takes 25 minutes, which is tight for plans 20 minutes apart.
    const dayHops = path.match(/^\/travel\/trips\/([^/]+)\/days\/([\d-]+)\/hops(?:\/([^/]+)\/([^/]+))?$/);
    if (dayHops && method === "GET") {
      const stops = state.plans
        .filter((p) => p.place_id && p.day === dayHops[2])
        .sort((a, b) => String(a.at ?? "").localeCompare(String(b.at ?? "")));
      // Like the server's: a plan with no place breaks the chain, so there is no time on either side of it.
      const order = state.plans.filter((p) => p.day === dayHops[2]).sort((a, b) => String(a.at ?? "").localeCompare(String(b.at ?? "")));
      const hops = order.slice(1).flatMap((end, n) => {
        const start = order[n];
        if (!start.place_id || !end.place_id) return [];
        return [{
          start_id: start.id, end_id: end.id, start: start.title, end: end.title, mode: "walk", minutes: 14, metres: 944, tight: false,
          directions: `https://www.google.com/maps/dir/?api=1&origin_place_id=${String(start.place_id)}&destination_place_id=${String(end.place_id)}`,
        }];
      });
      // From the airport a flight lands at to the hotel checked into that day: a long
      // way, 2 h 20 min by public transport or 1 h 30 min by car.
      const trip = state.trips.find((t) => t.id === dayHops[1]);
      const landed = state.plans.find((p) => landsOn(p, dayHops[2]) && Object.values((p.stations as Record<string, string> | undefined) ?? {}).some(Boolean));
      const lodge = state.plans.find((p) => p.kind === "hotel" && p.check_in === dayHops[2] && p.place_id);
      if (landed && lodge) {
        const car = trip?.getting_around === "car";
        hops.unshift({
          start_id: String(landed.id), end_id: String(lodge.id), start: `${String(legsOf(landed).at(-1)?.destination)} airport`, end: String(lodge.hotel),
          mode: car ? "drive" : "transit", minutes: car ? 90 : 140, metres: 120000, tight: false,
          directions: `https://www.google.com/maps/dir/?api=1&destination_place_id=${String(lodge.place_id)}`,
        });
      }
      if (state.backToHotel && lodge && stops.length > 0) {
        const leg = (a: Record<string, unknown>, b: Record<string, unknown>) => ({
          start_id: String(a.id), end_id: String(b.id), start: String(a.title), end: String(b.title), mode: "transit", minutes: 20, metres: 3100, tight: false,
          directions: "https://www.google.com/maps/dir/?api=1",
        });
        const hotel = { id: lodge.id, title: lodge.hotel };
        hops.unshift(leg(hotel, stops[0]));
        hops.push(leg(stops.at(-1)!, hotel));
      }
      if (!dayHops[3]) return json(route, hops);
      const mode = url.searchParams.get("mode") ?? "walk";
      state.hopModes.push(mode);
      const hop = hops.find((h) => h.start_id === dayHops[3] && h.end_id === dayHops[4]);
      if (!hop) return json(route, { detail: "those two aren't one after the other that day" }, 404);
      const minutes = mode === "transit" ? 25 : mode === "drive" ? 12 : 14;
      return json(route, { ...hop, mode, minutes, metres: mode === "walk" ? 944 : 2100, tight: minutes > 20 });
    }
    const planMove = path.match(/^\/travel\/bookings\/([^/]+)\/move$/);
    if (planMove && method === "PUT") {
      const moving = state.plans.find((p) => p.id === planMove[1]);
      if (!moving || moving.kind !== "activity") return json(route, { detail: "flights, trains and hotel nights stay where their booking is" }, 422);
      const day = (body.day as string | null) ?? null;
      state.moves.push(`${String(moving.id)}>${day ?? "places"}@${String(body.after ?? "first")}`);
      const others = [...(state.flight ? [FLIGHT] : []), ...state.plans.filter((p) => p !== moving)];
      const there = day ? dayEntries(others, day) : placesInOrder().filter((p) => p !== moving);
      const at = body.after ? there.findIndex((b) => b.id === body.after) + 1 : 0;
      if (body.after && at === 0) return json(route, { detail: "that entry isn't on that day" }, 404);
      const placed: Record<string, unknown> = { ...moving, day, scheduled: Boolean(day), starts: day ?? "2026-09-28" };
      const plans = [...there.slice(0, at), placed, ...there.slice(at)].filter((b) => b.kind === "activity");
      state.plans = state.plans.map((p) => {
        const n = plans.findIndex((b) => b.id === p.id);
        return n < 0 ? p : { ...(p === moving ? placed : p), order: n };
      });
      return json(route, state.plans.find((p) => p.id === moving.id));
    }
    const placeLink = path.match(/^\/travel\/bookings\/([^/]+)\/place$/);
    if (placeLink && method === "PUT") {
      // Linking a place lets the user's own pin go: the place has its own position.
      state.plans = state.plans.map((p) =>
        p.id === placeLink[1] ? { ...p, place_id: body.place_id ?? null, ...(body.place_id ? { lat: null, lng: null } : {}) } : p,
      );
      return json(route, state.plans.find((p) => p.id === placeLink[1]));
    }
    if (path === "/travel/bookings" && method === "GET") return json(route, state.looseBookings);
    const bookingTrip = path.match(/^\/travel\/bookings\/([^/]+)\/trip$/);
    if (bookingTrip && method === "PUT") {
      state.movedBookings.push(`${bookingTrip[1]}:${String(body.trip_id)}`);
      state.looseBookings = state.looseBookings.filter((b) => b.id !== bookingTrip[1]);
      return route.fulfill({ status: 204 });
    }
    if (path === "/travel/next" && method === "GET") {
      const next = state.trips.find((t) => t.status !== "finished");
      return json(route, next ? tripDetail(next) : null);
    }
    // A 1x1 PNG stands in for any photo.
    const png = () => Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
    if (/^\/travel\/places\/[^/]+\/photo$/.test(path)) return route.fulfill({ status: 200, contentType: "image/png", body: png() });
    const tripWeather = path.match(/^\/travel\/trips\/([^/]+)\/weather$/);
    if (tripWeather) {
      const trip = state.trips.find((t) => t.id === tripWeather[1]);
      if (!trip) return json(route, null);
      const start = Date.parse(String(trip.start));
      const days = Array.from({ length: Math.min(Number(trip.days), 5) }, (_, i) => ({
        day: new Date(start + i * 86400000).toISOString().slice(0, 10),
        high: 18 + i, low: 9, rain: i === 1 ? 70 : 10, summary: i === 1 ? "Light rain" : "Clear", code: i === 1 ? 61 : 0,
      }));
      return json(route, { place: `${String(trip.destination)}, Exampleland`, kind: "typical", years: 3, days });
    }
    // The Prep tab: to-dos, "Not needed" and cover and documents, as the server answers them. A trip the
    // user was added to (`role: "member"`) sees covers without a cost and can't set or log one.
    const tripPrep = path.match(/^\/travel\/trips\/([^/]+)\/(todos|prep\/dismiss|covers)(?:\/([^/]+))?(\/log)?$/);
    if (tripPrep) {
      const trip = state.trips.find((t) => t.id === tripPrep[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      const id = String(trip.id);
      const [, , what, other, log] = tripPrep;
      state.prepRequests.push({ request: `${method} ${path}`, body });
      const member = trip.role === "member";
      const seen = (c: FakeCover) => (member ? { ...c, cost: null, logged: false } : c);
      const prep = () => ({ todos: state.todos[id] ?? [], covers: (state.covers[id] ?? []).map(seen), prep_suggestions: prepSuggestions(trip) });
      const noteShared = (summary: string) => {
        if ((state.members[id] ?? []).length > 0 || member) {
          state.activity[id] = [{ actor: OWNER_NAME, summary, at: "2026-09-28T03:00:00Z" }, ...(state.activity[id] ?? [])];
        }
      };
      if (what === "todos" && method === "PUT") {
        const given = (body.todos as { id?: string | null; text: string; due?: string | null; done?: boolean }[]) ?? [];
        if (given.length > 50 || given.some((t) => t.text.length > 80)) return json(route, { detail: "keep at most 50 things on the to-do list" }, 422);
        const seenText = new Set<string>();
        const kept: FakeTodo[] = [];
        for (const t of given) {
          const text = t.text.split(/\s+/).filter(Boolean).join(" ");
          if (!text || seenText.has(text.toLowerCase())) continue;
          seenText.add(text.toLowerCase());
          const taken = kept.some((k) => k.id === t.id);
          kept.push({ id: t.id && !taken ? t.id : `todo${++coverCount}`, text, due: t.due ?? null, done: Boolean(t.done) });
        }
        state.todos[id] = kept;
        noteShared("changed the to-do list");
        return json(route, prep());
      }
      if (what === "prep/dismiss") {
        const key = method === "POST" ? String(body.key) : String(other);
        if (!["insurance", "visa", "passport", "money"].includes(key)) return json(route, { detail: `there's no suggestion called '${key}'` }, 422);
        const rest = (state.dismissed[id] ?? []).filter((k) => k !== key);
        state.dismissed[id] = method === "POST" ? [...rest, key] : rest;
        noteShared(method === "POST" ? "marked a prep suggestion as not needed" : "brought back a prep suggestion");
        return json(route, prep());
      }
      const list = state.covers[id] ?? [];
      const asCover = (b: Record<string, unknown>, keep?: FakeCover): FakeCover | string => {
        const name = String(b.name ?? "").split(/\s+/).filter(Boolean).join(" ");
        if (!name) return "a cover needs a name";
        if (/passport/i.test(name) && b.reference) return "a passport's number isn't kept; leave the reference out";
        if (/\b(?:\d[ -]?){15,16}\b/.test(String(b.reference ?? ""))) return "a reference can't hold a card or passport number; leave it out";
        if (b.phone && !/^[0-9+()\- ]+$/.test(String(b.phone))) return "a phone number can only have digits, +, spaces, - and brackets";
        if (b.starts && b.ends && String(b.ends) < String(b.starts)) return "a cover can't end before it starts";
        const cost = member ? (keep?.cost ?? null) : b.cost ? moneyOf(Number(String(b.cost).replace(/,/g, "")), String(b.currency ?? "SGD").toUpperCase()) : null;
        return {
          id: keep?.id ?? `cover${++coverCount}`,
          kind: String(b.kind),
          name,
          reference: b.reference ? String(b.reference).trim() : null,
          phone: b.phone ? String(b.phone).trim() : null,
          starts: (b.starts as string | null) ?? null,
          ends: (b.ends as string | null) ?? null,
          cost,
          logged: keep?.logged ?? false,
          note: b.note ? String(b.note).trim() : null,
        };
      };
      if (what === "covers" && !other && method === "POST") {
        if (member && (body.cost || body.currency)) return json(route, { detail: "only the trip's owner can do that" }, 403);
        if (list.length >= 30) return json(route, { detail: "a trip keeps at most 30 covers and documents" }, 422);
        const made = asCover(body);
        if (typeof made === "string") return json(route, { detail: made }, 422);
        state.covers[id] = [...list, made];
        noteShared(`added ${made.name} to cover and documents`);
        return json(route, seen(made), 201);
      }
      const found = list.find((c) => c.id === other);
      if (what === "covers" && other && !found) return json(route, { detail: "no cover with that id" }, 404);
      if (what === "covers" && found && log && method === "POST") {
        if (member) return json(route, { detail: "only the trip's owner can do that" }, 403);
        if (!found.cost) return json(route, { detail: "this cover has no cost to log" }, 422);
        if (found.logged) return json(route, { detail: "this cost is already logged as an expense" }, 409);
        found.logged = true;
        state.coverItems[id] = [
          ...(state.coverItems[id] ?? []),
          { transaction_id: `cv-${found.id}`, day: "2026-09-28", counterparty: found.name, category: "Travel", amount: found.cost, home: homeOf(found.cost), linked: true },
        ];
        return json(route, found);
      }
      if (what === "covers" && found && method === "PUT") {
        if (member && (body.cost || body.currency)) return json(route, { detail: "only the trip's owner can do that" }, 403);
        const changed = asCover(body, found);
        if (typeof changed === "string") return json(route, { detail: changed }, 422);
        state.covers[id] = list.map((c) => (c === found ? changed : c));
        noteShared(`changed ${changed.name} in cover and documents`);
        return json(route, seen(changed));
      }
      if (what === "covers" && found && method === "DELETE") {
        state.covers[id] = list.filter((c) => c !== found);
        noteShared(`removed ${found.name} from cover and documents`);
        return route.fulfill({ status: 204 });
      }
    }
    const tripPacking = path.match(/^\/travel\/trips\/([^/]+)\/packing(\/suggest)?$/);
    if (tripPacking) {
      const trip = state.trips.find((t) => t.id === tripPacking[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      const have = (trip.packing as { text: string; done: boolean }[] | undefined) ?? [];
      if (tripPacking[2]) {
        const wanted = ["Passport", "Travel adapter", "Umbrella or rain jacket"].filter((t) => !have.some((h) => h.text === t));
        trip.packing = [...have, ...wanted.map((text) => ({ text, done: false }))];
      } else trip.packing = body.items;
      return json(route, trip);
    }
    const tripPhoto = path.match(/^\/travel\/trips\/([^/]+)\/photo$/);
    if (tripPhoto && method === "POST") {
      const trip = state.trips.find((t) => t.id === tripPhoto[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      state.photoChoices.push(String(body.choice));
      if (body.choice === "next") return json(route, { detail: "there's no other photo of this place yet" }, 422);
      trip.photo_off = body.choice === "off";
      return json(route, trip);
    }
    const gettingAround = path.match(/^\/travel\/trips\/([^/]+)\/getting-around$/);
    if (gettingAround && method === "PUT") {
      const trip = state.trips.find((t) => t.id === gettingAround[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      trip.getting_around = body.by;
      return json(route, trip);
    }
    const tripStops = path.match(/^\/travel\/trips\/([^/]+)\/stops$/);
    if (tripStops && method === "PUT") {
      const trip = state.trips.find((t) => t.id === tripStops[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      const stops = ((body.stops ?? []) as { name: string; start: string; end: string }[])
        .map((stop) => ({ name: String(stop.name).trim().replace(/\s+/g, " "), start: stop.start, end: stop.end }))
        .sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
      // The server's rules: 1-40 characters, inside the trip, in order, only a travel day shared, at most 10.
      const problem =
        stops.length > 10 ? "at most 10 stops on a trip"
        : stops.find((s) => s.name.length < 1 || s.name.length > 40) ? "a stop needs a name of 1 to 40 characters"
        : stops.find((s) => s.end < s.start) ? "a stop ends before it starts"
        : stops.find((s) => s.start < String(trip.start) || s.end > String(trip.end)) ? "a stop is outside the trip's dates"
        : stops.find((s, n) => n > 0 && (s.start < stops[n - 1].end || s.start === stops[n - 1].start)) ? "two stops overlap"
        : null;
      if (problem) return json(route, { detail: problem }, 422);
      state.stopPuts.push(stops);
      trip.stops = stops;
      return json(route, trip);
    }
    const dayLabel = path.match(/^\/travel\/trips\/([^/]+)\/days\/([0-9-]+)$/);
    if (dayLabel && method === "PUT") {
      const trip = state.trips.find((t) => t.id === dayLabel[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      const labels = { ...(trip.day_labels as Record<string, string>) };
      if (body.label) labels[dayLabel[2]] = String(body.label);
      else delete labels[dayLabel[2]];
      trip.day_labels = labels;
      return json(route, trip);
    }
    const tripMatch = path.match(/^\/travel\/trips\/([^/]+)$/);
    if (tripMatch) {
      const trip = state.trips.find((t) => t.id === tripMatch[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      if (method === "GET") return json(route, tripDetail(trip));
      if (method === "PUT") {
        // The whole trip body, as the trip form and the tabs send it: notes, planned costs and the rest.
        state.tripPuts.push(body);
        const money = (v: unknown) => (v ? home(Number(v)) : null);
        const start = String(body.start ?? trip.start);
        const end = String(body.end ?? trip.end);
        Object.assign(trip, {
          destination: body.destination ?? trip.destination,
          start,
          end,
          days: Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1,
          currency: String(body.currency ?? trip.currency).toUpperCase(),
          budget: money(body.budget),
          companions: body.companions ?? trip.companions,
          set_aside: money(body.set_aside),
          planned: Object.fromEntries(Object.entries((body.planned ?? {}) as Record<string, string>).map(([k, v]) => [k, home(Number(v))])),
          notes: body.notes ?? null,
        });
        // Stops that no longer fit the dates go back to following the hotels.
        const stops = (trip.stops ?? []) as { start: string; end: string }[];
        if (stops.some((s) => s.start < start || s.end > end)) trip.stops = [];
        return json(route, trip);
      }
      if (method === "DELETE") {
        state.trips = state.trips.filter((t) => t !== trip);
        return route.fulfill({ status: 204 });
      }
    }
    // Splitting costs, what others paid and settling up, as the server answers them.
    const tripMoney = path.match(/^\/travel\/trips\/([^/]+)\/(split-evenly|split|keep-mine|paid-by-others|settle)(?:\/([^/]+))?$/);
    if (tripMoney) {
      const trip = state.trips.find((t) => t.id === tripMoney[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      const id = String(trip.id);
      const companions = (trip.companions as string[]) ?? [];
      const traveller = (name: unknown) => companions.find((c) => c.toLowerCase() === String(name ?? "").trim().toLowerCase());
      if (tripMoney[2] === "split-evenly" && method === "PUT") {
        if (typeof body.on !== "boolean") return json(route, { detail: "on: Input should be a valid boolean" }, 422);
        trip.split_evenly = body.on;
        return json(route, trip);
      }
      if (tripMoney[2] === "keep-mine" && method === "POST") {
        state.keepMinePosts.push(body);
        const ids = (body.transaction_ids ?? []) as string[];
        if (ids.length === 0) return json(route, { detail: "transaction_ids: List should have at least 1 item" }, 422);
        if (ids.some((i) => !tripCosts().some((c) => c.transaction_id === i))) return json(route, { detail: "no expense with that id on this trip" }, 404);
        const kept = (state.justMine[id] ?? []).filter((i) => body.keep === false ? !ids.includes(i) : true);
        state.justMine[id] = body.keep === false ? kept : [...kept, ...ids.filter((i) => !kept.includes(i))];
        return json(route, { just_mine: state.justMine[id] });
      }
      if (tripMoney[2] === "split" && method === "POST") {
        state.splitPosts.push(body);
        const ids = body.transaction_ids as string[] | undefined;
        if ((ids === undefined || ids === null) === !body.all || (ids && ids.length === 0)) return json(route, { detail: "give transaction_ids, or all: true, but not both" }, 422);
        if (companions.length === 0) return json(route, { detail: "add the people you're travelling with to the trip first" }, 422);
        const costs = tripCosts();
        const wanted = body.all ? costs.filter((c) => !state.splitDone.includes(c.transaction_id) && !(state.justMine[id] ?? []).includes(c.transaction_id)).map((c) => c.transaction_id) : ids!;
        const done: Record<string, unknown>[] = [];
        const skipped: { transaction_id: string; reason: string }[] = [];
        for (const tid of wanted) {
          const cost = costs.find((c) => c.transaction_id === tid);
          if (!cost) skipped.push({ transaction_id: tid, reason: "not an expense on this trip" });
          else if (state.splitDone.includes(tid)) skipped.push({ transaction_id: tid, reason: "this bill is already split" });
          else {
            state.splitDone.push(tid);
            state.justMine[id] = (state.justMine[id] ?? []).filter((i) => i !== tid);
            done.push({ transaction_id: tid, counterparty: cost.counterparty, amount: cost.amount, own_share: firstShare(cost.amount, companions.length + 1) });
          }
        }
        return json(route, { with_people: companions, done, skipped });
      }
      if (tripMoney[2] === "paid-by-others" && (method === "POST" || method === "PUT" || method === "DELETE")) {
        const list = state.paidByOthers[id] ?? (state.paidByOthers[id] = []);
        const found = tripMoney[3] ? list.find((p) => p.id === tripMoney[3]) : undefined;
        if (method !== "POST" && !found) return json(route, { detail: "no payment with that id on this trip" }, 404);
        if (method === "DELETE") {
          state.paidByOthers[id] = list.filter((p) => p !== found);
          return route.fulfill({ status: 204 });
        }
        if (found?.settled) return json(route, { detail: "this payment is already settled" }, 409);
        const person = traveller(body.person);
        if (!person) return json(route, { detail: `${String(body.person ?? "").trim()} isn't on this trip; add them to the trip's travellers first` }, 422);
        const currency = String(body.currency ?? "SGD").toUpperCase();
        const value = Number(String(body.amount ?? "").replace(/,/g, ""));
        if (!(value > 0)) return json(route, { detail: "amount must be greater than zero" }, 422);
        const others = body.split_with === undefined || body.split_with === null ? companions : (body.split_with as string[]).map((n) => traveller(n));
        if (others.some((n) => !n)) return json(route, { detail: "someone in split_with isn't on this trip" }, 422);
        const split_with = [...new Set(others as string[])].filter((n) => n !== person);
        const amount = moneyOf(value, currency);
        const payment: FakePayment = {
          id: found?.id ?? `pay${list.length + 1}`,
          person,
          amount,
          note: body.note ? String(body.note).trim() : null,
          paid_on: String(body.paid_on ?? "2026-09-28"),
          split_with,
          my_share: firstShare(amount, 2 + split_with.length),
          settled: false,
          settled_at: null,
        };
        if (found) Object.assign(found, payment);
        else list.push(payment);
        return json(route, payment, method === "POST" ? 201 : 200);
      }
      if (tripMoney[2] === "settle" && method === "POST") {
        state.settlePosts.push(body);
        const person = traveller(body.person) ?? String(body.person ?? "");
        const balance = balancesFor(trip).find((b) => b.person.toLowerCase() === person.toLowerCase());
        if (!balance) return json(route, { detail: `nothing to settle with ${person} on this trip` }, 422);
        state.settledWith.push(`${id}:${balance.person}`);
        for (const p of state.paidByOthers[id] ?? []) if (p.person === balance.person) Object.assign(p, { settled: true, settled_at: "2026-09-28T04:00:00Z" });
        return json(route, {
          person: balance.person,
          ious_repaid: balance.owes_you.length,
          payments_settled: balance.you_owe.length,
          income: balance.owes_you.map((d) => d.amount),
          expenses: body.log === false ? [] : balance.you_owe.map((d) => d.amount),
        });
      }
    }
    // A trip's read-only link. Tokens are made up, in the real ones' shape.
    const tripShare = path.match(/^\/travel\/trips\/([^/]+)\/share$/);
    if (tripShare) {
      const id = tripShare[1];
      if (!state.trips.some((t) => t.id === id)) return json(route, { detail: "no trip with that id" }, 404);
      if (method === "DELETE") {
        delete state.shares[id];
        delete state.shareBookings[id];
        return route.fulfill({ status: 204 });
      }
      if (method === "POST" && body.show_bookings !== undefined && body.show_bookings !== null && typeof body.show_bookings !== "boolean") {
        return json(route, { detail: "show_bookings: Input should be a valid boolean" }, 422);
      }
      if (method === "POST" && (!state.shares[id] || body.renew)) {
        state.shareCount += 1;
        state.shares[id] = `fakeShare${String(state.shareCount).padStart(4, "0")}`.padEnd(43, "x");
        // A new link starts with bookings shown; a renewed one keeps the choice.
        if (!body.renew) state.shareBookings[id] = true;
      }
      // Left out, the link keeps what it had.
      if (method === "POST" && typeof body.show_bookings === "boolean") state.shareBookings[id] = body.show_bookings;
      return json(route, { token: state.shares[id] ?? null, show_bookings: state.shareBookings[id] ?? true });
    }
    // Shared trips: members, invites, activity and the notes. The fake user owns every trip
    // it makes, so it sees what an owner does; a test fills `members`/`activity` to show more.
    const sharedTrip = path.match(/^\/travel\/trips\/([^/]+)\/(members|invites|activity|notes)(?:\/([^/]+))?$/);
    if (sharedTrip) {
      const trip = state.trips.find((t) => t.id === sharedTrip[1]);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      const id = String(trip.id);
      const [, , what, other] = sharedTrip;
      const people = state.members[id] ?? [];
      const asMemberOf = trip.role === "member";
      if (what === "members" && !other && method === "GET") {
        // On a trip the user was added to, the owner is someone else and the user is the first member.
        if (asMemberOf) {
          return json(route, [
            { id: "u-lead", name: String(trip.owner_name ?? "Someone"), role: "owner", added_at: null, you: false },
            { id: "u-me", name: OWNER_NAME, role: "member", added_at: "2026-09-20T03:00:00Z", you: true },
            ...people,
          ]);
        }
        return json(route, [{ id: "u-owner", name: OWNER_NAME, role: "owner", added_at: null, you: true }, ...people]);
      }
      if (what === "members" && other && method === "DELETE" && asMemberOf) {
        // A member can only remove themselves: leaving ends their access.
        if (other !== "u-me") return json(route, { detail: "only the trip's owner can do that" }, 403);
        state.trips = state.trips.filter((t) => t !== trip);
        return route.fulfill({ status: 204 });
      }
      if (what === "members" && other && method === "DELETE") {
        if (!people.some((m) => m.id === other)) return json(route, { detail: "no one with that id is on this trip" }, 404);
        state.members[id] = people.filter((m) => m.id !== other);
        return route.fulfill({ status: 204 });
      }
      if (what === "invites" && !other && method === "GET") {
        return json(route, (state.invites[id] ?? []).map(({ token: _token, ...invite }) => invite));
      }
      if (what === "invites" && !other && method === "POST") {
        state.inviteCount += 1;
        const token = `fakeInvite${String(state.inviteCount).padStart(4, "0")}`.padEnd(43, "x");
        const invite = { id: `inv${state.inviteCount}`, created_at: "2026-09-28T03:00:00Z", expires_at: "2026-10-05T03:00:00Z", token };
        state.invites[id] = [invite, ...(state.invites[id] ?? [])];
        return json(route, { ...invite, url: `${url.origin}/trip-invite/${token}` }, 201);
      }
      if (what === "invites" && other && method === "DELETE") {
        if (!(state.invites[id] ?? []).some((i) => i.id === other)) return json(route, { detail: "that invite link doesn't work" }, 404);
        state.invites[id] = state.invites[id].filter((i) => i.id !== other);
        return route.fulfill({ status: 204 });
      }
      if (what === "activity" && method === "GET") return json(route, (state.activity[id] ?? []).slice(0, 20));
      if (what === "notes" && method === "PUT") {
        state.notesPuts.push(body);
        const notes = typeof body?.notes === "string" ? body.notes.trim() : "";
        trip.notes = notes || null;
        // Only a shared trip keeps an activity log, as on the server.
        if (people.length > 0) state.activity[id] = [{ actor: OWNER_NAME, summary: "changed the notes", at: "2026-09-28T03:00:00Z" }, ...(state.activity[id] ?? [])];
        return json(route, trip);
      }
    }
    // An invite link opened by someone signed in: the token must be one a test made joinable.
    const acceptInvite = path.match(/^\/travel\/invites\/([^/]+)\/accept$/);
    if (acceptInvite && method === "POST") {
      const token = decodeURIComponent(acceptInvite[1]);
      const tripId = state.joinable[token];
      if (tripId) {
        delete state.joinable[token];
        return json(route, { trip_id: tripId, new: true });
      }
      // The owner's own link joins nothing and is not spent: the server answers 200 with `own`.
      const ownTrip = Object.entries(state.invites).find(([, list]) => list.some((i) => i.token === token));
      if (ownTrip) return json(route, { trip_id: ownTrip[0], new: false, own: true });
      return json(route, { detail: "that invite link doesn't work" }, 404);
    }
    const shared = path.match(/^\/shared\/trips\/([^/]+)(\/photo)?$/);
    if (shared) {
      const id = Object.keys(state.shares).find((k) => state.shares[k] === shared[1]);
      const trip = state.trips.find((t) => t.id === id);
      if (!trip) return json(route, { detail: "Not found" }, 404);
      if (shared[2]) return route.fulfill({ status: 200, contentType: "image/png", body: png() });
      // The same allow-list as the server: the plan, never money, references or notes.
      const keep = ["kind", "title", "provider", "starts", "ends", "segments", "hotel", "address", "check_in", "check_out", "day", "at", "category"];
      const detail = tripDetail(trip);
      const showBookings = state.shareBookings[String(id)] ?? true;
      // Without bookings: only the user's own plans stay (a plan with a reference or a place booked is a ticket).
      const isBooking = (b: Record<string, unknown>) => b.kind !== "activity" || Boolean(b.reference) || Boolean(b.booked_via);
      const scheduled = (detail.bookings as Record<string, unknown>[]).filter((b) => b.scheduled);
      const hidden = showBookings ? [] : scheduled.filter(isBooking);
      return json(route, {
        destination: trip.destination,
        start: trip.start,
        end: trip.end,
        days: trip.days,
        status: trip.status,
        days_until: trip.days_until,
        day_number: trip.day_number,
        day_labels: trip.day_labels,
        stops: trip.stops ?? [],
        photo: trip.photo && !trip.photo_off ? { ...(trip.photo as object), url: `/api/shared/trips/${shared[1]}/photo` } : null,
        bookings: scheduled.filter((b) => showBookings || !isBooking(b)).map((b) => Object.fromEntries(keep.map((k) => [k, b[k] ?? null]))),
        show_bookings: showBookings,
        // Days a hidden booking starts or ends on, so the page can say "Travel day" rather than "Free day".
        hidden_days: [...new Set(hidden.flatMap((b) => [b.starts, b.ends]).filter(Boolean).map(String))].sort(),
      });
    }
    const tripShot = path.match(/^\/travel\/trips\/([^/]+)\/screenshot$/);
    if (tripShot && method === "POST") {
      if (!body.image) return json(route, { detail: "no image" }, 422);
      const stay = {
        id: `pl${state.plans.length + 1}`, trip_id: tripShot[1], kind: "hotel", title: "Hotel Kumo, 3 nights", provider: null,
        starts: "2026-11-15", ends: "2026-11-18", segments: [], hotel: "Hotel Kumo", address: "4-5-6 Asakusa",
        check_in: "2026-11-15", check_out: "2026-11-18", name: null, day: null, at: null, note: null,
        reference: "9876543210", booked_via: "Agoda", category: null, scheduled: true, cost: { amount: "64500.0000", currency: "JPY" }, logged: false, manual: true,
      };
      state.plans.push(stay);
      return json(route, { added: [stay], repeated: 0, message: "✈️ Added to your Tokyo trip:\n• hotel booking (Hotel Kumo, 3 nights, 15 Nov to 18 Nov; booked on Agoda, ref 9876543210)" });
    }
    const tripPlans = path.match(/^\/travel\/trips\/([^/]+)\/bookings$/);
    if (tripPlans && method === "POST" && body.kind === "hotel") {
      const stay = {
        id: `pl${state.plans.length + 1}`, trip_id: tripPlans[1], kind: "hotel", title: body.hotel, provider: null,
        starts: body.check_in, ends: body.check_out, segments: [], hotel: body.hotel, address: body.address,
        check_in: body.check_in, check_out: body.check_out, name: null, day: null, at: null, note: null, cost: null,
        reference: body.reference ?? null, booked_via: body.booked_via ?? null, category: null, scheduled: true,
        logged: false, manual: true,
      };
      state.plans.push(stay);
      return json(route, stay, 201);
    }
    if (tripPlans && method === "POST") {
      if (!body.name) return json(route, { detail: "a plan or place needs a name" }, 422);
      const plan = {
        id: `pl${state.plans.length + 1}`, trip_id: tripPlans[1], kind: "activity", title: body.name, provider: null,
        starts: body.day, ends: body.day, segments: [], hotel: null, address: body.address, check_in: null, check_out: null,
        name: body.name, day: body.day, at: body.at, note: body.note, cost: null, logged: false, manual: true,
        reference: body.reference ?? null, booked_via: body.booked_via ?? null, category: body.category ?? null,
        place_id: body.place_id ?? null, ends_at: body.ends_at ?? null, link: body.link ?? null, list_name: body.list_name ?? null, order: null,
        // The user's own pin, only on a plan without a Google Maps place.
        lat: body.place_id ? null : (body.lat ?? null), lng: body.place_id ? null : (body.lng ?? null),
        scheduled: Boolean(body.day), ...(body.day ? {} : { starts: "2026-09-28", ends: null }),
      };
      state.plans.push(plan);
      return json(route, plan, 201);
    }
    const planEdit = path.match(/^\/travel\/bookings\/(pl\d+)$/);
    if (planEdit && method === "PUT") {
      state.plans = state.plans.map((p) =>
        p.id === planEdit[1]
          ? {
              ...p, at: body.at, day: body.day, starts: body.day ?? p.starts, scheduled: Boolean(body.day), name: body.name, title: body.name, category: body.category ?? null,
              ...("lat" in body && !p.place_id ? { lat: body.lat ?? null, lng: body.lng ?? null } : {}),
              ...("ends_at" in body ? { ends_at: body.ends_at } : {}), ...("link" in body ? { link: body.link } : {}), ...("list_name" in body ? { list_name: body.list_name } : {}),
              ...(body.day !== p.day ? { order: null } : {}),
            }
          : p,
      );
      return json(route, state.plans.find((p) => p.id === planEdit[1]));
    }
    if (planEdit && method === "DELETE") {
      state.plans = state.plans.filter((p) => p.id !== planEdit[1]);
      return route.fulfill({ status: 204 });
    }
    const tripExpense = path.match(/^\/travel\/trips\/([^/]+)\/expenses\/([^/]+)$/);
    if (tripExpense && method === "DELETE") {
      state.tripItems = state.tripItems.filter((i) => i !== tripExpense[2]);
      return route.fulfill({ status: 204 });
    }
    if (path === "/home" && method === "GET") {
      const nudges = state.missed.map(({ bill: id, due }) => {
        const bill = state.bills.find((b) => b.id === id)!;
        const shown = `${bill.amount?.currency} ${Number(bill.amount?.amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
        return {
          department: "accounting",
          kind: "missed_move",
          text: `Your ${shown} ${bill.name} on ${shortDay(due)} hasn't shown up. Did it go through?`,
          link: "/accounting/budgets",
          urgent: false,
          when: "soon",
          actions: [
            { key: "went_through", label: "It went through", method: "POST", path: `/bills/${id}/paid?due=${due}` },
            { key: "skip", label: "Skip this month", method: "POST", path: `/bills/${id}/skip?due=${due}` },
          ],
        };
      });
      // The server sorts: urgent, then about today, then the rest; by department within each.
      const today = todayItems
        ? [
            { department: "investment", kind: "plan_hit", text: "NVDA reached its stop (182.40)", link: "/investment/plans/p1", urgent: true, when: "now", actions: [] },
            { department: "travel", kind: "booking_soon", text: "Check in at Hotel Sakura today", link: "/travel/trips/t1", urgent: true, when: "now", actions: [] },
            { department: "investment", kind: "big_move", text: "AMD \u22126.2% today", link: "/investment/stocks/AMD", urgent: false, when: "today", actions: [] },
          ]
        : [];
      const soon = todayItems
        ? [
            { department: "investment", kind: "earnings", text: "MSFT reports earnings tomorrow", link: "/investment/stocks/MSFT", urgent: false, when: "soon", actions: [] },
            { department: "travel", kind: "booking_soon", text: "Flight SQ12 to Tokyo tomorrow 09:40", link: "/travel/trips/t1", urgent: false, when: "soon", actions: [] },
            { department: "travel", kind: "prep", text: "3 things to sort before Tokyo", link: "/travel/trips/t1?tab=prep", urgent: false, when: "soon", actions: [] },
          ]
        : [];
      return json(route, [
        ...today.filter((i) => i.when === "now"),
        ...today.filter((i) => i.when === "today"),
        ...nudges,
        { department: "accounting", kind: "email", text: "2 receipts from email waiting for you", link: "/settings/email", urgent: false, when: "soon", actions: [] },
        { department: "accounting", kind: "bill", text: "Rent (SGD 1,800.00) due tomorrow", link: "/accounting/budgets", urgent: false, when: "soon", actions: [] },
        ...soon,
      ]);
    }
    if (path === "/setup" && method === "GET") return json(route, state.setup);
    if (path === "/setup/dismiss" && method === "POST") {
      state.setup.dismissed = true;
      return route.fulfill({ status: 204 });
    }
    if (path === "/departments" && method === "GET") {
      return json(route, [{ name: "accounting", label: "Accounting", emoji: "🧾", blurb: "Spending." }]);
    }
    if (path === "/runs" && method === "GET") {
      const done = research
        ? [{ id: "rs1", department: "travel", kind: "travel.research", title: "Research: Tokyo", status: "done", progress: "done", steps_done: 4, steps_total: 4, result: null, error: null, created_at: "2026-09-28T03:00:00Z", finished_at: "2026-09-28T03:03:00Z" }]
        : [];
      return json(route, [...state.runs, ...done]);
    }
    if (path === "/travel/research/rs1" && method === "GET") {
      return json(route, {
        destination: "Tokyo",
        start: "2027-01-10",
        end: "2027-01-17",
        nights: 7,
        travellers: 2,
        currency: "JPY",
        home_currency: "SGD",
        when_summary: "January is cold and dry, and quieter after New Year.",
        when: [{ text: "Days are cold but clear.", source: 1 }],
        prices: [
          { label: "Return flights SIN-NRT", low: "1200", high: "1600", currency: "SGD", per: "person", source: 2, home_low: "1200", home_high: "1600" },
          { label: "Daily spending", low: "8000", high: "15000", currency: "JPY", per: "day", source: 1, home_low: "72", home_high: "135" },
        ],
        areas: RESEARCH_AREAS,
        getting_around: "An IC card covers city trains.",
        getting_around_source: 1,
        sources: [
          { id: 1, url: "https://guide.example.com/tokyo", title: "Tokyo guide", checked_on: "2026-09-28" },
          { id: 2, url: "https://flights.example.com/s", title: "Google Flights", checked_on: "2026-09-28" },
        ],
        estimate_low: "4602",
        estimate_high: "6760",
        estimate_lines: ["Return flights SIN-NRT: SGD 2,400–3,200"],
        budget: "6800",
        paydays_left: 3,
        set_aside: "2267",
        fits: true,
        trip_id: null,
      });
    }
    // POST /travel/research/{run}/ideas: the chosen areas' things (at most 4 each) become ideas under a
    // list named after the area; one already on the trip is skipped. 404 for a trip or research that
    // isn't there, 422 for a finished trip or an unknown area. ``stop_suggestion`` is the research place
    // when it is none of the trip's stops.
    const researchIdeas = path.match(/^\/travel\/research\/([^/]+)\/ideas$/);
    if (researchIdeas && method === "POST") {
      if (researchIdeas[1] !== "rs1") return json(route, { detail: "no research with that id" }, 404);
      const areas = (body.areas ?? []) as string[];
      const trip = state.trips.find((t) => t.id === body.trip_id);
      if (!trip) return json(route, { detail: "no trip with that id" }, 404);
      if (areas.length === 0) return json(route, { detail: "choose at least one area" }, 422);
      if (String(trip.end) < "2026-09-28") return json(route, { detail: "that trip is over" }, 422);
      const chosen = areas.map((name) => RESEARCH_AREAS.find((a) => a.name.toLowerCase() === name.trim().toLowerCase()));
      const unknown = areas.find((_, n) => !chosen[n]);
      if (unknown !== undefined) return json(route, { detail: `the research has no area called '${unknown}'` }, 422);
      state.researchIdeaPosts.push({ run: researchIdeas[1], trip_id: String(trip.id), areas });
      const squash = (name: string) => name.toLowerCase().replace(/\s+/g, "");
      const have = new Set(state.plans.filter((p) => p.kind === "activity").map((p) => squash(String(p.name))));
      let [added, skipped] = [0, 0];
      for (const area of chosen) {
        for (const thing of area!.things.slice(0, 4)) {
          if (have.has(squash(thing))) {
            skipped += 1;
            continue;
          }
          have.add(squash(thing));
          added += 1;
          state.plans.push({
            id: `pl${state.plans.length + 1}`, trip_id: trip.id, kind: "activity", title: thing, provider: null,
            starts: "2026-09-28", ends: null, segments: [], hotel: null, address: null, check_in: null, check_out: null,
            name: thing, day: null, at: null, note: null, cost: null, logged: false, manual: true, reference: null, booked_via: null,
            category: null, place_id: null, ends_at: null, link: null, list_name: area!.name, order: null, lat: null, lng: null,
            scheduled: false,
          });
        }
      }
      const stops = (trip.stops as { name: string }[] | undefined)?.length ? (trip.stops as { name: string }[]) : suggestedStops(trip);
      const first = (name: string) => name.split(",")[0].trim().toLowerCase();
      const known = [String(trip.destination), ...stops.map((s) => s.name)].some((name) => first(name) === first("Tokyo"));
      return json(route, { added, skipped, stop_suggestion: known ? null : "Tokyo" });
    }
    if (path === "/travel/research/rs1/trip" && method === "POST") {
      const trip = {
        id: "trip9", destination: "Tokyo", start: "2027-01-10", end: "2027-01-17", days: 8, currency: "JPY",
        budget: { amount: "6800.0000", currency: "SGD" }, companions: [], set_aside: { amount: "2267.0000", currency: "SGD" },
        planned: {}, status: "upcoming", days_until: 104, day_number: null, notes: null, day_labels: {}, stops: [],
        role: "owner", owner_name: OWNER_NAME,
      };
      state.trips = [trip, ...state.trips];
      return json(route, trip, 201);
    }
    const runCancel = path.match(/^\/runs\/(\w+)\/cancel$/);
    if (runCancel && method === "POST") {
      const run = state.runs.find((r) => r.id === runCancel[1])!;
      Object.assign(run, { status: "cancelled", progress: "cancelled" });
      state.cancelled.push(run.id);
      return json(route, run);
    }
    if (path === "/spending/months" && method === "GET") {
      const sgd = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
      const now = live()
        .filter((t) => t.direction === "out")
        .reduce((s, t) => s + Number(t.amount.amount), 0);
      const overall = state.budgets.find((b) => b.category_id === null);
      return json(route, {
        currency: "SGD",
        months: [
          ["2026-04-01", 1520],
          ["2026-05-01", 1384.5],
          ["2026-06-01", 2210],
          ["2026-07-01", 1190.25],
          ["2026-08-01", 1655],
        ]
          .map(([month, amount]) => ({ month, spent: sgd(amount as number), to_date: false }))
          .concat([{ month: "2026-09-01", spent: sgd(now), to_date: true }]),
        last_month_to_date: sgd(1402.1),
        budget: overall ? sgd(overall.limit) : null,
      });
    }
    if (path === "/wallets" && method === "GET") return json(route, wallets);
    if (path === "/wallets/likely-moves" && method === "GET") {
      const ibkrWallet = wallets.find((w) => w.id === "w-ibkr") ?? null;
      const reasons: Record<string, [typeof ibkrWallet, string]> = {
        t201: [ibkrWallet, "The description names IBKR."],
        t202: [null, "A round amount, like the transfers you've moved before."],
      };
      return json(
        route,
        live()
          .filter((t) => t.id in reasons && t.direction !== "move")
          .map((t) => ({ transaction: t, wallet: reasons[t.id][0], reason: reasons[t.id][1] })),
      );
    }
    if (path === "/wallets" && method === "POST") {
      const name = String(body.name).trim();
      if (wallets.some((w) => w.name.toLowerCase() === name.toLowerCase()))
        return json(route, { detail: "a wallet with that name already exists" }, 409);
      const created = { id: `w-${wallets.length + 1}`, name, kind: String(body.kind), match_words: (body.match_words ?? []) as string[] };
      wallets.push(created);
      return json(route, created, 201);
    }
    const walletPreview = path.match(/^\/wallets\/([\w-]+)\/delete-preview$/);
    if (walletPreview && method === "GET") {
      const wallet = wallets.find((w) => w.id === walletPreview[1]);
      if (!wallet) return json(route, { detail: "wallet not found" }, 404);
      if (wallet.kind === "spending") return json(route, { detail: "Spending can't be deleted" }, 422);
      const { mine, dropped } = walletFold(wallet.id, url.searchParams.get("move_to"));
      return json(route, { moved: mine.length - dropped.length, removed: dropped.length });
    }
    const walletOne = path.match(/^\/wallets\/([\w-]+)$/);
    if (walletOne && method === "PATCH") {
      const wallet = wallets.find((w) => w.id === walletOne[1]);
      if (!wallet) return json(route, { detail: "wallet not found" }, 404);
      if (body.kind && wallet.kind === "spending" && body.kind !== "spending")
        return json(route, { detail: "Spending can't change kind" }, 400);
      if (body.name && wallets.some((w) => w.id !== wallet.id && w.name.toLowerCase() === String(body.name).toLowerCase()))
        return json(route, { detail: "a wallet with that name already exists" }, 409);
      Object.assign(wallet, body);
      for (const t of state.txs)
        for (const end of ["from_wallet", "to_wallet"] as const)
          if (t[end]?.id === wallet.id) t[end] = walletRef(wallet);
      return json(route, wallet);
    }
    if (walletOne && method === "DELETE") {
      const wallet = wallets.find((w) => w.id === walletOne[1]);
      if (!wallet) return json(route, { detail: "wallet not found" }, 404);
      if (wallet.kind === "spending") return json(route, { detail: "Spending can't be deleted" }, 400);
      const into = wallets.find((w) => w.id === url.searchParams.get("move_to") && w.id !== wallet.id);
      const { mine, dropped } = walletFold(wallet.id, into?.id ?? null);
      if (mine.length > 0 && !into) return json(route, { detail: "pick another wallet to move its moves to" }, 400);
      for (const t of mine) {
        if (dropped.includes(t)) t.deleted = true;
        else for (const end of ["from_wallet", "to_wallet"] as const) if (t[end]?.id === wallet.id) t[end] = walletRef(into!);
      }
      wallets.splice(wallets.indexOf(wallet), 1);
      return json(route, { moved: mine.length - dropped.length, removed: dropped.length, into: mine.length ? into : null });
    }
    if (path === "/moves" && method === "POST") {
      const from = wallets.find((w) => w.id === (body.from_wallet_id ?? "w-spending"));
      const to = wallets.find((w) => w.id === body.to_wallet_id);
      if (!from || !to) return json(route, { detail: "wallet not found" }, 404);
      if (from.id === to.id) return json(route, { detail: "a move needs two different wallets" }, 400);
      const tx: Tx = {
        ...mk(`t${state.txs.length + 1}`, "move", body.amount, null, null),
        from_wallet: walletRef(from),
        to_wallet: walletRef(to),
        notes: body.notes ?? null,
      };
      if (body.currency) tx.amount.currency = body.currency;
      if (body.occurred_at) tx.occurred_at = `${String(body.occurred_at).slice(0, 10)}T04:00:00Z`;
      state.txs.unshift(tx);
      return json(route, tx, 201);
    }
    const markMove = path.match(/^\/transactions\/(t\d+)\/move$/);
    if (markMove && method === "POST") {
      const tx = state.txs.find((t) => t.id === markMove[1]);
      const wallet = wallets.find((w) => w.id === body.wallet_id);
      if (!tx) return json(route, { detail: "transaction not found" }, 404);
      if (tx.direction === "move") return json(route, { detail: "this is already a move" }, 400);
      if (!wallet || wallet.kind === "spending")
        return json(route, { detail: "pick a wallet other than Spending to move it to or from" }, 400);
      if (tx.split) return json(route, { detail: "this bill is split with others, so it can't be a move" }, 409);
      const spending = walletRef(wallets[0]);
      const [sent, received] = tx.direction === "out" ? [spending, walletRef(wallet)] : [walletRef(wallet), spending];
      Object.assign(tx, { direction: "move", category_id: null, from_wallet: sent, to_wallet: received });
      return json(route, tx);
    }
    if (path === "/summary") {
      const out = live().filter((t) => t.direction === "out");
      const total = out.reduce((s, t) => s + Number(t.amount.amount), 0);
      // Money moved into savings and investment wallets.
      const putAway = live()
        .filter((t) => t.direction === "move" && ["savings", "investment"].includes(t.to_wallet?.kind ?? ""))
        .reduce((s, t) => s + Number(t.amount.amount), 0);
      return json(route, {
        start: "2026-09-01",
        end: "2026-09-28",
        currency: "SGD",
        totals: [
          {
            direction: "out",
            total: { amount: total.toFixed(4), currency: "SGD" },
            count: out.length,
            converted: [{ amount: "33.8000", currency: "USD" }],
            unconverted: [],
          },
          {
            direction: "in",
            total: { amount: "4200.0000", currency: "SGD" },
            count: 1,
            converted: [],
            unconverted: [],
          },
        ],
        put_away: { amount: putAway.toFixed(4), currency: "SGD" },
        saving_rate: putAway / 4200,
        total_out: { amount: (total + putAway).toFixed(4), currency: "SGD" },
        by_category: [
          {
            category_id: "food",
            category_name: "Dining Out",
            total: { amount: "12.4000", currency: "SGD" },
            count: 1,
          },
          {
            category_id: null,
            category_name: null,
            total: { amount: "25.0000", currency: "SGD" },
            count: 1,
          },
        ],
      });
    }
    if (path === "/budgets/month" && method === "GET") {
      const sgd = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
      const overall = state.budgets.find((b) => b.category_id === null);
      // Fixed figures for the made-up month: 5,000 in, 2,600 out of Spending so far and
      // 1,300 still due leave 1,100 to spend, which is less than the 1,400 left of a budget.
      return json(route, {
        currency: "SGD",
        total_out: sgd(2600),
        left_to_spend: sgd(1100),
        still_due_out: sgd(1300),
        income: sgd(5000),
        budget_left: overall ? sgd(1400) : null,
        tighter: overall ? "left_to_spend" : null,
        plan_warning: planWarning
          ? "Your budget and the moves you've scheduled add up to more than you usually bring in."
          : null,
        skipped: [],
      });
    }
    if (path === "/budgets" && method === "GET") {
      const sgd = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
      return json(
        route,
        state.budgets.map((b) => ({
          id: b.id,
          category_id: b.category_id,
          name: b.category_id ? "Dining Out" : "Overall",
          limit: sgd(b.limit),
          spent: sgd(b.spent),
          remaining: sgd(b.limit - b.spent),
          percent: Math.floor((b.spent * 100) / b.limit),
          unconverted: [],
        })),
      );
    }
    if (path === "/budgets" && method === "PUT") {
      const existing = state.budgets.find((b) => b.category_id === (body.category_id ?? null));
      if (existing) existing.limit = Number(body.amount);
      else
        state.budgets.push({
          id: `b${state.budgets.length + 1}`,
          category_id: body.category_id ?? null,
          limit: Number(body.amount),
          spent: body.category_id ? 90 : 37.4,
        });
      return route.fulfill({ status: 204 });
    }
    if (path.startsWith("/budgets/") && method === "DELETE") {
      state.budgets = state.budgets.filter((b) => `/budgets/${b.id}` !== path);
      return route.fulfill({ status: 204 });
    }
    if (path === "/cashflow" && method === "GET") {
      const month = new URL(route.request().url()).searchParams.get("month") ?? "2026-09";
      const [year, mon] = month.split("-").map(Number);
      const last = new Date(Date.UTC(year, mon, 0)).getUTCDate();
      const m = (amount: string) => ({ amount, currency: "SGD" });
      const days = Array.from({ length: last }, (_, n) => {
        const day = `${month}-${String(n + 1).padStart(2, "0")}`;
        const logged = day === "2026-09-12" ? { in: "0", out: "42.10" } : day === "2026-09-25" ? { in: "4200", out: "0" } : { in: "0", out: "0" };
        const expected =
          day === "2026-09-30"
            ? [{ kind: "bill", name: "Rent", direction: "out", amount: m("1800"), home: m("1800") }]
            : day === "2026-10-12"
              ? [{ kind: "subscription", name: "Netflix", direction: "out", amount: m("17.98"), home: m("17.98") }]
              : [];
        const net = (Number(logged.in) - Number(logged.out)).toFixed(2);
        const expectedNet = expected.reduce((sum, e) => sum - Number(e.home.amount), 0).toFixed(2);
        return { day, money_in: m(logged.in), money_out: m(logged.out), net: m(net), expected, expected_net: m(expectedNet) };
      });
      return json(route, {
        start: `${month}-01`,
        end: `${month}-${last}`,
        today: "2026-09-28",
        currency: "SGD",
        days,
        logged_in: m(month === "2026-09" ? "4200.00" : "0"),
        logged_out: m(month === "2026-09" ? "42.10" : "0"),
        expected_in: m("0"),
        expected_out: m(month === "2026-09" ? "1800.00" : "17.98"),
        unknown_amounts: 0,
        unconverted: [],
      });
    }
    if (path === "/subscriptions" && method === "GET") {
      const out = (s: { id: string; name: string; amount: string }) => ({
        id: s.id,
        name: s.name,
        cadence: "monthly",
        amount: { amount: s.amount, currency: "SGD" },
        monthly: { amount: s.amount, currency: "SGD" },
        last_charged_on: "2026-09-12",
        next_charge: "2026-10-12",
        previous_amount: s.id === "s1" ? { amount: "15.98", currency: "SGD" } : null,
        price_changed_on: s.id === "s1" ? "2026-09-12" : null,
      });
      const tracked = state.subs.filter((s) => s.status === "active");
      const total = tracked.reduce((sum, s) => sum + Number(s.amount), 0);
      return json(route, {
        tracked: tracked.map(out),
        proposed: state.subs.filter((s) => s.status === "proposed").map(out),
        monthly_totals: tracked.length ? [{ amount: total.toFixed(2), currency: "SGD" }] : [],
      });
    }
    const sub = path.match(/^\/subscriptions\/(\w+)\/(track|dismiss)$/);
    if (sub && method === "POST") {
      const found = state.subs.find((s) => s.id === sub[1]);
      if (found) found.status = sub[2] === "track" ? "active" : "dismissed";
      return route.fulfill({ status: 204 });
    }
    if (path === "/trip-alerts") {
      if (method === "PUT") state.tripAlerts = Boolean(body.enabled);
      return json(route, { enabled: state.tripAlerts });
    }
    if (path === "/notifications") {
      if (method === "PUT") {
        if (body.frequency) state.frequency = body.frequency;
        if (body.daily_at) dailyAt = body.daily_at;
        if (body.quiet_start) marketAlerts.quiet_start = body.quiet_start;
        if (body.quiet_end) marketAlerts.quiet_end = body.quiet_end;
        if (body.move_alert_percent !== undefined && body.move_alert_percent !== null) {
          const percent = Number(body.move_alert_percent);
          if (!(percent >= 1 && percent <= 20)) {
            return json(route, { detail: "a big move can be 1.0% to 20.0% in a day" }, 422);
          }
          marketAlerts.move_alert_percent = percent.toFixed(1);
        }
        if (typeof body.market_summary === "boolean") marketAlerts.market_summary = body.market_summary;
        if (body.daily_cap !== undefined && body.daily_cap !== null) {
          const cap = Number(body.daily_cap);
          if (!(Number.isInteger(cap) && cap >= 3 && cap <= 20)) {
            return json(route, { detail: "the daily limit can be 3 to 20 messages" }, 422);
          }
          marketAlerts.daily_cap = cap;
        }
      }
      const [h, m] = dailyAt.split(":").map(Number);
      const at = `${h % 12 || 12}${m ? `:${String(m).padStart(2, "0")}` : ""}${h < 12 ? "am" : "pm"}`;
      const options = {
        instant: "as it happens",
        hourly: "every hour (8am to 9pm)",
        thrice_daily: "3 times a day (9am, 2pm, 8pm)",
        daily: `once a day at ${at}`,
        off: "off",
      };
      const description =
        state.frequency === "off"
          ? "Transaction updates are off."
          : state.frequency === "instant"
            ? "You get a message for each transaction as it happens."
            : `You get a summary of your transactions ${options[state.frequency as keyof typeof options]}.`;
      return json(route, { frequency: state.frequency, daily_at: dailyAt, description, options, ...marketAlerts });
    }
    if (path === "/notifications/history" && method === "GET") {
      // Made-up messages, newest first: one urgent and sent, one sent, one waiting for quiet hours
      // to end, two told in a digest, a long one with line breaks, and one from before Telegram was linked.
      return json(route, [
        { id: "n0", kind: "big_move", level: "urgent", text: "TSLA is down 6.2% today at 9:58am, 201.15", link: "/investment/stocks/TSLA", status: "sent", created_at: "2026-10-22T02:00:00Z", sent_at: "2026-10-22T02:00:00Z", held_until: null },
        { id: "n1", kind: "bill_reminder", level: "now", text: "Reminder: Rent is due in 3 days.", link: "/accounting", status: "sent", created_at: "2026-10-22T01:00:00Z", sent_at: "2026-10-22T01:00:00Z", held_until: null },
        { id: "n2", kind: "receipt_question", level: "now", text: "Fresh Mart, S$23.40 on 21 Oct. Log it?", link: "/settings/email", status: "held", created_at: "2026-10-21T16:30:00Z", sent_at: null, held_until: "2026-10-22T00:00:00Z" },
        { id: "n3", kind: "budget_alert", level: "digest", text: "You've used 80% of your overall budget for October: S$800.00 of S$1,000.00.", link: "/accounting/budgets", status: "digested", created_at: "2026-10-21T14:10:00Z", sent_at: "2026-10-22T00:00:00Z", held_until: null },
        { id: "n4", kind: "big_move", level: "digest", text: "NVDA +5.4% today at 10:42pm, 182.40", link: "/investment/stocks/NVDA", status: "digested", created_at: "2026-10-21T14:42:00Z", sent_at: "2026-10-22T00:00:00Z", held_until: null },
        { id: "n5", kind: "market_summary", level: "now", text: "Good morning. Your portfolio rose 1.2% in the last US session.\nNVDA +5.4% on strong demand for its data centre chips, with analysts raising their targets.\nAMD +2.1% after a new product launch.\nTSLA -0.8% on delivery numbers that came in lower than expected.", link: null, status: "sent", created_at: "2026-10-20T00:00:00Z", sent_at: "2026-10-20T00:00:00Z", held_until: null },
        { id: "n6", kind: "trip_reminder", level: "now", text: "Your Tokyo trip is in 5 days. Check your passport is valid.", link: null, status: "dropped", created_at: "2026-10-09T03:00:00Z", sent_at: null, held_until: null },
      ]);
    }
    if (path === "/salary" && method === "GET") {
      const pay = state.salary;
      if (!pay) return json(route, null);
      return json(route, {
        ...pay,
        description: pay.rule === "monthly_day" ? `the ${pay.day}th of each month` : "the last weekday of each month",
        usual: pay.usual ? { amount: Number(pay.usual).toFixed(4), currency: "SGD" } : null,
        next_payday: "2026-10-23",
        days_until: 25,
      });
    }
    if (path === "/salary" && method === "PUT") {
      state.salary = { rule: body.rule, day: body.day, anchor: body.anchor, usual: state.salary?.usual ?? null };
      return route.fulfill({ status: 204 });
    }
    if (path === "/salary/usual" && method === "PUT" && state.salary) {
      state.salary.usual = body.amount;
      return route.fulfill({ status: 204 });
    }
    if (path === "/salary" && method === "DELETE") {
      state.salary = null;
      return route.fulfill({ status: 204 });
    }
    if (path === "/bills" && method === "GET") return json(route, state.bills);
    if (path === "/bills" && method === "POST") {
      const bill = {
        id: `bill${state.bills.length + 1}`,
        name: body.name,
        spending: body.spending ?? true,
        wallet: null as WalletRef | null,
        amount: body.amount ? { amount: Number(body.amount).toFixed(4), currency: "SGD" } : null,
        cadence: body.cadence,
        due: body.due,
        days_until: Math.round((Date.parse(body.due) - Date.parse("2026-09-28")) / 86_400_000),
        snoozed: false,
      };
      if (body.wallet_id) {
        const target = wallets.find((w) => w.id === body.wallet_id);
        if (bill.spending) return json(route, { detail: "a bill that counts as spending can't move money to a wallet" }, 422);
        if (!target) return json(route, { detail: "wallet not found" }, 404);
        if (target.kind === "spending") return json(route, { detail: "a scheduled move goes to a wallet other than Spending" }, 422);
        bill.wallet = walletRef(target);
      }
      state.bills.push(bill);
      return json(route, bill, 201);
    }
    const billOne = path.match(/^\/bills\/([^/]+)$/);
    if (billOne && method === "PATCH") {
      const bill = state.bills.find((b) => b.id === billOne[1]);
      if (!bill) return json(route, { detail: "bill not found" }, 404);
      const target = body.wallet_id ? wallets.find((w) => w.id === body.wallet_id) : null;
      if (body.wallet_id && bill.spending !== false)
        return json(route, { detail: "a bill that counts as spending can't move money to a wallet" }, 422);
      if (body.wallet_id && !target) return json(route, { detail: "wallet not found" }, 404);
      if (target?.kind === "spending") return json(route, { detail: "a scheduled move goes to a wallet other than Spending" }, 422);
      bill.wallet = target ? walletRef(target) : null;
      return json(route, bill);
    }
    const billAction = path.match(/^\/bills\/([^/]+)(\/paid|\/snooze|\/skip)?$/);
    if (billAction && method !== "GET") {
      const [, id, action] = billAction;
      const marked = state.bills.find((b) => b.id === id);
      const due = url.searchParams.get("due") ?? marked?.due ?? "2026-09-28";
      state.missed = state.missed.filter((m) => !(m.bill === id && (action === "/paid" || action === "/skip")));
      if (action === "/snooze") state.bills = state.bills.map((b) => (b.id === id ? { ...b, snoozed: true } : b));
      else state.bills = state.bills.filter((b) => b.id !== id); // paid (one-off) or removed
      if (action === "/paid") {
        const amount = (body as { amount?: string | null } | null)?.amount;
        if (marked?.spending === false && marked.wallet) {
          const head = `Marked ${marked.name} (${shortDay(due)}) as done`;
          if (!marked.amount) {
            return json(route, { message: `${head}. It has no set amount, so no move was logged; tell me how much it was to log it.`, logged: false, moved: false, needs_amount: true });
          }
          state.txs.unshift({
            ...mk(`t${state.txs.length + 1}`, "move", marked.amount.amount, marked.name, null),
            from_wallet: walletRef(wallets[0]),
            to_wallet: marked.wallet,
          });
          const shown = Number(marked.amount.amount).toFixed(2);
          return json(route, { message: `${head} and logged a move of ${shown} SGD from Spending to ${marked.wallet.name}.`, logged: false, moved: true, needs_amount: false });
        }
        if (marked?.spending === false) {
          return json(route, { message: "Marked it as done. It doesn't count as spending, so nothing was logged.", logged: false, moved: false, needs_amount: false });
        }
        return json(route, {
          message: amount ? `Marked it as paid and logged SGD ${amount} in this month's spending.` : "Marked it as paid.",
          logged: Boolean(amount),
          moved: false,
          needs_amount: !amount,
        });
      }
      return route.fulfill({ status: 204 });
    }
    if (path === "/ious") {
      return json(
        route,
        annRepaid
          ? []
          : [
              {
                split_id: "s1",
                transaction_id: "t9",
                participant_name: "Ann",
                share: { amount: "30.0000", currency: "SGD" },
                outstanding: { amount: "20.0000", currency: "SGD" },
                expense_occurred_at: "2026-09-20T12:00:00Z",
              },
            ],
      );
    }
    if (path === "/ious/s1/repaid" && method === "POST") {
      annRepaid = true;
      return route.fulfill({ status: 204 });
    }
    if (path === "/email" && method === "GET") return json(route, { available: true, forwarding_available: true, ...state.email });
    if (path === "/email/link" && method === "GET")
      return json(route, url.searchParams.get("t") === "good" ? { valid: true, account_hint: "9165" } : { valid: false, account_hint: null });
    const emailAction = path.match(/^\/email\/(e\d+)\/(log|skip|move)$/);
    if (emailAction && method === "POST") {
      const email = state.email.emails.find((e) => e.id === emailAction[1])!;
      if (emailAction[2] === "move") {
        const target = wallets.find((w) => w.id === (body.wallet_id ?? email.move_wallet_id));
        if (!target) return json(route, { detail: "wallet not found" }, 404);
        state.emailMoves.push({ id: String(email.id), body });
        const [sent, received] = email.received ? [walletRef(target), walletRef(wallets[0])] : [walletRef(wallets[0]), walletRef(target)];
        state.txs.unshift({
          ...mk(`t${state.txs.length + 1}`, "move", String(body.amount ?? email.amount), String(email.merchant), null),
          from_wallet: sent,
          to_wallet: received,
        });
        Object.assign(email, { status: "logged", transaction_id: "t9", actionable: false, move_wallet_id: null, move_wallet: null });
        return route.fulfill({ status: 204 });
      }
      Object.assign(email, emailAction[2] === "log"
        ? { status: "logged", transaction_id: "t9", actionable: false }
        : { status: "skipped", reason: "you skipped it" });
      return route.fulfill({ status: 204 });
    }
    if (path === "/categories" && method === "GET") return json(route, categories);
    if (path === "/categories" && method === "POST") {
      const name = String(body.name).trim();
      if (categories.some((c) => c.name.toLowerCase() === name.toLowerCase()))
        return json(route, { detail: "a category with that name already exists" }, 409);
      const created = { id: `c${categories.length + 1}`, name };
      categories.push(created);
      return json(route, created, 201);
    }
    // Merging and deleting both fold a category into another one and drop it.
    const foldCategory = (sourceId: string, intoId: string) => {
      const into = categories.find((c) => c.id === intoId)!;
      let moved = 0;
      for (const tx of state.txs) if (tx.category_id === sourceId) { tx.category_id = into.id; moved++; }
      for (const rule of state.rules)
        if (rule.category_id === sourceId) Object.assign(rule, { category_id: into.id, category_name: into.name });
      state.budgets = state.budgets.filter((b) => b.category_id !== sourceId);
      categories.splice(categories.findIndex((c) => c.id === sourceId), 1);
      return { moved, into };
    };
    const categoryMerge = path.match(/^\/categories\/([\w-]+)\/merge$/);
    if (categoryMerge && method === "POST") return json(route, foldCategory(categoryMerge[1], body.into_id));
    const categoryEdit = path.match(/^\/categories\/([\w-]+)$/);
    if (categoryEdit && method === "DELETE") {
      const category = categories.find((c) => c.id === categoryEdit[1])!;
      if (["other", "income"].includes(category.name.toLowerCase()))
        return json(route, { detail: "Other and Income can't be deleted" }, 400);
      const moveTo = url.searchParams.get("move_to") ?? categories.find((c) => c.name === "Other")!.id;
      if (moveTo === category.id || !categories.some((c) => c.id === moveTo))
        return json(route, { detail: "pick another category to move its expenses to" }, 400);
      return json(route, foldCategory(category.id, moveTo));
    }
    if (categoryEdit && method === "PATCH") {
      const category = categories.find((c) => c.id === categoryEdit[1])!;
      Object.assign(category, body);
      return json(route, category);
    }
    if (path === "/imports/pdf" && method === "POST") {
      if (Buffer.from(String(body.pdf), "base64").toString().includes("scanned")) {
        return json(route, {
          needs_password: false, wrong_password: false, kind: "card", rows: 1, reconciles: null, scanned: true,
          csv: "Date,Description,Amount\n2026-09-10,Night Market,-12.00\n",
          layout: { date: 0, description: [1], amount: 2, debit: null, credit: null, currency: null, date_order: "ymd", sign: "negative_is_out" },
        });
      }
      if (body.password !== "secret") {
        return json(route, { needs_password: true, wrong_password: Boolean(body.password), csv: null, layout: null, kind: null, rows: 0, reconciles: null, scanned: false });
      }
      return json(route, {
        needs_password: false, wrong_password: false, kind: "card", rows: 2, reconciles: true, scanned: false,
        csv: "Date,Description,Amount\n2026-09-05,Beach Cafe,-28.50\n2026-09-08,Online Refund,10.00\n",
        layout: { date: 0, description: [1], amount: 2, debit: null, credit: null, currency: null, date_order: "ymd", sign: "negative_is_out" },
      });
    }
    if (path === "/imports/preview" && method === "POST") {
      const csv = String(body.csv);
      const layout = body.layout ?? {
        date: 0, description: [1], amount: 2, debit: null, credit: null, currency: null,
        date_order: "dmy", sign: "negative_is_out",
      };
      const lines = csv.trim().split("\n").slice(1).map((l) => l.split(","));
      const named = wallets.find((w) => w.id === "w-ibkr");
      return json(route, {
        headers: ["Date", "Description", "Amount"],
        layout,
        saved_as: null,
        rows: lines.map((cells, index) => {
          const amount = Number(cells[2]);
          const readable = !Number.isNaN(amount) && /\d/.test(cells[0]);
          return {
            index,
            verdict: !readable ? "unclear" : cells[1] === "Grab" ? "duplicate" : "new",
            cells,
            date: readable ? "2026-09-28" : null,
            description: cells[1],
            amount: readable ? Math.abs(amount).toFixed(2) : null,
            currency: readable ? "SGD" : null,
            direction: readable ? (amount < 0 ? "out" : "in") : null,
            // A description that names a wallet is proposed as a move, with no category.
            category: readable && !(named && cells[1].toLowerCase().includes("ibkr")) ? (amount < 0 ? "Other" : "Income") : null,
            move_to: readable && amount < 0 && named && cells[1].toLowerCase().includes("ibkr") ? named : null,
            move_from: readable && amount > 0 && named && cells[1].toLowerCase().includes("ibkr") ? named : null,
            problem: readable ? null : "can't read the date",
            matches: cells[1] === "Grab" ? { date: "2026-09-28", description: "Grab", amount: "25.00" } : null,
          };
        }),
      });
    }
    if (path === "/imports" && method === "POST") {
      state.importBodies.push({ include: body.include, moves: body.moves ?? [] });
      const record = {
        id: `i${state.imports.length + 1}`, file_name: body.file_name, added: body.include.length,
        created_at: "2026-09-28T06:00:00Z", undone_at: null,
      };
      state.imports.unshift(record);
      return json(route, { ...record, skipped: 0 }, 201);
    }
    if (path === "/imports" && method === "GET") return json(route, state.imports);
    const undo = path.match(/^\/imports\/(\w+)\/undo$/);
    if (undo && method === "POST") {
      const record = state.imports.find((i) => i.id === undo[1])!;
      record.undone_at = "2026-09-28T06:05:00Z";
      return json(route, { removed: record.added });
    }
    if (path === "/memories" && method === "GET") return json(route, state.memories);
    if (path === "/memories" && method === "DELETE") {
      state.memories = [];
      return route.fulfill({ status: 204 });
    }
    if (path.startsWith("/memories/") && method === "DELETE") {
      state.memories = state.memories.filter((m) => `/memories/${m.id}` !== path);
      return route.fulfill({ status: 204 });
    }
    if (path === "/category-rules" && method === "GET") return json(route, state.rules);
    if (path === "/category-rules" && method === "PUT") {
      const pattern = String(body.pattern).trim().toLowerCase();
      state.rules = state.rules.filter((r) => r.pattern !== pattern);
      state.rules.push({
        id: `r${state.rules.length + 1}`,
        pattern,
        category_id: body.category_id,
        category_name: categoryName(body.category_id),
        explanation: "You added this rule on 28 Sep 2026.",
      });
      return route.fulfill({ status: 204 });
    }
    if (path === "/category-rules/accept" && method === "POST") {
      const tx = state.txs.find((t) => t.id === body.transaction_id)!;
      const pattern = String(tx.counterparty).toLowerCase();
      state.rules.push({
        id: `r${state.rules.length + 1}`,
        pattern,
        category_id: tx.category_id!,
        category_name: categoryName(tx.category_id!),
        explanation: `Added on 28 Sep 2026 when you filed “${tx.counterparty}” under ${categoryName(tx.category_id!)}.`,
      });
      return route.fulfill({ status: 204 });
    }
    if (path.startsWith("/category-rules/") && method === "DELETE") {
      state.rules = state.rules.filter((r) => `/category-rules/${r.id}` !== path);
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/category-explanation")) {
      return json(route, { text: "It's in Dining Out because that was chosen for it, not by a rule." });
    }
    if (path.startsWith("/transactions/") && method === "PATCH") {
      const tx = state.txs.find((t) => `/transactions/${t.id}` === path)!;
      const changed = body.category_id !== tx.category_id;
      tx.category_id = body.category_id;
      tx.counterparty = body.counterparty;
      const pattern = String(tx.counterparty ?? "").toLowerCase();
      const offer =
        changed && tx.category_id && pattern && !state.rules.some((r) => r.pattern === pattern)
          ? {
              question: `Always file “${pattern}” under ${categoryName(tx.category_id)}?`,
              pattern,
              category_id: tx.category_id,
              replaces_category_id: null,
            }
          : null;
      return json(route, { ...tx, rule_suggestion: offer });
    }
    if (path === "/transactions/suggestions" && method === "GET") {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const direction = url.searchParams.get("direction") ?? "out";
      const groups = new Map<string, Tx[]>();
      for (const t of live()) {
        if (t.direction !== direction || !t.counterparty) continue;
        const key = t.counterparty.toLowerCase();
        if (q && (!key.includes(q) || key === q)) continue;
        groups.set(key, [...(groups.get(key) ?? []), t]);
      }
      const out = [...groups.values()]
        .sort((a, b) => b.length - a.length)
        .map((txs) => {
          const category = categories.find((c) => c.id === txs[0].category_id) ?? null;
          return { name: txs[0].counterparty, category_id: category?.id ?? null, category: category?.name ?? null, amount: txs[0].amount, times: txs.length, last_on: "2026-09-27" };
        });
      return json(route, out);
    }
    const one = path.match(/^\/transactions\/(t\d+)$/);
    if (one && method === "GET") return json(route, state.txs.find((t) => t.id === one[1]));
    if (path === "/transactions" && method === "GET") {
      const q = url.searchParams;
      const direction = q.get("direction");
      const category = q.get("category_id");
      const status = q.get("status");
      const limit = Number(q.get("limit") ?? 1000);
      const items = live().filter(
        (t) =>
          (!direction || t.direction === direction) &&
          (!category || t.category_id === category) &&
          (q.get("uncategorized") !== "true" || t.category_id === null) &&
          (!status || t.status === status),
      );
      return json(route, { items: items.slice(0, limit), total: items.length });
    }
    const pair = path.match(/^\/transactions\/(t\d+)\/(merge|not-duplicate)$/);
    if (pair && method === "POST") {
      const mine = state.txs.find((t) => t.id === pair[1])!;
      const other = state.txs.find((t) => t.id === body.other_id)!;
      mine.duplicate = null;
      other.duplicate = null;
      if (pair[2] === "not-duplicate") return route.fulfill({ status: 204 });
      const [kept, removed] = mine.counterparty?.includes("*") ? [mine, other] : [other, mine];
      kept.counterparty = "Grab Singapore";
      removed.deleted = true;
      return json(route, { kept, removed });
    }
    if (path === "/transactions" && method === "POST") {
      const tx = mk(
        `t${state.txs.length + 1}`,
        body.direction,
        body.amount,
        body.counterparty,
        body.category_id,
      );
      state.txs.unshift(tx);
      return json(route, tx, 201);
    }
    if (
      path === "/transactions/bulk-delete" ||
      path === "/transactions/bulk-restore"
    ) {
      const deleting = path.endsWith("delete");
      for (const t of state.txs)
        if (body.ids.includes(t.id)) t.deleted = deleting;
      return json(route, { ids: body.ids });
    }
    if (path === "/chat/history" && method === "GET") {
      const lines = chatHistory
        ? [
            { id: 2, role: "user", text: "kopi 4.20", channel: "telegram", at: "2026-09-27T01:00:00Z" },
            { id: 3, role: "nexus", text: "Logged SGD 4.20 at Kopi.", channel: "telegram", at: "2026-09-27T01:00:01Z" },
            { id: 4, role: "user", text: "how much on food this month?", channel: "web", at: "2026-09-28T02:00:00Z" },
            { id: 5, role: "nexus", text: "SGD 12.40 on Dining Out so far.", channel: "web", at: "2026-09-28T02:00:01Z" },
          ]
        : [];
      const before = url.searchParams.get("before");
      if (before) {
        return json(route, {
          lines: [{ id: 1, role: "user", text: "hello from last week", channel: "web", at: "2026-09-20T01:00:00Z" }],
          more: false,
          pending: null,
        });
      }
      return json(route, { lines, more: chatHistory, pending: null });
    }
    if (path === "/chat") {
      state.chatSent.push(String(body.message));
      if (String(body.message).startsWith("For my ")) {
        return json(route, [
          {
            text: "Add Hotel Ume, 2 nights, 13 to 15 Nov (ref 8812, booked on Agoda) to your Tokyo trip?",
            buttons: [[{ label: "Confirm", data: "hitl:t:y" }, { label: "Cancel", data: "hitl:t:n" }]],
          },
        ]);
      }
      return json(route, [
        {
          text: "Delete 2026-09-27 · -25.00 SGD · Grab?",
          buttons: [
            [
              { label: "Confirm", data: "hitl:x:y" },
              { label: "Cancel", data: "hitl:x:n" },
            ],
          ],
        },
      ]);
    }
    if (path === "/chat/press") {
      state.lastPress = body.data;
      if (body.data === "hitl:x:y")
        state.txs.find((t) => t.id === "t2")!.deleted = true;
      return json(route, [
        {
          text: body.data === "hitl:t:y" ? "Added Hotel Ume to your Tokyo trip." : body.data.endsWith("y") ? "Deleted." : "Cancelled.",
          buttons: [],
        },
      ]);
    }
    return json(route, { detail: `not faked: ${method} ${path}` }, 404);
  });
  // Google's map script: a stand-in that records the pins and lines the page draws
  // (window.__map), so no test ever reaches Google.
  await page.route("https://maps.googleapis.com/**", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `(() => {
        const log = (window.__map = { markers: [], lines: 0, circles: [], key: new URL(document.currentScript.src).searchParams.get("key") });
        // Holding the map: longPress(lat, lng) presses at that spot and lets go a little after the page's 550 ms.
        class Map {
          constructor(el) { el.dataset.map = "ready"; this.on = {}; log.longPress = (lat, lng) => {
            const at = { latLng: { lat: () => lat, lng: () => lng } };
            (this.on.mousedown || []).forEach((f) => f(at));
            setTimeout(() => (this.on.mouseup || []).forEach((f) => f(at)), 700);
          }; }
          fitBounds() {} setCenter() {} setZoom() {} panTo() {}
          addListener(e, f) { (this.on[e] = this.on[e] || []).push(f); }
        }
        class Circle { constructor(o) { this.o = o; log.circles.push(this); } setMap(m) { if (!m) log.circles = log.circles.filter((x) => x !== this); } }
        class Marker {
          constructor(o) { this.o = o; this.click = null; log.markers.push(this); }
          setMap(m) { if (!m) log.markers = log.markers.filter((x) => x !== this); }
          addListener(e, f) { this.click = f; }
        }
        class Polyline { constructor(o) { this.o = o; log.lines += 1; } setMap(m) { if (!m) log.lines -= 1; } }
        class LatLngBounds { extend() {} }
        const libraries = { maps: { Map, Polyline, Circle }, marker: { Marker }, core: { LatLngBounds, SymbolPath: { CIRCLE: 0 } } };
        window.google = { maps: { importLibrary: async (name) => libraries[name] } };
        window[new URL(document.currentScript.src).searchParams.get("callback")]();
      })();`,
    }),
  );
  // Telegram's scripts: the login widget is blanked; the Mini App script is a stub
  // that records what the app asked of it.
  await page.route("https://telegram.org/**", (route) =>
    route.request().url().endsWith("/telegram-web-app.js")
      ? route.fulfill({
          contentType: "text/javascript",
          body: `window.tgCalls = [];
        window.Telegram = { WebApp: {
          ready: () => tgCalls.push("ready"), expand: () => tgCalls.push("expand"),
          setHeaderColor: (c) => tgCalls.push("header " + c), setBackgroundColor: (c) => tgCalls.push("bg " + c),
        } };`,
        })
      : route.fulfill({ status: 200, body: "" }),
  );

  return state;
}

/** "25 Sep" for 2026-09-25. */
function shortDay(day: string): string {
  const [, month, date] = day.split("-").map(Number);
  return `${date} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month - 1]}`;
}

function mk(
  id: string,
  direction: "in" | "out" | "move",
  amount: string,
  counterparty: string | null,
  category: string | null,
): Tx {
  return {
    id,
    direction,
    amount: { amount: Number(amount).toFixed(4), currency: "SGD" },
    occurred_at: "2026-09-27T04:00:00Z",
    counterparty,
    category_id: category,
    notes: null,
    status: "confirmed",
    source: "manual",
    deleted: false,
  };
}
