import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatHistory, Reply, ViewShow } from "../api";
import { ChatDrawer } from "../components/ChatDrawer";

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const sgd = (amount: string) => ({ amount, currency: "SGD" });

const OUTLOOK: ViewShow = {
  view_id: "finance.month_outlook",
  kind: "finance.month_outlook",
  params: { month: "2026-11" },
  focus: true,
  caption: "Your outlook for November 2026",
  summary: { status: "ok", received: sgd("5000.00"), spent: sgd("2100.00"), overall: sgd("2900.00"), headroom: null, shortfall: null },
};
const SPENDING: ViewShow = {
  view_id: "finance.spending",
  kind: "finance.spending",
  params: { month: "2026-11" },
  focus: false,
  caption: "Where your money went in November 2026",
  summary: { spent: sgd("2100.00"), count: 9, categories: [{ name: "Dining", total: sgd("2100.00") }] },
};
const TODAY: ViewShow = {
  view_id: "health.today",
  kind: "health.today",
  params: {},
  focus: true,
  caption: "Your day",
  summary: { day: "2026-11-27", meals: 1, kcal: "675", protein_g: "30" },
};

/** What GET /views/{kind} answers: the frame's own figures, so a card shows the same either way. */
const figures = (v: ViewShow) => ({ view_id: v.view_id, kind: v.kind, params: v.params, caption: v.caption, summary: v.summary });

function api(opts: { views?: boolean; history?: ChatHistory; routes?: Record<string, () => Response | Promise<Response>> } = {}) {
  const { views = true, history = { lines: [], more: false, pending: null }, routes = {} } = opts;
  const fetches: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const key = `${init?.method ?? "GET"} ${path}`;
    fetches.push(key);
    if (routes[key]) return routes[key]();
    if (key === "GET /config") return json({ bot_username: "b", views_enabled: views });
    if (key === "GET /chat/history") return json(history);
    const kind = /^\/views\/(.+)$/.exec(path)?.[1];
    const known = [OUTLOOK, SPENDING, TODAY].find((v) => v.kind === kind);
    if (known) return json(figures(known));
    return json({ detail: "not mocked" }, 404);
  });
  return fetches;
}

function openStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => (controller = c) });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send: (text: string) => act(async () => controller.enqueue(encoder.encode(text))),
  };
}

function Where() {
  const at = useLocation();
  return <output data-testid="where">{at.pathname + at.search}</output>;
}

function draw(props: Partial<React.ComponentProps<typeof ChatDrawer>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/app"]}>
        <ChatDrawer onClose={onClose} onChanged={() => {}} {...props} />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onClose };
}

async function say(text: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Message"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

const regions = () => screen.queryAllByRole("region").map((r) => r.getAttribute("aria-labelledby") && within(r).getByRole("heading").textContent);

function phone(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches, addEventListener: () => {}, removeEventListener: () => {} }) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  // @ts-expect-error jsdom has none
  delete window.matchMedia;
});

