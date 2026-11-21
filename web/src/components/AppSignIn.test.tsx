import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../testing";
import { AppSignIn } from "./AppSignIn";

const START = { code: "ABCD-2345", poll_id: "poll-1", expires_in: 300, bot_username: "made_up_bot" };

describe("AppSignIn", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the code, a Telegram link and the typed command", async () => {
    mockApi({
      "POST /auth/device": () => START,
      "GET /auth/device/poll-1": () => ({ status: "pending" }),
    });
    render(<AppSignIn pollMs={20} />);
    expect(await screen.findByText("ABCD-2345")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Telegram" })).toHaveAttribute(
      "href",
      "https://t.me/made_up_bot?start=app-ABCD2345",
    );
    expect(screen.getByText(/\/app ABCD-2345/)).toBeInTheDocument();
    expect(screen.getByText(/Expires in 5:00|Expires in 4:5/)).toBeInTheDocument();
  });

  it("polls, then opens the sign-in link once approved", async () => {
    let polls = 0;
    mockApi({
      "POST /auth/device": () => START,
      "GET /auth/device/poll-1": () =>
        ++polls < 3 ? { status: "pending" } : { status: "approved", login_path: "/login/link/tok" },
    });
    const navigate = vi.fn();
    render(<AppSignIn pollMs={10} navigate={navigate} />);
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login/link/tok"));
    await new Promise((r) => setTimeout(r, 60));
    expect(polls).toBe(3); // stopped once approved
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("stops polling when it goes away", async () => {
    const calls = mockApi({
      "POST /auth/device": () => START,
      "GET /auth/device/poll-1": () => ({ status: "pending" }),
    });
    const { unmount } = render(<AppSignIn pollMs={10} />);
    await screen.findByText("ABCD-2345");
    await waitFor(() => expect(calls.some((c) => c.method === "GET")).toBe(true));
    unmount();
    const seen = calls.length;
    await new Promise((r) => setTimeout(r, 60));
    expect(calls.length).toBe(seen);
  });

  it("offers a new code when the request has expired", async () => {
    let started = 0;
    mockApi({
      "POST /auth/device": () => (++started === 1 ? START : { ...START, code: "WXYZ-6789", poll_id: "poll-2" }),
      "GET /auth/device/poll-1": () => new Response(JSON.stringify({ detail: "x" }), { status: 404 }),
      "GET /auth/device/poll-2": () => ({ status: "pending" }),
    });
    render(<AppSignIn pollMs={10} />);
    await userEvent.click(await screen.findByRole("button", { name: "Get a new code" }));
    expect(await screen.findByText("WXYZ-6789")).toBeInTheDocument();
  });
});
