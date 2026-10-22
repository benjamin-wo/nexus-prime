import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, NotificationEntry } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { groupByDay, NotificationsPage, statusLabel } from "./Notifications";

const me = (timezone: string): Me => ({
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone },
  csrf_token: "csrf",
});

const entry = (id: string, created_at: string, over: Partial<NotificationEntry> = {}): NotificationEntry => ({
  id,
  kind: "bill_reminder",
  level: "now",
  text: `Message ${id}`,
  link: null,
  status: "sent",
  created_at,
  sent_at: created_at,
  held_until: null,
  ...over,
});

// 12:00 on Thursday 22 Oct 2026 in Singapore.
const NOW = new Date("2026-10-22T04:00:00Z");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
});
afterEach(() => vi.useRealTimers());

describe("groupByDay", () => {
  it("groups by the user's day, Today and Yesterday first, newest first", () => {
    const days = groupByDay(
      [
        entry("old", "2026-10-09T03:00:00Z"),
        entry("a", "2026-10-22T01:00:00Z"),
        entry("b", "2026-10-21T14:10:00Z"),
        entry("c", "2026-10-21T14:42:00Z"),
        entry("d", "2026-10-20T00:00:00Z"),
      ],
      "Asia/Singapore",
      NOW,
    );
    expect(days.map((d) => d.label).slice(0, 2)).toEqual(["Today", "Yesterday"]);
    // Dates are written the way the locale does ("Tue, Oct 20" or "Tue 20 Oct").
    expect(days[2].label).toMatch(/^Tue,? (Oct 20|20 Oct)$/);
    expect(days[3].label).toMatch(/^Fri,? (Oct 9|9 Oct)$/);
    expect(days[1].entries.map((e) => e.id)).toEqual(["c", "b"]);
  });

  it("puts a message on the day it was made where the user is, not in UTC", () => {
    // 16:30 UTC on the 21st is half past midnight on the 22nd in Singapore, still the 21st in New York.
    const rows = [entry("late", "2026-10-21T16:30:00Z")];
    expect(groupByDay(rows, "Asia/Singapore", NOW).map((d) => d.label)).toEqual(["Today"]);
    expect(groupByDay(rows, "America/New_York", NOW).map((d) => d.label)).toEqual(["Yesterday"]);
  });

  it("adds the year to a date from another year", () => {
    const days = groupByDay([entry("x", "2025-12-30T10:00:00Z")], "Asia/Singapore", NOW);
    expect(days[0].label).toMatch(/^Tue,? (Dec 30, 2025|30 Dec 2025)$/);
  });

  it("is empty with nothing", () => {
    expect(groupByDay([], "Asia/Singapore", NOW)).toEqual([]);
  });
});

describe("statusLabel", () => {
  const tz = "Asia/Singapore";
  const at = "2026-10-22T01:00:00Z";
  it("says Sent, In a digest and not linked", () => {
    expect(statusLabel(entry("s", at), tz, NOW)).toBe("Sent");
    expect(statusLabel(entry("d", at, { status: "digested" }), tz, NOW)).toBe("In a digest");
    expect(statusLabel(entry("x", at, { status: "dropped", sent_at: null }), tz, NOW)).toBe("Not sent — Telegram not linked");
  });

  it("says when a held message goes, in the user's timezone", () => {
    const held = entry("h", at, { status: "held", sent_at: null, held_until: "2026-10-23T00:00:00Z" });
    // 00:00 UTC is 8:00am in Singapore, and the evening before in New York.
    expect(statusLabel(held, "Asia/Singapore", NOW)).toBe("Held until tomorrow 8:00am");
    expect(statusLabel({ ...held, held_until: "2026-10-22T10:00:00Z" }, "Asia/Singapore", NOW)).toBe("Held until 6:00pm");
    expect(statusLabel({ ...held, held_until: "2026-10-23T00:00:00Z" }, "America/New_York", NOW)).toBe("Held until 8:00pm");
  });

  it("says a held message with no time waits for the digest", () => {
    expect(statusLabel(entry("h", at, { status: "held", sent_at: null }), tz, NOW)).toBe("Held for the next digest");
  });
});