describe("views in the chat", () => {
  it("draws the cards as their frames arrive, then in order with the focus first", async () => {
    const stream = openStream();
    api({ routes: { "POST /chat/stream": () => stream.response } });
    draw();
    await say("how am I doing this month?");

    // The frames come first, supporting view before the focus one.
    await stream.send(frame("view.show", SPENDING));
    await stream.send(frame("view.show", OUTLOOK));
    await waitFor(() => expect(regions()).toEqual(["Your outlook for November 2026", "Where your money went in November 2026"]));

    // The replies carry the views too (on the last reply); nothing is drawn twice.
    const replies: Reply[] = [{ text: "You're on track.", buttons: [], views: [SPENDING, OUTLOOK] }];
    await stream.send(frame("replies", replies));
    expect(await screen.findByText("You're on track.")).toBeInTheDocument();
    await waitFor(() => expect(regions()).toEqual(["Your outlook for November 2026", "Where your money went in November 2026"]));
    // The cards sit under Prime's line.
    const line = screen.getByText("You're on track.");
    expect(line.compareDocumentPosition(screen.getAllByRole("region")[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the streamed views when the replies carry none", async () => {
    const stream = openStream();
    api({ routes: { "POST /chat/stream": () => stream.response } });
    draw();
    await say("had chicken rice");
    await stream.send(frame("view.show", TODAY));
    await stream.send(frame("replies", [{ text: "Logged.", buttons: [] }]));
    expect(await screen.findByText("Logged.")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Your day" })).toBeInTheDocument();
  });

  it("shows at most three views", async () => {
    const stream = openStream();
    api({ routes: { "POST /chat/stream": () => stream.response } });
    draw();
    await say("everything");
    const four = ["a", "b", "c", "d"].map((m, i) => ({ ...SPENDING, view_id: `s${i}`, params: { month: `2026-0${i + 1}` }, caption: `Spending ${m}`, focus: false }));
    for (const v of four) await stream.send(frame("view.show", v));
    await waitFor(() => expect(screen.getAllByRole("region")).toHaveLength(3));
  });

  it("draws the views of a reply sent the usual way when the stream can't start", async () => {
    api({
      routes: {
        "POST /chat/stream": () => json({ detail: "bad gateway" }, 502),
        "POST /chat": () => json([{ text: "Here's your day.", buttons: [], views: [TODAY] }]),
      },
    });
    draw();
    await say("what did I eat");
    expect(await screen.findByRole("region", { name: "Your day" })).toBeInTheDocument();
  });

  it("draws a past line's stored views when the chat reopens, with fresh figures", async () => {
    const fetches = api({
      history: {
        lines: [
          { id: 1, role: "user", text: "how's my month", channel: "web", at: "2026-11-27T01:00:00Z" },
          { id: 2, role: "nexus", text: "You're fine.", channel: "web", at: "2026-11-27T01:00:01Z", views: [{ kind: "finance.month_outlook", params: { month: "2026-11" }, focus: true }] },
        ],
        more: false,
        pending: null,
      },
    });
    draw();
    const card = await screen.findByRole("region", { name: "Your outlook for November 2026" });
    expect(await within(card).findByText("Left at month end")).toBeInTheDocument();
    expect(fetches).toContain("GET /views/finance.month_outlook");
  });

  it("draws no cards when views are off", async () => {
    const fetches = api({
      views: false,
      history: {
        lines: [{ id: 2, role: "nexus", text: "You're fine.", channel: "web", at: "2026-11-27T01:00:01Z", views: [{ kind: "finance.month_outlook", params: { month: "2026-11" }, focus: true }] }],
        more: false,
        pending: null,
      },
    });
    draw();
    expect(await screen.findByText("You're fine.")).toBeInTheDocument();
    await waitFor(() => expect(fetches).toContain("GET /config"));
    expect(screen.queryByRole("region")).toBeNull();
    expect(fetches.some((f) => f.startsWith("GET /views/"))).toBe(false);
  });

  it("draws no cards when the server doesn't say (an older one)", async () => {
    api({
      routes: { "GET /config": () => json({ bot_username: "b" }) },
      history: { lines: [{ id: 2, role: "nexus", text: "Hi.", channel: "web", at: "2026-11-27T01:00:01Z", views: [{ kind: "health.today", params: {}, focus: false }] }], more: false, pending: null },
    });
    draw();
    expect(await screen.findByText("Hi.")).toBeInTheDocument();
    expect(screen.queryByRole("region")).toBeNull();
  });
});

describe("Open", () => {
  const history: ChatHistory = {
    lines: [{ id: 2, role: "nexus", text: "You're fine.", channel: "web", at: "2026-11-27T01:00:01Z", views: [{ kind: "finance.month_outlook", params: { month: "2026-10" }, focus: true }] }],
    more: false,
    pending: null,
  };

  it("on a wide screen goes to the page behind the chat and leaves the chat open", async () => {
    phone(false);
    api({ history });
    const { onClose } = draw();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Open Your outlook/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/accounting?month=2026-10");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { hidden: true })).toBeInTheDocument();
  });

  it("on a phone closes the chat and goes to the page", async () => {
    phone(true);
    api({ history });
    const { onClose } = draw();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Open Your outlook/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/accounting?month=2026-10");
    expect(onClose).toHaveBeenCalled();
  });

  it("hands the page's path and the scroll position to the app when it takes over", async () => {
    phone(true);
    api({ history });
    const onOpenView = vi.fn();
    draw({ onOpenView });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Open Your outlook/ }));
    expect(onOpenView).toHaveBeenCalledWith("/accounting?month=2026-10", { phone: true, scroll: 0 });
  });
});

describe("coming back from a card's page", () => {
  it("scrolls the chat to where it was", async () => {
    api({ history: { lines: [{ id: 2, role: "nexus", text: "Hello.", channel: "web", at: "2026-11-27T01:00:01Z" }], more: false, pending: null } });
    draw({ restoreScroll: 140 });
    await screen.findByText("Hello.");
    await waitFor(() => expect(document.querySelector<HTMLElement>(".messages")!.scrollTop).toBe(140));
  });
});
