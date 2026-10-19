import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { TripActivity } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { ActivityLine, recentActivity, timeAgo } from "./TripActivity";

const NOW = Date.parse("2026-10-19T12:00:00Z");
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

describe("timeAgo", () => {
  it("says it in minutes, hours and days", () => {
    const at = (ms: number) => new Date(NOW - ms).toISOString();
    expect(timeAgo(at(10_000), NOW)).toBe("just now");
    expect(timeAgo(at(5 * MIN), NOW)).toBe("5 min ago");
    expect(timeAgo(at(59 * MIN), NOW)).toBe("59 min ago");
    expect(timeAgo(at(HOUR), NOW)).toBe("1 hour ago");
    expect(timeAgo(at(3 * HOUR), NOW)).toBe("3 hours ago");
    expect(timeAgo(at(DAY), NOW)).toBe("1 day ago");
    expect(timeAgo(at(3 * DAY), NOW)).toBe("3 days ago");
  });

  it("falls back to the date after a week, and to nothing for a bad one", () => {
    expect(timeAgo(new Date(NOW - 9 * DAY).toISOString(), NOW)).toMatch(/\d/);
    expect(timeAgo(new Date(NOW - 9 * DAY).toISOString(), NOW)).not.toMatch(/ago/);
    expect(timeAgo("nonsense", NOW)).toBe("");
  });
});

describe("recentActivity", () => {
  const item = (ms: number): TripActivity => ({ actor: "Alex", summary: "added Dinner", at: new Date(NOW - ms).toISOString() });
  it("is the newest change when it is from the last 7 days", () => {
    expect(recentActivity([item(2 * DAY), item(3 * DAY)], NOW)).toEqual(item(2 * DAY));
  });
  it("is nothing for an older one or an empty log", () => {
    expect(recentActivity([item(8 * DAY)], NOW)).toBeNull();
    expect(recentActivity([], NOW)).toBeNull();
  });
});

describe("the activity line", () => {
  const log = (): TripActivity[] => [
    { actor: "Alex", summary: "added Dinner at Sushi Ten", at: ago(5 * MIN + 10_000) },
    { actor: "Sam", summary: "changed the notes", at: ago(2 * DAY) },
  ];

  it("shows the latest change with how long ago, and a tap lists the recent ones", async () => {
    mockApi({ "GET /travel/trips/t1/activity": log });
    renderWithProviders(<ActivityLine tripId="t1" shared />);
    const line = await screen.findByRole("button", { name: /Alex added Dinner at Sushi Ten/ });
    expect(line).toHaveTextContent("Alex added Dinner at Sushi Ten · 5 min ago");
    await userEvent.setup().click(line);
    const sheet = screen.getByRole("dialog", { name: "Recent changes" });
    const rows = within(sheet).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Alex added Dinner at Sushi Ten");
    expect(rows[1]).toHaveTextContent("Sam changed the notes");
    expect(rows[1]).toHaveTextContent("2 days ago");
  });

  it("is left out when nothing changed in the last week", async () => {
    const calls = mockApi({ "GET /travel/trips/t1/activity": () => [{ actor: "Alex", summary: "added Dinner", at: ago(9 * DAY) }] });
    renderWithProviders(<ActivityLine tripId="t1" shared />);
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/activity"))).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is left out, and never asked for, on a trip nobody else is on", async () => {
    const calls = mockApi({ "GET /travel/trips/t1/activity": log });
    renderWithProviders(<ActivityLine tripId="t1" shared={false} />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("button")).toBeNull();
    expect(calls).toHaveLength(0);
  });
});
