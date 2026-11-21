import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../testing";
import { LoginPage } from "./LoginPage";

function renderAt(address: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[address]}>
        <LoginPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("says an expired sign-in link from the bot has to be asked for again", async () => {
    mockApi({ "GET /config": () => ({ bot_username: "made_up_bot" }) });
    renderAt("/login?error=link");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That sign-in link has expired — send /web to the bot again",
    );
  });

  it("shows no error on a plain visit", async () => {
    mockApi({ "GET /config": () => ({ bot_username: "made_up_bot" }) });
    renderAt("/login");
    expect(await screen.findByRole("link", { name: "Try the live demo" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("hides the Telegram widget inside the iOS app and shows a code to approve", async () => {
    window.NexusNative = { v: 1, platform: "ios" };
    try {
      mockApi({
        "GET /config": () => ({ bot_username: "made_up_bot" }),
        "POST /auth/device": () => ({ code: "ABCD-2345", poll_id: "p", expires_in: 300, bot_username: "made_up_bot" }),
        "GET /auth/device/p": () => ({ status: "pending" }),
      });
      const { container } = renderAt("/login");
      expect(await screen.findByText("ABCD-2345")).toBeInTheDocument();
      expect(container.querySelector("script[data-telegram-login]")).toBeNull();
    } finally {
      delete window.NexusNative;
    }
  });
});
