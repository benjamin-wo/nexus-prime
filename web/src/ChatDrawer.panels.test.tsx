import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "./api";
import { ChatDrawer } from "./components/ChatDrawer";
import { Shell } from "./components/Shell";
import { PanelStageProvider, usePanelStageContext } from "./panels/usePanelStage";

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

const panel = {
  panel_id: "finance.budgets",
  kind: "finance.budgets",
  version: 1,
  params: { month: "2026-11" },
  topic: "your dining budget",
  as_of: "2026-11-15T10:02:00Z",
  message_id: "m1",
};

/** fetch for a chat whose stream sends one panel and then its reply. */
function streamWithPanel() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    if (path === "/chat/history") return json({ lines: [], more: false, pending: null });
    if (path === "/chat/stream" && init?.method === "POST")
      return new Response(frame("panel.upsert", panel) + frame("replies", [{ text: "You have used half.", buttons: [] }]), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    if (path === "/budgets") return json([]);
    return json({ detail: "not mocked" }, 404);
  });
}

function Seen() {
  const stage = usePanelStageContext();
  return <p data-testid="seen">{stage.state.panels.map((p) => p.id).join(",")}</p>;
}

const wrap = (ui: React.ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>
      <PanelStageProvider>{ui}</PanelStageProvider>
    </MemoryRouter>
  </QueryClientProvider>
);

describe("ChatDrawer and the panel stage", () => {
  it("gives the panels a turn opens to the stage", async () => {
    streamWithPanel();
    render(wrap(<><ChatDrawer onClose={() => {}} onChanged={() => {}} /><Seen /></>));
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "how is my dining budget?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("You have used half.")).toBeInTheDocument();
    expect(screen.getByTestId("seen")).toHaveTextContent("finance.budgets");
  });

  it("still works with no stage around it", async () => {
    streamWithPanel();
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ChatDrawer onClose={() => {}} onChanged={() => {}} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "budget?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("You have used half.")).toBeInTheDocument();
  });
});

const me: Me = { user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };

describe("the docked layout", () => {
  function docked(isDocked: boolean) {
    streamWithPanel();
    return render(
      wrap(
        <Shell me={me} onOpenChat={() => {}} onLogout={() => {}} docked={isDocked}>
          <p>The page</p>
          <ChatDrawer docked={isDocked} onClose={() => {}} onChanged={() => {}} />
        </Shell>,
      ),
    );
  }

  it("draws the chat as a column that cannot be closed, with the page showing until a panel opens", async () => {
    docked(true);
    const chat = await screen.findByRole("region", { name: "Chat" });
    expect(chat.closest(".chat-column")).not.toBeNull();
    expect(within(chat).queryByRole("button", { name: "Close chat" })).toBeNull();
    expect(screen.getByText("The page")).toBeVisible();
    expect(document.activeElement).not.toBe(screen.getByLabelText("Message"));

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "how is my dining budget?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("You have used half.")).toBeInTheDocument();
    // The stage comes forward, announces itself, and the page is one click away.
    await waitFor(() => expect(screen.getByRole("button", { name: "Panels" })).toHaveAttribute("aria-pressed", "true"));
    expect(await screen.findByRole("article", { name: "Budgets" })).toBeVisible();
    expect(screen.getByText("The page")).not.toBeVisible();
    await user.click(screen.getByRole("button", { name: "Page" }));
    expect(screen.getByText("The page")).toBeVisible();
    expect(screen.getByRole("button", { name: "Page" })).toHaveAttribute("aria-pressed", "true");
  });

  it("is a plain drawer, with no stage, when not docked", async () => {
    docked(false);
    expect(await screen.findByRole("dialog", { name: "Chat" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Panels" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Panels" })).toBeNull();
  });
});

