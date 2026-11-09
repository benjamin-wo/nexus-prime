import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Me } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Settings, SettingsSection, TimeZoneSection } from "./Settings";

const me = (user: Partial<Me["user"]> = {}): Me => ({
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore", home_timezone: "Asia/Singapore", timezone_source: "home", timezone_set_at: null, ...user },
  csrf_token: "c",
});

const demoMe = (): Me => ({ ...me({ role: "member" }), demo: { expires_at: "2026-11-05T00:00:00Z", messages_left: 5 } });

const connected = {
  connections: [{ id: "m1", address: "me@example.com", kind: "gmail", status: "ok", last_checked_at: null, last_error: null }],
  emails: [
    { id: "e1", status: "pending" },
    { id: "e2", status: "logged" },
  ],
};

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

/** Settings and its pages, routed as the app routes them. Returns the client, to look at the cache. */
function renderSettings(who: Me, at = "/settings") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/settings" element={<Settings me={who} />} />
          <Route path="/settings/:slug" element={<SettingsSection me={who} />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

const rowNames = () => screen.getAllByRole("link").map((l) => l.querySelector(".set-row-title")?.textContent);
const row = (name: string) => screen.getByRole("link", { name: new RegExp(`^${name}`) });

describe("Settings", () => {
  it("is a short list: Preferences first, then Notifications, Connections and Your data", () => {
    mockApi({});
    renderSettings(me());
    expect(screen.getByRole("heading", { name: "Settings", level: 1 })).toBeInTheDocument();
    expect([...document.querySelectorAll("h2.section-title")].map((h) => h.textContent)).toEqual([
      "Preferences",
      "Notifications",
      "Connections",
      "Your data",
    ]);
    expect(rowNames()).toEqual([
      "Telegram updates",
      "Time zone",
      "Shared trips",
      "Notifications",
      "How Kaya talks",
      "Receipts by email",
      "Import a statement",
      "Categories",
      "Wallets",
      "Category rules",
      "What Kaya remembers",
      "Download or delete",
      "Model costs",
    ]);
    // Nothing is expanded: no forms on the list itself.
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("links each row to its own page, keeping the pages that already had an address", () => {
    mockApi({});
    renderSettings(me());
    const href = (name: string) => row(name).getAttribute("href");
    expect(href("Telegram updates")).toBe("/settings/updates");
    expect(href("Time zone")).toBe("/settings/time-zone");
    expect(href("Shared trips")).toBe("/settings/shared-trips");
    expect(href("Notifications")).toBe("/settings/notifications");
    expect(href("How Kaya talks")).toBe("/settings/voice");
    expect(href("Receipts by email")).toBe("/settings/email");
    expect(href("Import a statement")).toBe("/settings/import");
    expect(href("Categories")).toBe("/settings/categories");
    expect(href("Wallets")).toBe("/settings/wallets");
    expect(href("Category rules")).toBe("/settings/rules");
    expect(href("What Kaya remembers")).toBe("/settings/memory");
    expect(href("Download or delete")).toBe("/settings/data");
    expect(href("Model costs")).toBe("/settings/costs");
  });

  it("hides Receipts by email, Shared trips and Model costs from a demo account", () => {
    mockApi({});
    renderSettings(demoMe());
    expect(rowNames()).not.toContain("Receipts by email");
    expect(rowNames()).not.toContain("Shared trips");
    expect(rowNames()).not.toContain("Model costs");
    expect(rowNames()).toContain("Wallets");
  });

  it("shows Model costs to the owner only", () => {
    mockApi({});
    renderSettings(me({ role: "member" }));
    expect(rowNames()).not.toContain("Model costs");
    expect(rowNames()).toContain("Receipts by email");
  });

  it("says the current value on the rows that can, from a few cheap reads", async () => {
    const calls = mockApi({
      "GET /notifications": () => ({
        frequency: "daily",
        daily_at: "21:00",
        description: "",
        options: { instant: "as it happens", hourly: "every hour", thrice_daily: "3 times a day", daily: "once a day at 9pm", off: "off" },
      }),
      "GET /wallets": () => [
        { id: "w1", name: "Main account", kind: "spending", match_words: [] },
        { id: "w2", name: "Cash", kind: "cash", match_words: [] },
        { id: "w3", name: "Savings", kind: "savings", match_words: [] },
      ],
      "GET /trip-alerts": () => ({ enabled: true }),
      "GET /email": () => connected,
    });
    renderSettings(me());
    expect(await within(row("Telegram updates")).findByText("Daily at 9pm")).toBeInTheDocument();
    expect(await within(row("Wallets")).findByText("3 wallets")).toBeInTheDocument();
    expect(await within(row("Shared trips")).findByText("On")).toBeInTheDocument();
    expect(await within(row("Receipts by email")).findByText("me@example.com · 1 waiting")).toBeInTheDocument();
    expect(within(row("Time zone")).getByText("Singapore · UTC+8")).toBeInTheDocument();
    // The rows with nothing cheap to say stay bare, and only four reads are made.
    expect(row("Category rules").querySelector(".set-row-value")).toBeNull();
    expect(calls.map((c) => c.path).sort()).toEqual(["/email", "/notifications", "/trip-alerts", "/wallets"]);
  });

  it("shows no value for a row whose read fails", async () => {
    const calls = mockApi({ "GET /wallets": () => new Response("{}", { status: 500 }) });
    renderSettings(me());
    await waitFor(() => expect(calls.some((c) => c.path === "/wallets")).toBe(true));
    expect(row("Wallets").querySelector(".set-row-value")).toBeNull();
  });

  it("skips the reads that are not for a demo account", async () => {
    const calls = mockApi({ "GET /notifications": () => new Response("{}", { status: 500 }), "GET /wallets": () => [] });
    renderSettings(demoMe());
    await waitFor(() => expect(calls.some((c) => c.path === "/wallets")).toBe(true));
    expect(calls.map((c) => c.path)).not.toContain("/email");
    expect(calls.map((c) => c.path)).not.toContain("/trip-alerts");
  });

  it("opens a section on its own page, with a way back", async () => {
    mockApi({ "GET /wallets": () => [], "GET /wallets/likely-moves": () => [] });
    renderSettings(me());
    await userEvent.click(row("Wallets"));
    expect(screen.getByTestId("where")).toHaveTextContent("/settings/wallets");
    expect(screen.getByRole("heading", { name: "Wallets", level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Wallets" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Time zone" })).toBeNull();
    await userEvent.click(screen.getByRole("link", { name: "Back to Settings" }));
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/settings$/);
    expect(screen.getByRole("heading", { name: "Settings", level: 1 })).toBeInTheDocument();
  });

  it("opens the time zone, with its form, at /settings/time-zone", () => {
    mockApi({});
    renderSettings(me(), "/settings/time-zone");
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/settings");
    expect(within(screen.getByRole("region", { name: "Time zone" })).getByRole("button", { name: "Change" })).toBeInTheDocument();
  });

  it("sends an address that isn't a section back to the list", () => {
    mockApi({});
    renderSettings(me(), "/settings/nonsense");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/settings$/);
  });

  it("keeps Shared trips off a demo account's address too", () => {
    mockApi({});
    renderSettings(demoMe(), "/settings/shared-trips");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/settings$/);
  });
});

