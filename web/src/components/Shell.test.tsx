import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Me } from "../api";
import { Shell } from "./Shell";

const user = (role: Me["user"]["role"], display_name?: string | null): Me => ({
  user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore", display_name },
  csrf_token: "c",
});

function shell(me: Me) {
  return render(
    <MemoryRouter initialEntries={["/travel"]}>
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
