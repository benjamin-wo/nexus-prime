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
};

/** An in-memory stand-in for the API, so journeys exercise the real UI in a browser. */
export async function fakeApi(page: Page, { signedIn = true, emailConnected = false, forwarding = false } = {}) {
  let session = signedIn;
  type FakeBudget = { id: string; category_id: string | null; limit: number; spent: number };
  type FakeBill = {
    id: string;
    name: string;
    amount: { amount: string; currency: string } | null;
    cadence: string;
    due: string;
    days_until: number;
    snoozed: boolean;
  };
  type FakeRule = { id: string; pattern: string; category_id: string; category_name: string; explanation: string };
  type FakeSalary = { rule: string; day: number | null; anchor: string | null; usual: string | null };
  const state: {
    txs: Tx[];
    lastPress?: string;
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
              transaction_id: null,
              actionable: true,
            },
          ]
        : [],
    },
  };
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
      if (method === "PUT") state.frequency = body.frequency;
      const options = {
        instant: "as it happens",
        hourly: "every hour (8am to 9pm)",
        thrice_daily: "3 times a day (9am, 2pm, 8pm)",
        daily: "once a day at 9pm",
        off: "off",
      };
      const description =
        state.frequency === "off"
          ? "Transaction updates are off."
          : state.frequency === "instant"
            ? "You get a message for each transaction as it happens."
            : `You get a summary of your transactions ${options[state.frequency as keyof typeof options]}.`;
      return json(route, { frequency: state.frequency, description, options });
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
      if (action === "/snooze") state.bills = state.bills.map((b) => (b.id === id ? { ...b, snoozed: true } : b));
      else state.bills = state.bills.filter((b) => b.id !== id); // paid (one-off) or removed
      return route.fulfill({ status: 204 });
    }
    if (path === "/ious") {
      return json(route, [
        {
          split_id: "s1",
          transaction_id: "t9",
          participant_name: "Ann",
          share: { amount: "30.0000", currency: "SGD" },
          outstanding: { amount: "20.0000", currency: "SGD" },
          expense_occurred_at: "2026-09-20T12:00:00Z",
        },
      ]);
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
    if (path === "/transactions" && method === "GET") {
      const direction = url.searchParams.get("direction");
      const items = live().filter(
        (t) => !direction || t.direction === direction,
      );
      return json(route, { items, total: items.length });
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
    if (path === "/chat") {
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
          text: body.data.endsWith("y") ? "Deleted." : "Cancelled.",
          buttons: [],
        },
      ]);
    }
    return json(route, { detail: `not faked: ${method} ${path}` }, 404);
  });
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
