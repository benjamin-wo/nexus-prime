import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me, Page, Setup } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { GetStarted } from "./GetStarted";

const base: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore", telegram_linked: false },
  csrf_token: "csrf",
};
const meWith = (over: Partial<Me["user"]> = {}): Me => ({ ...base, user: { ...base.user, ...over } });

/** `GET /api/setup` as the server answers it: four items, of which the card reads the budget and the receipts. */
const setupOf = (done: { budget?: boolean; receipts?: boolean } = {}, dismissed = false): Setup => ({
  dismissed,
  items: [
    { key: "payday", label: "Set your payday", done: false, link: "/accounting/budgets", ask: "Help me set my payday" },
    { key: "receipts", label: "Get receipts in automatically", done: done.receipts === true, link: "/settings/email", ask: "Help me" },
    { key: "investments", label: "Add your stocks", done: false, link: "/investment", ask: "Help me add my stocks" },
    { key: "budget", label: "Set a monthly budget", done: done.budget === true, link: "/accounting/budgets", ask: "Help me set a monthly budget" },
  ],
});
const page = (total: number): Page => ({ items: [], total });

function serve({ entries = 0, setup = setupOf() as Setup | Response } = {}) {
  return mockApi({
    "GET /config": () => ({ bot_username: "made_up_bot" }),
    "GET /transactions": () => page(entries),
    "GET /setup": () => setup,
  });
}

const show = (me: Me) => renderWithProviders(<GetStarted me={me} />);
const card = () => screen.findByRole("region", { name: "Get started" });
const stepOf = (name: string) => screen.getByText(name).closest("li") as HTMLElement;
const urls = () => vi.mocked(fetch).mock.calls.map(([url]) => String(url));
const settle = () => new Promise((r) => setTimeout(r, 30));

afterEach(() => vi.restoreAllMocks());

describe("GetStarted: each step's state", () => {
  it("a brand-new person has all four to do, each with its action, in order", async () => {
    serve();
    show(meWith());
    const region = await card();
    expect(within(region).getByText("0 of 4")).toBeInTheDocument();
    const rows = within(region).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".wrap")?.textContent)).toEqual([
      "Connect Telegram",
      "Log your first expense",
      "Set a monthly budget",
      "Get receipts in automatically",
    ]);
    for (const row of rows) expect(row).toHaveTextContent("To do");
    expect(within(stepOf("Connect Telegram")).getByRole("link", { name: /Open the bot/ })).toHaveAttribute("href", "https://t.me/made_up_bot");
    expect(within(stepOf("Log your first expense")).getByRole("button", { name: /Log one/ })).toBeInTheDocument();
    expect(within(stepOf("Set a monthly budget")).getByRole("link", { name: /Set one/ })).toHaveAttribute("href", "/accounting/budgets");
    expect(within(stepOf("Get receipts in automatically")).getByRole("link", { name: /Connect/ })).toHaveAttribute("href", "/settings/email");
    expect(region).toHaveTextContent("Log in Telegram or the chat button; review here.");
  });

  it("a linked Telegram chat ticks the first step and drops its action", async () => {
    serve();
    show(meWith({ telegram_linked: true }));
    const region = await card();
    expect(within(region).getByText("1 of 4")).toBeInTheDocument();
    expect(stepOf("Connect Telegram")).toHaveTextContent("Done");
    expect(within(stepOf("Connect Telegram")).queryByRole("link")).toBeNull();
    expect(stepOf("Log your first expense")).toHaveTextContent("To do");
  });

  it("any transaction ticks the second step", async () => {
    serve({ entries: 3 });
    show(meWith());
    await card();
    await waitFor(() => expect(stepOf("Log your first expense")).toHaveTextContent("Done"));
    expect(within(stepOf("Log your first expense")).queryByRole("button")).toBeNull();
    expect(stepOf("Connect Telegram")).toHaveTextContent("To do");
  });

  it("a budget ticks the third step", async () => {
    serve({ setup: setupOf({ budget: true }) });
    show(meWith());
    await card();
    expect(stepOf("Set a monthly budget")).toHaveTextContent("Done");
    expect(within(stepOf("Set a monthly budget")).queryByRole("link")).toBeNull();
    expect(stepOf("Get receipts in automatically")).toHaveTextContent("To do");
  });

  it("a connected email ticks the fourth step", async () => {
    serve({ setup: setupOf({ receipts: true }) });
    show(meWith());
    await card();
    expect(stepOf("Get receipts in automatically")).toHaveTextContent("Done");
    expect(within(stepOf("Get receipts in automatically")).queryByRole("link")).toBeNull();
    expect(stepOf("Set a monthly budget")).toHaveTextContent("To do");
  });

  it("asks for only one entry, to know whether there is one", async () => {
    serve();
    show(meWith());
    await card();
    expect(urls()).toContain("/api/transactions?limit=1");
  });

  it("Log one brings the person to the Ask anything box", async () => {
    serve();
    const input = document.createElement("input");
    input.id = "ask-input";
    input.scrollIntoView = vi.fn();
    document.body.append(input);
    show(meWith());
    await card();
    await userEvent.setup().click(within(stepOf("Log your first expense")).getByRole("button", { name: /Log one/ }));
    expect(input).toHaveFocus();
    expect(input.scrollIntoView).toHaveBeenCalled();
    input.remove();
  });
});

