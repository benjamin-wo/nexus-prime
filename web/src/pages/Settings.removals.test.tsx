import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { EmailPage } from "./Email";
import { RulesSection } from "./Rules";

const refused = () => new Response(JSON.stringify({ detail: "Nexus is busy. Try again." }), { status: 500 });
const me = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" } as never;

afterEach(() => vi.restoreAllMocks());

describe("removing a category rule", () => {
  it("says so, and keeps the rule, when it can't be removed", async () => {
    mockApi({
      "GET /category-rules": () => [{ id: "r1", pattern: "grab", category_id: "c1", category_name: "Transport", explanation: "You filed Grab under Transport." }],
      "GET /categories": () => [],
      "DELETE /category-rules/r1": refused,
    });
    renderWithProviders(<RulesSection />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nexus is busy");
    expect(screen.getByText("“grab”")).toBeInTheDocument();
  });
});

describe("disconnecting a mailbox", () => {
  const overview = {
    available: true,
    forwarding_available: false,
    connections: [{ id: "e1", provider: "gmail", address: "ben@example.com", status: "active", last_checked: null, last_received: null }],
    emails: [],
  };

  it("asks first, and says so when the disconnect fails", async () => {
    const calls = mockApi({ "GET /email": () => overview, "DELETE /email/connections/e1": refused });
    renderWithProviders(<EmailPage me={me} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    // Nothing is sent until the question is answered.
    expect(screen.getByText("Stop reading this mailbox?")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(within(screen.getByText("Stop reading this mailbox?").parentElement as HTMLElement).getByRole("button", { name: "Disconnect" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nexus is busy");
    expect(screen.getByText("ben@example.com")).toBeInTheDocument();
  });
});
