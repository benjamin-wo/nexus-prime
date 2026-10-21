import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Me } from "../api";
import { Shell } from "./Shell";

const user = (role: Me["user"]["role"], display_name?: string | null): Me => ({
  user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore", display_name },
  csrf_token: "c",
});

function shell(me: Me, at = "/travel") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Shell me={me} onOpenChat={() => {}} onLogout={() => {}}>
        <p>The trips</p>
      </Shell>
    </MemoryRouter>,
  );
}

describe("the shell", () => {
  it("gives a member every department, Settings and the chat", () => {
    shell(user("member"));
    for (const name of ["Home", "Accounting", "Investment", "Travel", "Settings"]) {
      expect(screen.getAllByRole("link", { name }).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByRole("button", { name: "Ask Nexus" }).length).toBeGreaterThan(0);
  });

  it("puts a short label under each icon in the bottom bar, and the full names in the rail", () => {
    shell(user("member"));
    const bar = screen.getByRole("navigation", { name: "Main (mobile)" });
    const links = within(bar).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Home", "Money", "Invest", "Travel"]);
    // The accessible names still say what each one is.
    expect(links.map((l) => l.getAttribute("aria-label") ?? l.textContent)).toEqual([
      "Home",
      "Money (Accounting)",
      "Invest (Investment)",
      "Travel",
    ]);
    expect(within(bar).getByRole("link", { name: "Money (Accounting)" })).toHaveAttribute("href", "/accounting");
    // Nexus stays in the middle, as a button with its own name.
    const kids = [...bar.children];
    expect(kids[2]).toBe(within(bar).getByRole("button", { name: "Ask Nexus" }));
    expect(kids[2]).toHaveTextContent("");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "Home",
      "Accounting",
      "Investment",
      "Travel",
      "Settings",
    ]);
  });

  it("marks the current place in the bottom bar", () => {
    shell(user("member"), "/accounting/ledger");
    const bar = screen.getByRole("navigation", { name: "Main (mobile)" });
    expect(within(bar).getByRole("link", { name: "Money (Accounting)" })).toHaveAttribute("aria-current", "page");
    expect(within(bar).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("keeps Settings current on the pages inside it, with no department tabs", () => {
    shell(user("member"), "/settings/email");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(within(rail).getByRole("link", { name: "Accounting" })).not.toHaveAttribute("aria-current");
    expect(screen.queryByRole("navigation", { name: "Accounting pages" })).toBeNull();
  });

  it("lists Accounting's tabs without Email, and Investment's as Trade plans", () => {
    const { unmount } = shell(user("member"), "/accounting/budgets");
    const tabs = screen.getByRole("navigation", { name: "Accounting pages" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["Overview", "Ledger", "Budgets", "Cash flow"]);
    expect(within(tabs).getByRole("link", { name: "Budgets" })).toHaveAttribute("href", "/accounting/budgets");
    expect(within(tabs).getByRole("link", { name: "Budgets" })).toHaveAttribute("aria-current", "page");
    unmount();
    shell(user("member"), "/investment/plans");
    const invest = screen.getByRole("navigation", { name: "Investment pages" });
    expect(within(invest).getAllByRole("link").map((l) => l.textContent)).toEqual(["Portfolio", "Watchlist", "Trade plans"]);
  });

  it("gives a guest only their trips, a way out and no chat", () => {
    shell(user("guest"));
    expect(screen.getByText("The trips")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    for (const name of ["Home", "Accounting", "Investment", "Settings"]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    expect(screen.queryByRole("button", { name: "Ask Nexus" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Main (mobile)" })).toBeNull();
    // The app's name is the only link, and it goes to Travel.
    expect(screen.getAllByRole("link").map((l) => l.getAttribute("href"))).toEqual(["/travel"]);
  });

  it("shows a guest who is signed in beside Sign out, and nothing when they have no name", () => {
    const { unmount } = shell(user("guest", "Gus L."));
    expect(screen.getByText("Gus L.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    unmount();
    shell(user("guest", null));
    expect(screen.queryByText("Gus L.")).toBeNull();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