describe("GetStarted: when it shows", () => {
  it("is not there once all four are done", async () => {
    serve({ entries: 2, setup: setupOf({ budget: true, receipts: true }) });
    show(meWith({ telegram_linked: true }));
    await waitFor(() => expect(urls()).toEqual(expect.arrayContaining(["/api/setup", "/api/transactions?limit=1"])));
    await settle();
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
  });

  it("is not there for a demo, and asks for nothing", async () => {
    const calls = serve();
    show({ ...meWith(), demo: { expires_at: "2026-11-06T00:00:00Z", messages_left: 5 } });
    await settle();
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
    expect(calls).toHaveLength(0);
  });

  it("is not there once it was put away (the same dismissal the old checklist had), on any device", async () => {
    serve({ setup: setupOf({}, true) });
    show(meWith());
    await waitFor(() => expect(urls()).toContain("/api/setup"));
    await settle();
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
  });

  it("stays out when what it needs can't be loaded, rather than show steps that may not be true", async () => {
    serve({ setup: new Response("{}", { status: 403 }) });
    show(meWith());
    await settle();
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
    vi.restoreAllMocks();
    mockApi({
      "GET /config": () => ({ bot_username: "made_up_bot" }),
      "GET /transactions": () => new Response("{}", { status: 500 }),
      "GET /setup": () => setupOf(),
    });
    show(meWith());
    await settle();
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
  });
});

describe("GetStarted: Hide", () => {
  it("puts the guide away for good with the setup dismissal, and asks the server again", async () => {
    let dismissed = false;
    const calls = mockApi({
      "GET /config": () => ({ bot_username: "made_up_bot" }),
      "GET /transactions": () => page(0),
      "GET /setup": () => setupOf({}, dismissed),
      "POST /setup/dismiss": () => {
        dismissed = true;
        return new Response(null, { status: 204 });
      },
    });
    show(meWith());
    await card();
    await userEvent.setup().click(screen.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Get started" })).toBeNull());
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/setup/dismiss"]);
    expect(calls.filter((c) => c.path === "/setup")).toHaveLength(2);
  });

  it("says so, and stays, when the save fails", async () => {
    mockApi({
      "GET /config": () => ({ bot_username: "made_up_bot" }),
      "GET /transactions": () => page(0),
      "GET /setup": () => setupOf(),
      "POST /setup/dismiss": () => new Response(JSON.stringify({ detail: "Try again in a minute" }), { status: 429 }),
    });
    show(meWith());
    await card();
    await userEvent.setup().click(screen.getByRole("button", { name: "Hide" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in a minute");
    expect(screen.getByRole("region", { name: "Get started" })).toBeInTheDocument();
  });
});