describe("Track which card paid", () => {
  const sw = () => screen.getByRole("switch", { name: "Track which card paid" });

  it("is a switch with its explanation, off while /me says nothing", () => {
    mockApi({});
    renderSettings(me());
    expect(sw()).not.toBeChecked();
    expect(sw()).toHaveAccessibleDescription("Off keeps logging simple. On adds a Paid with field to expenses.");
  });

  it("starts on when /me says so", () => {
    mockApi({});
    renderSettings({ ...me(), preferences: { track_cards: true } });
    expect(sw()).toBeChecked();
  });

  it("saves on toggle and refreshes the cached /me so the rest of the app follows", async () => {
    let on = false;
    const calls = mockApi({
      "PUT /settings/preferences": (body) => {
        on = (body as { track_cards: boolean }).track_cards;
        return { track_cards: on };
      },
      "GET /me": () => ({ ...me(), preferences: { track_cards: on } }),
    });
    const client = renderSettings(me());
    client.setQueryData(["me"], me());
    await userEvent.click(sw());
    expect(sw()).toBeChecked();
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ track_cards: true }));
    await waitFor(() => expect(client.getQueryData<Me>(["me"])?.preferences).toEqual({ track_cards: true }));
    await waitFor(() => expect(sw()).not.toBeDisabled());
    expect(sw()).toBeChecked();
    // And off again.
    await userEvent.click(sw());
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ track_cards: true }, { track_cards: false }]));
    await waitFor(() => expect(client.getQueryData<Me>(["me"])?.preferences).toEqual({ track_cards: false }));
    expect(sw()).not.toBeChecked();
  });

  it("goes back and says why when the save fails", async () => {
    mockApi({ "PUT /settings/preferences": () => new Response(JSON.stringify({ detail: "Saving failed, try again" }), { status: 500 }) });
    const client = renderSettings(me());
    client.setQueryData(["me"], me());
    await userEvent.click(sw());
    expect(await screen.findByRole("alert")).toHaveTextContent("Saving failed, try again");
    expect(sw()).not.toBeChecked();
    expect(client.getQueryData<Me>(["me"])?.preferences).toBeUndefined();
  });

  it("goes back to on when turning it off fails", async () => {
    mockApi({ "PUT /settings/preferences": () => new Response(JSON.stringify({ detail: "Saving failed, try again" }), { status: 500 }) });
    renderSettings({ ...me(), preferences: { track_cards: true } });
    await userEvent.click(sw());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(sw()).toBeChecked();
  });
});

