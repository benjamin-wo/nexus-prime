import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Mover, Today } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { TodayCard, whyError } from "./TodayCard";

const mover = (symbol: string, over: Partial<Mover> = {}): Mover => ({
  symbol,
  held: true,
  price: "131.50",
  day_percent: "0.96",
  price_kind: "live",
  price_at: "2026-09-28T14:41:00Z",
  price_day: "2026-09-28",
  headline: null,
  ...over,
});
const today = (over: Partial<Today> = {}): Today => ({
  session: "live",
  day: "2026-09-28",
  change: { amount: "16.25", currency: "SGD" },
  percent: "0.96",
  price_kind: "live",
  as_of_at: "2026-09-28T14:41:00Z",
  holds: true,
  movers: [mover("NVDA", { headline: { headline: "Nvidia wins a big order", source: "Wire", url: "https://news.example/nvda/1", summary: "", published_at: "2026-09-28T14:00:00Z" } })],
  prices: true,
  ...over,
});
const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.useRealTimers());

describe("TodayCard", () => {
  it.each([
    ["live", "Today"],
    ["closed_today", "Today's session"],
    ["previous", "Last session"],
  ] as const)("is titled for a %s session", async (session, title) => {
    mockApi({ "GET /investments/today": () => today({ session }) });
    renderWithProviders(<TodayCard />);
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
  });

  it("says when a live price is from and shows the change in colour", async () => {
    mockApi({ "GET /investments/today": () => today() });
    const { container } = renderWithProviders(<TodayCard />);
    const card = await screen.findByRole("region", { name: "Today" });
    expect(card).toHaveTextContent("Live");
    expect(card.querySelector(".live-dot")).not.toBeNull();
    expect(card).toHaveTextContent("+");
    expect(card).toHaveTextContent("+0.96%");
    expect(container.querySelector(".today-change.up")).not.toBeNull();
  });

  it("colours a fall rose and signs it with a minus", async () => {
    mockApi({ "GET /investments/today": () => today({ change: { amount: "-9.50", currency: "SGD" }, percent: "-1.20" }) });
    const { container } = renderWithProviders(<TodayCard />);
    const card = await screen.findByRole("region", { name: "Today" });
    expect(card).toHaveTextContent("−");
    expect(card).toHaveTextContent("−1.2%");
    expect(container.querySelector(".today-change.down")).not.toBeNull();
  });

  it("lists movers with a stock link, the move, the price and a headline link", async () => {
    mockApi({
      "GET /investments/today": () =>
        today({ movers: [mover("NVDA", { headline: { headline: "Nvidia wins a big order", source: "Wire", url: "https://news.example/nvda/1", summary: "", published_at: "x" } }), mover("AMD", { day_percent: "-2.10", price: "129.00" })] }),
    });
    renderWithProviders(<TodayCard />);
    const list = await screen.findByRole("list", { name: "Biggest movers" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "NVDA" })).toHaveAttribute("href", "/investment/stocks/NVDA");
    expect(rows[0]).toHaveTextContent("USD 131.50");
    const headline = within(rows[0]).getByRole("link", { name: "Nvidia wins a big order" });
    expect(headline).toHaveAttribute("href", "https://news.example/nvda/1");
    expect(headline).toHaveAttribute("target", "_blank");
    expect(rows[1]).toHaveTextContent("−2.1%");
    expect(within(rows[1]).queryByRole("link", { name: /order/ })).toBeNull();
  });

  it("shows a headline without a link when it has no url", async () => {
    mockApi({
      "GET /investments/today": () =>
        today({ movers: [mover("NVDA", { headline: { headline: "Nvidia wins a big order", source: "Wire", url: "", summary: "", published_at: "x" } })] }),
    });
    renderWithProviders(<TodayCard />);
    await screen.findByText("Nvidia wins a big order");
    expect(screen.queryByRole("link", { name: "Nvidia wins a big order" })).toBeNull();
  });

  it("shows movers alone for watched stocks when nothing is held", async () => {
    mockApi({ "GET /investments/today": () => today({ change: null, percent: null, holds: false, movers: [mover("AMD", { held: false })] }) });
    const { container } = renderWithProviders(<TodayCard />);
    await screen.findByRole("list", { name: "Biggest movers" });
    expect(container.querySelector(".today-change")).toBeNull();
  });

  it("is hidden when there is nothing held or watched", async () => {
    const calls = mockApi({ "GET /investments/today": () => today({ change: null, percent: null, holds: false, movers: [] }) });
    const { container } = renderWithProviders(<TodayCard />);
    await waitFor(() => expect(calls).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });

  it("answers Why did it move? in place, with where it came from", async () => {
    const calls = mockApi({
      "GET /investments/today": () => today(),
      "POST /investments/today/NVDA/why": () => ({ symbol: "NVDA", day: "2026-09-28", day_percent: "0.96", text: "Nvidia won a big order. Chip stocks were also higher.", headlines: [], cached: false }),
    });
    renderWithProviders(<TodayCard />);
    await userEvent.click(await screen.findByRole("button", { name: /Why did it move/ }));
    expect(await screen.findByText("Nvidia won a big order. Chip stocks were also higher.")).toBeInTheDocument();
    expect(screen.getByText("From today's headlines")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Why did it move/ })).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("tells the user to try again in a minute after a 429, and lets them", async () => {
    let asked = 0;
    mockApi({
      "GET /investments/today": () => today(),
      "POST /investments/today/NVDA/why": () => {
        asked += 1;
        return asked === 1
          ? json({ detail: "Too many requests" }, 429)
          : { symbol: "NVDA", day: "2026-09-28", day_percent: "0.96", text: "A big order.", headlines: [], cached: false };
      },
    });
    renderWithProviders(<TodayCard />);
    await userEvent.click(await screen.findByRole("button", { name: /Why did it move/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in a minute");
    await userEvent.click(screen.getByRole("button", { name: /Why did it move/ }));
    expect(await screen.findByText("A big order.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the server's short reason for a 422, and a plain line for anything else", async () => {
    let status = 422;
    mockApi({
      "GET /investments/today": () => today(),
      "POST /investments/today/NVDA/why": () => json({ detail: "reading why a stock moved isn't set up" }, status),
    });
    renderWithProviders(<TodayCard />);
    const button = await screen.findByRole("button", { name: /Why did it move/ });
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("reading why a stock moved isn't set up");
    status = 500;
    await userEvent.click(screen.getByRole("button", { name: /Why did it move/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Couldn't read that move just now"));
  });

  it("asks again every minute while the session is live, and not otherwise", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let session: Today["session"] = "live";
    const calls = mockApi({ "GET /investments/today": () => today({ session }) });
    renderWithProviders(<TodayCard />);
    await screen.findByRole("region", { name: "Today" });
    expect(calls).toHaveLength(1);
    session = "closed_today";
    await vi.advanceTimersByTimeAsync(60_000);
    await screen.findByRole("region", { name: "Today's session" });
    expect(calls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(calls).toHaveLength(2);
  });
});

describe("whyError", () => {
  it("is the same wording the card shows", () => {
    expect(whyError(new Error("x"))).toBe("Couldn't read that move just now");
  });
});
