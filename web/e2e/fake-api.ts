import type { Page, Route } from "@playwright/test";

type Tx = {
  id: string;
  direction: "in" | "out";
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

export async function fakeApi(
  page: Page,
  {
    signedIn = true,
    emailConnected = false,
    forwarding = false,
    splitBill = false,
    twins = false,
    running = false,
    research = false,
    chatHistory = false,
  } = {},
) {
  let session = signedIn;
  type FakeBudget = { id: string; category_id: string | null; limit: number; spent: number };
  type FakeBill = {
    id: string;
    name: string;
    spending?: boolean;
    amount: { amount: string; currency: string } | null;
    cadence: string;
    due: string;
    days_until: number;
    snoozed: boolean;
  };
  type FakeRule = { id: string; pattern: string; category_id: string; category_name: string; explanation: string };
  type FakeSalary = { rule: string; day: number | null; anchor: string | null; usual: string | null };
  let annRepaid = false;
  let dailyAt = "21:00";
  const state: {
    txs: Tx[];
    lastPress?: string;
    chatSent: string[];
    runs: { id: string; status: string; progress: string; [key: string]: unknown }[];
    holdings: { symbol: string; quantity: string; average_cost: { amount: string; currency: string }; cost: { amount: string; currency: string }; updated_at: string }[];
    draft: Record<string, unknown> | null;
    screenshots: number;
    watching: string[];
    trips: Record<string, unknown>[];
    trades: Record<string, unknown>[];
    tripItems: string[];
    looseBookings: Record<string, unknown>[];
    movedBookings: string[];
    plans: Record<string, unknown>[];
    /** The browser key for the trip map; null: no map (as when it isn't set up). */
    mapKey: string | null;
    hopModes: string[];
    /** Moves sent from the trip page, as "id>day|places@after". */
    moves: string[];
    placeSearches: string[];
    ideaSearches: string[];
    photoChoices: string[];
    shares: Record<string, string>;
    shareCount: number;
    planStarted: boolean;
    planAlerts: boolean;
    cancelled: string[];
    budgets: FakeBudget[];
    bills: FakeBill[];
    salary: FakeSalary | null;
    rules: FakeRule[];
    imports: { id: string; file_name: string; added: number; created_at: string; undone_at: string | null }[];
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
    trips: [],
    shares: {},
    shareCount: 0,
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
    plans: [],
    mapKey: null,
    hopModes: [],
    moves: [],
    placeSearches: [],
    ideaSearches: [],
    photoChoices: [],
    planStarted: false,
    planAlerts: true,
    draft: null,
    screenshots: 0,
    txs: [
      { ...mk("t1", "out", "12.40", "Maxwell Food Centre", "food"), has_receipt: true },
      mk("t2", "out", "25.00", "Grab", null),
      mk("t3", "in", "4200.00", "Employer", null),
    ],
    budgets: [],
    bills: [],
    salary: null,
    rules: [],
    imports: [],
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
          ]
        : [],
    },
  };
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
  const categories = [
    { id: "food", name: "Dining Out", active: true },
    { id: "transport", name: "Transport", active: true },
  ];
  const categoryName = (id: string) => categories.find((c) => c.id === id)?.name ?? id;
  const live = () => state.txs.filter((t) => !t.deleted);
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
      return json(route, {
        user: {
          telegram_user_id: 1,
          role: "owner",
          home_currency: "SGD",
          timezone: "Asia/Singapore",
        },
        csrf_token: "csrf-1",
      });
    }
    if (method !== "GET" && request.headers()["x-csrf-token"] !== "csrf-1") {
      return json(route, { detail: "missing or wrong CSRF token" }, 403);
    }
    if (path === "/config")
      return json(route, { bot_username: "nexus_test_bot" });
    if (path === "/me") {
      if (!session) return json(route, { detail: "not signed in" }, 401);
      return json(route, {
        user: {
          telegram_user_id: 1,
          role: "owner",
          home_currency: "SGD",
          timezone: "Asia/Singapore",
        },
        csrf_token: "csrf-1",
      });
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
      // Made-up closes: NVDA has one, AAPL doesn't yet. 1 USD = 1.30 SGD.
      const closes: Record<string, [string, string]> = { NVDA: ["130.25", "128.00"] };
      const sgd = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
      let total = 0;
      let gain = 0;
      const missing: string[] = [];
      const holdings = state.holdings.map((h) => {
        const close = closes[h.symbol];
        if (!close) {
          missing.push(h.symbol);
          return { ...h, price: null, price_day: null, value: null, gain: null, gain_percent: null, day_change: null, day_percent: null, value_home: null, earnings: null };
        }
        const value = Number(h.quantity) * Number(close[0]);
        const up = value - Number(h.cost.amount);
        total += value * 1.3;
        gain += up * 1.3;
        return {
          ...h,
          price: usd(close[0]),
          price_day: "2026-09-25",
          value: usd(value.toFixed(4)),
          gain: usd(up.toFixed(4)),
          gain_percent: ((up / Number(h.cost.amount)) * 100).toFixed(2),
          day_change: usd((Number(h.quantity) * (Number(close[0]) - Number(close[1]))).toFixed(4)),
          day_percent: "1.76",
          value_home: sgd(value * 1.3),
          earnings: { day: "2026-10-29", timing: "after close" },
        };
      });
      const priced = holdings.length > missing.length;
      return json(route, {
        holdings,
        totals: {
          value: priced ? sgd(total) : null,
          cost: priced ? sgd(total - gain) : null,
          gain: priced ? sgd(gain) : null,
          gain_percent: priced ? ((gain / (total - gain)) * 100).toFixed(2) : null,
          day_change: null,
          day_percent: null,
          as_of: priced ? "2026-09-25" : null,
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
    if (path === "/investments/watchlist" && method === "GET") {
      return json(route, {
        stocks: state.watching.map((symbol) => ({
          symbol,
          price: symbol === "AMD" ? "129.50" : null,
          price_day: symbol === "AMD" ? "2026-09-25" : null,
          day_percent: symbol === "AMD" ? "0.39" : null,
          earnings: null,
        })),
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
      return json(route, state.planStarted ? [{ ...PLAN_BRIEF, alerts: state.planAlerts }, FINISHED_PLAN] : [FINISHED_PLAN]);
    }
    if (path === "/investments/plans/p1/alerts" && method === "POST") {
      state.planAlerts = Boolean(body.on);
      return route.fulfill({ status: 204 });
    }
    if (path === "/investments/plans/p1" && method === "GET") {
      const closes = Array.from({ length: 60 }, (_, i) => ({
        day: new Date(Date.UTC(2026, 6, 28 + i)).toISOString().slice(0, 10),
        close: (100 + i * 0.5).toFixed(2),
      }));
      return json(route, {
        brief: { ...PLAN_BRIEF, alerts: state.planAlerts },
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
      const known: Record<string, [string, string]> = { tokyo: ["JPY", "Japan"], osaka: ["JPY", "Japan"], seoul: ["KRW", "South Korea"], bali: ["IDR", "Indonesia"] };
      const hit = Object.entries(known).find(([k]) => place.startsWith(k));
      return json(route, hit ? { currency: hit[1][0], country: hit[1][1] } : { currency: null, country: null });
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
    const tripDetail = (trip: Record<string, unknown>) => {
      const items = [
        { transaction_id: "k1", day: "2026-09-28", counterparty: "Ichiran", category: "Dining Out", amount: { amount: "2000.0000", currency: "JPY" }, home: home(18), linked: false },
        { transaction_id: "k2", day: "2026-08-01", counterparty: "Air ticket", category: "Travel", amount: home(800), home: home(800), linked: true },
      ].filter((i) => state.tripItems.includes(i.transaction_id));
      const spent = items.reduce((total, i) => total + Number(i.home.amount), 0);
      const budget = trip.budget as { amount: string } | null;
      return {
        trip,
        spending: {
          spent: home(spent),
          left: budget ? home(Number(budget.amount) - spent) : null,
          percent: budget ? Math.floor((spent * 100) / Number(budget.amount)) : null,
          before: home(state.tripItems.includes("k2") ? 800 : 0),
          today: null,
          per_day: null,
          per_day_left: null,
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
        owed: [{ name: "Ann", amounts: [{ amount: "15000.0000", currency: "JPY" }], home: home(135) }],
        items,
        bookings: [{ ...FLIGHT, trip_id: trip.id }, ...state.plans],
        booked: home(820),
        booked_unlogged: home(820),
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
        to_spend: budget ? home(Number(budget.amount) - spent - 820) : null,
        days: (() => {
          const all = [FLIGHT, ...state.plans];
          const landings = all.flatMap((b) => legsOf(b).map((s) => s.arrives?.slice(0, 10) ?? "")).filter(Boolean);
          const days = [...new Set([...all.filter((b) => b.scheduled).map((b) => String(b.starts)), ...landings])].sort();
          return days.map((day) => {
            const entries = dayEntries(all, day);
            return { day, order: entries.map((b) => b.id), notes: notesFor(entries, day) };
          });
        })(),
        places_order: placesInOrder().map((p) => p.id),
        places: true,
        ideas: true,
        routes: state.mapKey !== null,
        map_key: state.mapKey,
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
        lat: 37.5651, lng: 126.9895,
        closed: 4,
      },
      fakePlaceMarket01: {
        id: "fakePlaceMarket01", name: "Namdaemun Market", address: "21 Example-gil, Jung-gu, Seoul", kind: "Market",
        rating: "4.3", ratings: 18000, price: null, maps_url: "https://maps.example/market", website: null, phone: null,
        summary: null, status: "OPERATIONAL", hours: [], reviews: [], lat: 37.5592, lng: 126.9776, closed: null,
      },
    };
    PLACES.fakePlaceLodge001 = {
      id: "fakePlaceLodge001", name: "Hill Lodge", address: "3 Example Cove", kind: "Hotel", rating: "4.5", ratings: 1576, price: null,
      maps_url: "https://maps.example/lodge", website: null, phone: null, summary: null, status: "OPERATIONAL", hours: [], reviews: [],
      lat: 41.93, lng: 3.21, closed: null,
    };
    PLACES.fakePlaceAirport1 = {
      id: "fakePlaceAirport1", name: "Exampleton Airport", address: "Exampleton", kind: "International airport", rating: null, ratings: null,
      price: null, maps_url: "https://maps.example/airport", website: null, phone: null, summary: null, status: "OPERATIONAL", hours: [],
      reviews: [], lat: 41.29, lng: 2.07, closed: null,
    };
    const placeOut = ({ closed: _closed, ...place }: Record<string, unknown>) => place;
    if (path === "/travel/places/search" && method === "GET") {
      state.placeSearches.push(url.searchParams.get("q") ?? "");
      return json(route, Object.values(PLACES).map(placeOut));
    }
    // Made-up ideas from made-up articles: one matched to Google Maps, one not.
    const tripIdeas = path.match(/^\/travel\/trips\/([^/]+)\/ideas$/);
    if (tripIdeas && method === "GET") {
      const q = url.searchParams.get("q") ?? "";
      state.ideaSearches.push(q);
      const trip = state.trips.find((t) => t.id === tripIdeas[1]);
      return json(route, {
        query: q,
        destination: trip?.destination ?? "",
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
      const hops = stops.slice(1).map((end, n) => {
        const start = stops[n];
        return {
          start_id: start.id, end_id: end.id, start: start.title, end: end.title, mode: "walk", minutes: 14, metres: 944, tight: false,
          directions: `https://www.google.com/maps/dir/?api=1&origin_place_id=${String(start.place_id)}&destination_place_id=${String(end.place_id)}`,
        };
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
      const others = [FLIGHT, ...state.plans.filter((p) => p !== moving)];
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
      state.plans = state.plans.map((p) => (p.id === placeLink[1] ? { ...p, place_id: body.place_id ?? null } : p));
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
      if (method === "DELETE") {
        state.trips = state.trips.filter((t) => t !== trip);
        return route.fulfill({ status: 204 });
      }
    }
    // A trip's read-only link. Tokens are made up, in the real ones' shape.
    const tripShare = path.match(/^\/travel\/trips\/([^/]+)\/share$/);
    if (tripShare) {
      const id = tripShare[1];
      if (!state.trips.some((t) => t.id === id)) return json(route, { detail: "no trip with that id" }, 404);
      if (method === "DELETE") {
        delete state.shares[id];
        return route.fulfill({ status: 204 });
      }
      if (method === "POST" && (!state.shares[id] || body.renew)) {
        state.shareCount += 1;
        state.shares[id] = `fakeShare${String(state.shareCount).padStart(4, "0")}`.padEnd(43, "x");
      }
      return json(route, { token: state.shares[id] ?? null });
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
      return json(route, {
        destination: trip.destination,
        start: trip.start,
        end: trip.end,
        days: trip.days,
        status: trip.status,
        days_until: trip.days_until,
        day_number: trip.day_number,
        day_labels: trip.day_labels,
        photo: trip.photo && !trip.photo_off ? { ...(trip.photo as object), url: `/api/shared/trips/${shared[1]}/photo` } : null,
        bookings: (detail.bookings as Record<string, unknown>[]).filter((b) => b.scheduled).map((b) => Object.fromEntries(keep.map((k) => [k, b[k] ?? null]))),
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
      return json(route, [
        { department: "accounting", kind: "email", text: "2 receipts from email waiting for you", link: "/accounting/email", urgent: false },
        { department: "accounting", kind: "bill", text: "Rent (SGD 1,800.00) due tomorrow", link: "/accounting/plan", urgent: false },
      ]);
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
        areas: [{ name: "Shinjuku", why: "Central, with late food.", things: ["Gyoen garden"], source: 1 }],
        getting_around: "An IC card covers city trains.",
        getting_around_source: 1,
        sources: [
          { id: 1, url: "https://guide.example.com/tokyo", title: "Tokyo guide", checked_on: "2026-09-28" },
          { id: 2, url: "https://flights.example.com/s", title: "Google Flights", checked_on: "2026-09-28" },
        ],
        estimate_low: "4602",
        estimate_high: "6760",
        estimate_lines: ["Return flights SIN-NRT: 2,400 to 3,200 SGD"],
        budget: "6800",
        paydays_left: 3,
        set_aside: "2267",
        fits: true,
        trip_id: null,
      });
    }
    if (path === "/travel/research/rs1/trip" && method === "POST") {
      const trip = {
        id: "trip9", destination: "Tokyo", start: "2027-01-10", end: "2027-01-17", days: 8, currency: "JPY",
        budget: { amount: "6800.0000", currency: "SGD" }, companions: [], set_aside: { amount: "2267.0000", currency: "SGD" },
        planned: {}, status: "upcoming", days_until: 104, day_number: null, notes: null, day_labels: {},
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
    if (path === "/summary") {
      const out = live().filter((t) => t.direction === "out");
      const total = out.reduce((s, t) => s + Number(t.amount.amount), 0);
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
    if (path === "/notifications") {
      if (method === "PUT") {
        state.frequency = body.frequency;
        if (body.daily_at) dailyAt = body.daily_at;
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
      return json(route, { frequency: state.frequency, daily_at: dailyAt, description, options });
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
        amount: body.amount ? { amount: Number(body.amount).toFixed(4), currency: "SGD" } : null,
        cadence: body.cadence,
        due: body.due,
        days_until: Math.round((Date.parse(body.due) - Date.parse("2026-09-28")) / 86_400_000),
        snoozed: false,
      };
      state.bills.push(bill);
      return json(route, bill, 201);
    }
    const billAction = path.match(/^\/bills\/([^/]+)(\/paid|\/snooze)?$/);
    if (billAction && method !== "GET") {
      const [, id, action] = billAction;
      const marked = state.bills.find((b) => b.id === id);
      if (action === "/snooze") state.bills = state.bills.map((b) => (b.id === id ? { ...b, snoozed: true } : b));
      else state.bills = state.bills.filter((b) => b.id !== id); // paid (one-off) or removed
      if (action === "/paid") {
        const amount = (body as { amount?: string | null } | null)?.amount;
        if (marked?.spending === false) {
          return json(route, { message: "Marked it as done. It doesn't count as spending, so nothing was logged.", logged: false, needs_amount: false });
        }
        return json(route, {
          message: amount ? `Marked it as paid and logged SGD ${amount} in this month's spending.` : "Marked it as paid.",
          logged: Boolean(amount),
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
    const emailAction = path.match(/^\/email\/(e\d+)\/(log|skip)$/);
    if (emailAction && method === "POST") {
      const email = state.email.emails.find((e) => e.id === emailAction[1])!;
      Object.assign(email, emailAction[2] === "log"
        ? { status: "logged", transaction_id: "t9", actionable: false }
        : { status: "skipped", reason: "you skipped it" });
      return route.fulfill({ status: 204 });
    }
    if (path === "/categories" && method === "GET") {
      const all = url.searchParams.get("include_inactive") === "true";
      return json(route, all ? categories : categories.filter((c) => c.active));
    }
    if (path === "/categories" && method === "POST") {
      const name = String(body.name).trim();
      if (categories.some((c) => c.name.toLowerCase() === name.toLowerCase()))
        return json(route, { detail: "a category with that name already exists" }, 409);
      const created = { id: `c${categories.length + 1}`, name, active: true };
      categories.push(created);
      return json(route, created, 201);
    }
    const categoryMerge = path.match(/^\/categories\/([\w-]+)\/merge$/);
    if (categoryMerge && method === "POST") {
      const source = categories.find((c) => c.id === categoryMerge[1])!;
      const into = categories.find((c) => c.id === body.into_id)!;
      source.active = false;
      let moved = 0;
      for (const tx of state.txs) if (tx.category_id === source.id) { tx.category_id = into.id; moved++; }
      return json(route, { moved, into });
    }
    const categoryEdit = path.match(/^\/categories\/([\w-]+)$/);
    if (categoryEdit && method === "PATCH") {
      const category = categories.find((c) => c.id === categoryEdit[1])!;
      Object.assign(category, body);
      return json(route, category);
    }
    if (path === "/imports/pdf" && method === "POST") {
      if (body.password !== "secret") {
        return json(route, { needs_password: true, wrong_password: Boolean(body.password), csv: null, layout: null, kind: null, rows: 0, reconciles: null });
      }
      return json(route, {
        needs_password: false, wrong_password: false, kind: "card", rows: 2, reconciles: true,
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
            category: readable ? (amount < 0 ? "Other" : "Income") : null,
            problem: readable ? null : "can't read the date",
            matches: cells[1] === "Grab" ? { date: "2026-09-28", description: "Grab", amount: "25.00" } : null,
          };
        }),
      });
    }
    if (path === "/imports" && method === "POST") {
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
        const log = (window.__map = { markers: [], lines: 0, key: new URL(document.currentScript.src).searchParams.get("key") });
        class Map { constructor(el) { el.dataset.map = "ready"; } fitBounds() {} setCenter() {} setZoom() {} panTo() {} }
        class Marker {
          constructor(o) { this.o = o; this.click = null; log.markers.push(this); }
          setMap(m) { if (!m) log.markers = log.markers.filter((x) => x !== this); }
          addListener(e, f) { this.click = f; }
        }
        class Polyline { constructor(o) { this.o = o; log.lines += 1; } setMap(m) { if (!m) log.lines -= 1; } }
        class LatLngBounds { extend() {} }
        const libraries = { maps: { Map, Polyline }, marker: { Marker }, core: { LatLngBounds, SymbolPath: { CIRCLE: 0 } } };
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

function mk(
  id: string,
  direction: "in" | "out",
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