describe("Investing and Travel in the menu", () => {
  const invest = () => screen.getByRole("switch", { name: "Investing" });
  const travel = () => screen.getByRole("switch", { name: "Travel" });
  const prefs = (show_invest: boolean | null | undefined, show_travel: boolean | null | undefined) => ({
    ...me(),
    preferences: { track_cards: false, show_invest, show_travel },
  });

  it("are two switches with their explanations, off while not decided", () => {
    mockApi({});
    renderSettings(prefs(null, null));
    expect(invest()).not.toBeChecked();
    expect(travel()).not.toBeChecked();
    expect(invest()).toHaveAccessibleDescription("Portfolio, watchlist and trade plans in the menu");
    expect(travel()).toHaveAccessibleDescription("Trips and trip research in the menu");
  });

  it("are off while /me says nothing about them", () => {
    mockApi({});
    renderSettings(me());
    expect(invest()).not.toBeChecked();
    expect(travel()).not.toBeChecked();
  });

  it("start from /me: on when true, off when switched off", () => {
    mockApi({});
    renderSettings(prefs(true, false));
    expect(invest()).toBeChecked();
    expect(travel()).not.toBeChecked();
  });

  it("save only the one flipped, and update the cached /me", async () => {
    let state = { track_cards: false, show_invest: null as boolean | null, show_travel: null as boolean | null };
    const calls = mockApi({
      "PUT /settings/preferences": (body) => {
        state = { ...state, ...(body as object) };
        return state;
      },
      "GET /me": () => ({ ...me(), preferences: state }),
    });
    const client = renderSettings(prefs(null, null));
    client.setQueryData(["me"], prefs(null, null));
    await userEvent.click(invest());
    expect(invest()).toBeChecked();
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ show_invest: true }));
    await waitFor(() =>
      expect(client.getQueryData<Me>(["me"])?.preferences).toEqual({ track_cards: false, show_invest: true, show_travel: null }),
    );
    await waitFor(() => expect(invest()).not.toBeDisabled());
    expect(travel()).not.toBeChecked();
    // And Travel on, then Investing off again: false is sent, not null.
    await userEvent.click(travel());
    await waitFor(() => expect(travel()).toBeChecked());
    await waitFor(() => expect(travel()).not.toBeDisabled());
    await userEvent.click(invest());
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([
        { show_invest: true },
        { show_travel: true },
        { show_invest: false },
      ]),
    );
    await waitFor(() =>
      expect(client.getQueryData<Me>(["me"])?.preferences).toEqual({ track_cards: false, show_invest: false, show_travel: true }),
    );
    expect(invest()).not.toBeChecked();
    expect(travel()).toBeChecked();
  });

  it("go back and say why when the save fails, leaving the cached /me alone", async () => {
    mockApi({ "PUT /settings/preferences": () => new Response(JSON.stringify({ detail: "Saving failed, try again" }), { status: 500 }) });
    const client = renderSettings(prefs(null, true));
    client.setQueryData(["me"], prefs(null, true));
    await userEvent.click(invest());
    expect(await screen.findByRole("alert")).toHaveTextContent("Saving failed, try again");
    expect(invest()).not.toBeChecked();
    await userEvent.click(travel());
    await waitFor(() => expect(travel()).toBeChecked());
    expect(client.getQueryData<Me>(["me"])?.preferences).toEqual({ track_cards: false, show_invest: null, show_travel: true });
  });
});

