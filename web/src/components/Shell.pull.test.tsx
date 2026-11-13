import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me } from "../api";
import { Shell } from "./Shell";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};

function page(at: string, onRefresh: () => Promise<unknown>) {
  render(
    <MemoryRouter initialEntries={[at]}>
      <Shell me={me} onOpenChat={() => {}} onLogout={() => {}} onRefresh={onRefresh}>
        <p>The page</p>
        <div role="dialog" aria-label="A dialog">
          <p>Inside the dialog</p>
        </div>
      </Shell>
    </MemoryRouter>,
  );
  return screen.getByRole("main");
}

const touch = (y: number, x = 100) => ({ touches: [{ clientX: x, clientY: y }] });

function pull(main: HTMLElement, from: number, to: number) {
  fireEvent.touchStart(main, touch(from));
  fireEvent.touchMove(main, touch(from + (to - from) / 2));
  fireEvent.touchMove(main, touch(to));
  fireEvent.touchEnd(main);
}

afterEach(() => {
  delete window.Telegram;
});

describe("pull to refresh", () => {
  it("refreshes when a page at the top is pulled down far enough", async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const main = page("/accounting/ledger", onRefresh);
    pull(main, 100, 260);
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Refreshing…")).toBeInTheDocument();
    expect(await screen.findByText("Updated")).toBeInTheDocument();
  });

  it.each(["/", "/accounting", "/accounting/ledger", "/accounting/budgets"])("works on %s", (path) => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    pull(page(path, onRefresh), 100, 260);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("takes the gesture from the browser while pulling", () => {
    const main = page("/", vi.fn().mockResolvedValue(undefined));
    fireEvent.touchStart(main, touch(100));
    const move = new Event("touchmove", { bubbles: true, cancelable: true });
    Object.assign(move, touch(200));
    main.dispatchEvent(move);
    expect(move.defaultPrevented).toBe(true);
    expect(main.classList.contains("ptr-active")).toBe(true);
  });

  it("leaves a touch that starts inside a dialog to the dialog, and still pulls from the page", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const main = page("/", onRefresh);
    const inside = screen.getByText("Inside the dialog");
    fireEvent.touchStart(inside, touch(100));
    const move = new Event("touchmove", { bubbles: true, cancelable: true });
    Object.assign(move, touch(260));
    inside.dispatchEvent(move);
    fireEvent.touchEnd(inside);
    expect(move.defaultPrevented).toBe(false);
    expect(main.classList.contains("ptr-active")).toBe(false);
    expect(onRefresh).not.toHaveBeenCalled();

    pull(screen.getByText("The page"), 100, 260);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("does nothing for a short pull", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const main = page("/", onRefresh);
    pull(main, 100, 150);
    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByText("Refreshing…")).not.toBeInTheDocument();
  });

  it("leaves a page that is scrolled down alone", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const main = page("/", onRefresh);
    main.scrollTop = 120;
    pull(main, 100, 300);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("leaves an upward or sideways move alone", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const main = page("/", onRefresh);
    pull(main, 300, 100);
    fireEvent.touchStart(main, touch(100, 0));
    fireEvent.touchMove(main, touch(130, 150));
    fireEvent.touchMove(main, touch(260, 300));
    fireEvent.touchEnd(main);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("is not on the pages that aren't money data", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    pull(page("/travel", onRefresh), 100, 260);
    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();
  });

  it("stays off in a Telegram that can't turn off swipe-to-close", () => {
    vi.resetModules();
    // initData is read once at load; the fake WebApp has no disableVerticalSwipes.
    window.history.replaceState(null, "", "/#tgWebAppData=abc");
    return import("../telegram").then(({ pullIsSafe }) => {
      window.Telegram = { WebApp: { ready() {}, expand() {} } };
      expect(pullIsSafe()).toBe(false);
      window.Telegram = { WebApp: { ready() {}, expand() {}, disableVerticalSwipes() {} } };
      expect(pullIsSafe()).toBe(true);
      window.history.replaceState(null, "", "/");
    });
  });

  it("has a Refresh button for the keyboard that does the same", async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    page("/", onRefresh);
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText("Updated")).toBeInTheDocument());
  });
});
