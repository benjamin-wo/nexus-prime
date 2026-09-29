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
export async function fakeApi(page: Page, { signedIn = true } = {}) {
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
  };
  const categories = [
    { id: "food", name: "Food & Drink", active: true },
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
            category_name: "Food & Drink",
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
          name: b.category_id ? "Food & Drink" : "Overall",
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
    if (path === "/categories") return json(route, categories);
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
      return json(route, { text: "It's in Food & Drink because that was chosen for it, not by a rule." });
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