describe("Time zone", () => {
  it("shows the time zone with where it came from, and Home when it differs", () => {
    mockApi({});
    renderWithProviders(<TimeZoneSection me={me({ timezone: "Europe/Madrid", timezone_source: "phone" })} />);
    const card = screen.getByRole("region", { name: "Time zone" });
    expect(within(card).getByTestId("time-zone-now")).toHaveTextContent(/^Madrid · UTC\+[12]$/);
    expect(card).toHaveTextContent("from your phone");
    expect(card).toHaveTextContent("Home: Singapore");
    expect(within(card).getByRole("button", { name: "Use home time" })).toBeInTheDocument();
  });

  it("hides Use home time and Home while on the home zone", () => {
    mockApi({});
    renderWithProviders(<TimeZoneSection me={me()} />);
    const card = screen.getByRole("region", { name: "Time zone" });
    expect(card).toHaveTextContent("Singapore · UTC+8");
    expect(card).not.toHaveTextContent("Home:");
    expect(within(card).queryByRole("button", { name: "Use home time" })).toBeNull();
  });

  it("sends a picked zone as a manual choice", async () => {
    const calls = mockApi({ "POST /me/timezone": () => ({ ...me({ timezone: "Asia/Tokyo", timezone_source: "chat" }), changed: true }) });
    renderWithProviders(<TimeZoneSection me={me()} />);
    const card = screen.getByRole("region", { name: "Time zone" });
    await userEvent.click(within(card).getByRole("button", { name: "Change" }));
    await userEvent.type(within(card).getByLabelText("Find a time zone"), "tokyo");
    await userEvent.selectOptions(within(card).getByRole("listbox", { name: "Time zone" }), "Asia/Tokyo");
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/me/timezone")?.body).toEqual({ timezone: "Asia/Tokyo", source: "manual" }));
    expect(await within(card).findByRole("status")).toHaveTextContent("Saved. Kaya now uses Tokyo time.");
  });

  it("goes back to the home zone", async () => {
    const calls = mockApi({ "POST /me/timezone/home": () => ({ ...me(), changed: true }) });
    renderWithProviders(<TimeZoneSection me={me({ timezone: "Europe/Madrid", timezone_source: "phone" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Use home time" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/me/timezone/home")).toBe(true));
    expect(await screen.findByRole("status")).toHaveTextContent("Back on home time, Singapore.");
  });

  it("shows the server's refusal and keeps the picker open", async () => {
    mockApi({ "POST /me/timezone": () => new Response(JSON.stringify({ detail: "unknown time zone" }), { status: 422 }) });
    renderWithProviders(<TimeZoneSection me={me()} />);
    const card = screen.getByRole("region", { name: "Time zone" });
    await userEvent.click(within(card).getByRole("button", { name: "Change" }));
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("unknown time zone");
    expect(within(card).getByRole("button", { name: "Save" })).toBeInTheDocument();
  });
});
