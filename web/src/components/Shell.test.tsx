import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "../api";
import { Shell } from "./Shell";

type Menu = NonNullable<Me["preferences"]>;
const everything: Menu = { track_cards: false, show_invest: true, show_travel: true };

const user = (role: Me["user"]["role"], display_name?: string | null, preferences?: Menu): Me => ({
  user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore", display_name },
  csrf_token: "c",
  preferences,
});

/** A member with Invest and Travel set as given (true shown; false, null or absent hidden). */
const member = (show_invest?: boolean | null, show_travel?: boolean | null): Me =>
  user("member", undefined, { track_cards: false, show_invest, show_travel });

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
    shell(user("member", undefined, everything));
    for (const name of ["Home", "Money", "Investment", "Travel", "Settings"]) {
      expect(screen.getAllByRole("link", { name }).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByRole("button", { name: "Ask Nexus" }).length).toBeGreaterThan(0);
  });

  it("has text labels in the bottom bar with the Nexus mark in the middle, and the full names in the rail", () => {
    shell(user("member", undefined, everything));
    const bar = screen.getByRole("navigation", { name: "Main (mobile)" });
    const links = within(bar).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Today", "Money", "Invest", "Trips"]);
    // The accessible names still say what each one is.
    expect(links.map((l) => l.getAttribute("aria-label") ?? l.textContent)).toEqual([
      "Today (Home)",
      "Money",
      "Invest (Investment)",
      "Trips (Travel)",
    ]);
    expect(within(bar).getByRole("link", { name: "Money" })).toHaveAttribute("href", "/accounting");
    // The one-colour Nexus mark is the way into chat, in the middle: Today, Money, [N], Invest, Trips.
    const ask = within(bar).getByRole("button", { name: "Ask Nexus" });
    expect(ask.querySelector("svg.nexus-mark")).not.toBeNull();
    expect(ask).toHaveTextContent("");
    expect([...bar.children]).toEqual([links[0], links[1], ask, links[2], links[3]]);
    expect(within(bar).getAllByRole("link").every((l) => l.querySelector("svg") === null)).toBe(true);
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getAllByRole("link").every((l) => l.querySelector("svg") === null)).toBe(true);
    expect(within(rail).getByRole("button", { name: "Ask Nexus" })).toHaveTextContent("Ask Nexus");
    expect(within(rail).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "Home",
      "Money",
      "Investment",
      "Travel",
      "Settings",
    ]);
  });

  it("marks the current place in the bottom bar", () => {
    shell(user("member", undefined, everything), "/accounting/ledger");
    const bar = screen.getByRole("navigation", { name: "Main (mobile)" });
    expect(within(bar).getByRole("link", { name: "Money" })).toHaveAttribute("aria-current", "page");
    expect(within(bar).getByRole("link", { name: "Today (Home)" })).not.toHaveAttribute("aria-current");
  });

  it("keeps Settings current on the pages inside it, with no department tabs", () => {
    shell(user("member"), "/settings/email");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(within(rail).getByRole("link", { name: "Money" })).not.toHaveAttribute("aria-current");
    expect(screen.queryByRole("navigation", { name: "Money pages" })).toBeNull();
  });

  it("lists Money's tabs without Email, and Investment's as Trade plans", () => {
    const { unmount } = shell(user("member", undefined, everything), "/accounting/budgets");
    const tabs = screen.getByRole("navigation", { name: "Money pages" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["Overview", "Ledger", "Budgets", "Cash flow"]);
    expect(within(tabs).getByRole("link", { name: "Budgets" })).toHaveAttribute("href", "/accounting/budgets");
    expect(within(tabs).getByRole("link", { name: "Budgets" })).toHaveAttribute("aria-current", "page");
    unmount();
    shell(user("member", undefined, everything), "/investment/plans");
    const invest = screen.getByRole("navigation", { name: "Investment pages" });
    expect(within(invest).getAllByRole("link").map((l) => l.textContent)).toEqual(["Portfolio", "Watchlist", "Trade plans"]);
  });

  it("gives a guest only their trips, a way out and no chat", () => {
    shell(user("guest"));
    expect(screen.getByText("The trips")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    for (const name of ["Home", "Money", "Investment", "Settings"]) {
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

describe("Invest and Travel in the menu", () => {
  const bar = () => screen.getByRole("navigation", { name: "Main (mobile)" });
  const rail = () => screen.getByRole("navigation", { name: "Main" });
  const labels = (nav: HTMLElement) => within(nav).getAllByRole("link").map((l) => l.textContent);

  it("hides both until they are on: not decided, absent and switched off all read as hidden", () => {
    for (const me of [member(null, null), member(), member(false, false), user("member")]) {
      const { unmount } = shell(me, "/accounting");
      expect(labels(bar())).toEqual(["Today", "Money"]);
      expect(labels(rail())).toEqual(["Home", "Money", "Settings"]);
      unmount();
    }
  });

  it("shows just Invest when only it is on", () => {
    shell(member(true, null), "/accounting");
    expect(labels(bar())).toEqual(["Today", "Money", "Invest"]);
    expect(labels(rail())).toEqual(["Home", "Money", "Investment", "Settings"]);
  });

  it("shows just Travel, as Trips on the bar, when only it is on", () => {
    shell(member(false, true), "/accounting");
    expect(labels(bar())).toEqual(["Today", "Money", "Trips"]);
    expect(labels(rail())).toEqual(["Home", "Money", "Travel", "Settings"]);
  });

  it("shows both", () => {
    shell(member(true, true), "/accounting");
    expect(labels(bar())).toEqual(["Today", "Money", "Invest", "Trips"]);
  });

  it("keeps a hidden section's pages open, with its own tabs and no tab current in the menu", () => {
    shell(member(null, null), "/investment/plans");
    expect(screen.getByText("The trips")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Investment pages" })).getAllByRole("link")).toHaveLength(3);
    for (const nav of [bar(), rail()]) {
      expect(within(nav).queryByRole("link", { current: "page" })).toBeNull();
    }
  });

  it("marks the section when it is in the menu", () => {
    shell(member(true, null), "/investment/plans");
    expect(within(bar()).getByRole("link", { name: "Invest (Investment)" })).toHaveAttribute("aria-current", "page");
  });

  it("does not hide a guest's trips or give them the menu", () => {
    shell(user("guest", "Gus L.", { track_cards: false, show_invest: null, show_travel: null }));
    expect(screen.queryByRole("navigation", { name: "Main (mobile)" })).toBeNull();
  });
});

describe("the offline notice", () => {
  const notice = (waiting?: number) =>
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Shell me={user("member")} onOpenChat={() => {}} onLogout={() => {}} offlineWaiting={waiting}>
          <p>The page</p>
        </Shell>
      </MemoryRouter>,
    );

  it("says how many expenses will sync, above the page and not over it", () => {
    notice(1);
    const text = screen.getByRole("status");
    expect(text).toHaveTextContent("You're offline. 1 expense will sync when you're back.");
    // In the flow before the page, not positioned over it.
    expect(text.compareDocumentPosition(screen.getByText("The page")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(text.className).toBe("offline-notice");
  });

  it("uses the plural", () => {
    notice(3);
    expect(screen.getByRole("status")).toHaveTextContent("3 expenses will sync");
  });

  it.each([undefined, 0])("is not there with %s waiting", (waiting) => {
    notice(waiting);
    expect(screen.queryByText(/You're offline/)).toBeNull();
  });
});

describe("the way into chat", () => {
  it("opens the chat from the bar and from the rail", async () => {
    const onOpenChat = vi.fn();
    render(
      <MemoryRouter initialEntries={["/accounting"]}>
        <Shell me={user("member")} onOpenChat={onOpenChat} onLogout={() => {}}>
          <p>The page</p>
        </Shell>
      </MemoryRouter>,
    );
    const user_ = userEvent.setup();
    for (const nav of ["Main (mobile)", "Main"]) {
      await user_.click(within(screen.getByRole("navigation", { name: nav })).getByRole("button", { name: "Ask Nexus" }));
    }
    expect(onOpenChat).toHaveBeenCalledTimes(2);
  });
});
