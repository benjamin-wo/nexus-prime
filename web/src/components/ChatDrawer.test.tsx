import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../testing";
import { ChatDrawer } from "./ChatDrawer";

vi.mock("../telegram", () => ({ openExternal: vi.fn() }));
import { openExternal } from "../telegram";

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

function Where() {
  const l = useLocation();
  return <p data-testid="where">{`${l.pathname}${l.search}`}</p>;
}

function drawer(buttons: { label: string; data: string }[], onClose = vi.fn()) {
  const calls = mockApi({
    "GET /chat/history": () => ({ lines: [], more: false, pending: { text: "Logged lunch.", buttons: [buttons] } }),
    "POST /chat/press": () => [{ text: "Done.", buttons: [] }],
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ChatDrawer onClose={onClose} onChanged={() => {}} />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { calls, onClose };
}

describe("chat buttons", () => {
  it("opens a link to this app in the app, with its query", async () => {
    const { onClose } = drawer([{ label: "Edit", data: `url:${window.location.origin}/health?meal=m1` }]);
    await userEvent.click(await screen.findByRole("link", { name: "Edit" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/health?meal=m1");
    expect(openExternal).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled(); // only a phone closes the chat
  });

  it("closes the chat after an in-app link on a phone", async () => {
    window.matchMedia = ((q: string) => ({ matches: q.includes("480"), media: q, addEventListener: () => {}, removeEventListener: () => {} })) as unknown as typeof window.matchMedia;
    const { onClose } = drawer([{ label: "Edit", data: `url:${window.location.origin}/health?meal=m1` }]);
    await userEvent.click(await screen.findByRole("link", { name: "Edit" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/health?meal=m1");
    expect(onClose).toHaveBeenCalled();
  });

  it("opens another site outside the app", async () => {
    drawer([{ label: "Read", data: "url:https://example.com/a" }]);
    await userEvent.click(await screen.findByRole("link", { name: "Read" }));
    expect(openExternal).toHaveBeenCalledWith("https://example.com/a");
    expect(screen.getByTestId("where")).toHaveTextContent("/");
    expect(screen.getByTestId("where")).not.toHaveTextContent("example");
  });

  it("posts callback buttons as presses", async () => {
    const { calls } = drawer([
      { label: "Undo", data: "meal:undo:abc" },
      { label: "Start", data: "workout:start:w1" },
      { label: "Turn on Health", data: "health:on" },
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on Health" }));
    expect(await screen.findByText("Done.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/chat/press")?.body).toEqual({ data: "health:on" });
  });
});