describe("Notifications page", () => {
  const rows = [
    entry("1", "2026-10-22T02:00:00Z", { text: "TSLA is down 6.2% today", level: "urgent", link: "/investment/stocks/TSLA" }),
    entry("2", "2026-10-22T00:30:00Z", { text: "Fresh Mart, S$23.40. Log it?", status: "held", sent_at: null, held_until: "2026-10-22T00:00:00Z" }),
    entry("3", "2026-10-21T14:10:00Z", { text: "80% of your budget used", level: "digest", status: "digested" }),
    entry("4", "2026-10-09T03:00:00Z", { text: "Your trip is in 5 days", status: "dropped", sent_at: null }),
  ];
  const open = async (data: NotificationEntry[]) => {
    mockApi({ "GET /notifications/history": () => data });
    renderWithProviders(<NotificationsPage me={me("Asia/Singapore")} />);
    await screen.findByRole("heading", { name: "Notifications", level: 1 });
    await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
  };

  it("explains the rules in a line, and goes back to Settings", async () => {
    await open(rows);
    expect(screen.getByText(/Urgent ones always come\. The rest respect your quiet hours and daily limit/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/settings");
  });

  it("lists the days as titled blocks, newest first, each with its messages", async () => {
    await open(rows);
    const titles = await screen.findAllByRole("heading", { level: 2 });
    expect(titles.map((h) => h.textContent).slice(0, 2)).toEqual(["Today", "Yesterday"]);
    expect(titles).toHaveLength(3);
    expect(titles[2].textContent).toMatch(/^Fri,? (Oct 9|9 Oct)$/);
    const today = screen.getByRole("region", { name: "Today" });
    expect(within(today).getAllByRole("listitem")).toHaveLength(2);
    expect(within(screen.getByRole("region", { name: "Yesterday" })).getAllByRole("listitem")).toHaveLength(1);
  });

  it("shows a chip for each status, a time, and an Urgent marker only on urgent ones", async () => {
    await open(rows);
    const item = (text: string) => screen.getByText(text).closest("li") as HTMLElement;
    const urgent = item("TSLA is down 6.2% today");
    expect(within(urgent).getByText("Sent")).toBeInTheDocument();
    expect(within(urgent).getByText("Urgent")).toBeInTheDocument();
    expect(within(urgent).getByText("10:00am")).toBeInTheDocument();
    const held = item("Fresh Mart, S$23.40. Log it?");
    expect(within(held).getByText("Held until 8:00am")).toBeInTheDocument();
    expect(within(held).queryByText("Urgent")).toBeNull();
    expect(within(item("80% of your budget used")).getByText("In a digest")).toBeInTheDocument();
    expect(within(item("Your trip is in 5 days")).getByText("Not sent — Telegram not linked")).toBeInTheDocument();
  });

  it("links a row to where its message points, and leaves one with no link as text", async () => {
    await open(rows);
    expect(screen.getByRole("link", { name: "TSLA is down 6.2% today" })).toHaveAttribute("href", "/investment/stocks/TSLA");
    expect(screen.queryByRole("link", { name: "80% of your budget used" })).toBeNull();
  });

  it("folds a long message after two lines, and Show more opens the rest", async () => {
    const long = ["Good morning.", "NVDA +5.4% on strong demand.", "AMD +2.1% after a launch.", "TSLA -0.8% on deliveries."].join("\n");
    await open([entry("5", "2026-10-22T00:00:00Z", { text: long })]);
    const more = screen.getByRole("button", { name: "Show more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector(".note-text")).toHaveClass("open");
    expect(document.querySelector(".note-text")?.textContent).toBe(long);
  });

  it("has no Show more on a short message", async () => {
    await open(rows);
    expect(screen.queryByRole("button", { name: /Show/ })).toBeNull();
  });

  it("says so when nothing was sent", async () => {
    await open([]);
    expect(await screen.findByText("Nothing sent in the last 30 days.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("says when the list can't load", async () => {
    mockApi({});
    renderWithProviders(<NotificationsPage me={me("Asia/Singapore")} />);
    expect(await screen.findByText("Couldn't load your notifications.")).toBeInTheDocument();
  });
});
