import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { Settings } from "./Settings";

const connected = {
  connections: [{ id: "m1", address: "me@example.com", kind: "gmail", status: "ok", last_checked_at: null, last_error: null }],
  emails: [
    { id: "e1", status: "pending" },
    { id: "e2", status: "logged" },
  ],
};

/** The group a section title opens: the cards under it, up to the next title. */
function group(title: string): HTMLElement {
  // A card can share a group's name (Notifications), so pick the title.
  const heading = screen.getAllByRole("heading", { name: title, level: 2 }).find((h) => h.classList.contains("section-title"));
  expect(heading).toBeDefined();
  return heading!.nextElementSibling as HTMLElement;
}

describe("Settings", () => {
  it("is in three groups: Notifications, Connections and Your data, in that order", () => {
    mockApi({});
    renderWithProviders(<Settings />);
    expect(screen.getByRole("heading", { name: "Settings", level: 1 })).toBeInTheDocument();
    const titles = [...document.querySelectorAll("h2.section-title")].map((h) => h.textContent);
    expect(titles).toEqual(["Notifications", "Connections", "Your data"]);
    expect(screen.queryByRole("heading", { name: /^(Account|Travel|Accounting)$/ })).toBeNull();
  });

  it("puts alerts under Notifications, the two ways in under Connections, and the rest under Your data", async () => {
    mockApi({ "GET /email": () => connected });
    renderWithProviders(<Settings />);
    const names = (g: HTMLElement) => within(g).getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names(group("Notifications"))).toEqual(expect.arrayContaining(["Shared trips", "Notifications"]));
    expect(names(group("Connections"))).toEqual(["Receipts by email", "Import a statement"]);
    const data = names(group("Your data"));
    expect(data).toEqual(expect.arrayContaining(["Categories", "Wallets", "Category rules", "What Nexus remembers"]));
    expect(data.indexOf("What Nexus remembers")).toBeGreaterThan(data.indexOf("Category rules"));
  });

  it("links Receipts by email and Import a statement to their pages", async () => {
    mockApi({ "GET /email": () => connected });
    renderWithProviders(<Settings />);
    const email = screen.getByRole("region", { name: "Receipts by email" });
    expect(within(email).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/settings/email");
    expect(await within(email).findByText("me@example.com · 1 waiting for you")).toBeInTheDocument();
    const statement = screen.getByRole("region", { name: "Import a statement" });
    expect(within(statement).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/settings/import");
  });

  it("links Notifications, under Notifications, to the list of what was sent", () => {
    mockApi({});
    renderWithProviders(<Settings />);
    const card = within(group("Notifications")).getByRole("region", { name: "Notifications" });
    expect(within(card).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/settings/notifications");
    expect(card).toHaveTextContent("in the last 30 days");
  });

  it("shows Receipts by email before anything is connected", async () => {
    mockApi({ "GET /email": () => ({ connections: [], emails: [] }) });
    renderWithProviders(<Settings />);
    const email = screen.getByRole("region", { name: "Receipts by email" });
    expect(await within(email).findByText(/Not connected/)).toBeInTheDocument();
    expect(within(email).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/settings/email");
  });
});
