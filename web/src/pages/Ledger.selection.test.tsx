import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me, Page, Transaction } from "../api";
import { type Call, mockApi, renderWithProviders } from "../testing";
import { Ledger } from "./Ledger";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};

const tx = (over: Partial<Transaction>): Transaction => ({
  id: "t1",
  direction: "out",
  amount: { amount: "12.40", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Corner Cafe",
  category_id: null,
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
  ...over,
});

const ITEMS = [tx({}), tx({ id: "t2", counterparty: "Mystery shop" }), tx({ id: "t3", counterparty: "Kopi Stall" })];

function setup() {
  const onEdit = vi.fn();
  const calls: Call[] = mockApi({
    "GET /transactions": () => ({ items: ITEMS, total: ITEMS.length }) satisfies Page,
    "GET /categories": () => [],
    "GET /category-rules": () => [],
    "GET /wallets": () => [],
    "POST /transactions/bulk-delete": (body) => ({ ids: (body as { ids: string[] }).ids }),
    "POST /transactions/bulk-restore": (body) => ({ ids: (body as { ids: string[] }).ids }),
  });
  renderWithProviders(<Ledger me={me} onAdd={vi.fn()} onEdit={onEdit} />);
  return { onEdit, calls };
}

const rowOf = (name: string) => screen.getByRole("button", { name }).closest("tr")!;
const touch = { pointerType: "touch", pointerId: 1, isPrimary: true, button: 0, clientX: 50, clientY: 50 };
const sleep = (ms: number) => act(() => new Promise<void>((done) => setTimeout(done, ms)));

/** Holds a finger on a row for as long as a long press takes, then lifts it and lets the click through. */
async function longPress(name: string) {
  const row = rowOf(name);
  fireEvent.pointerDown(row, touch);
  await sleep(550);
  fireEvent.pointerUp(row, touch);
  fireEvent.click(screen.getByRole("button", { name }));
}

afterEach(() => {
  delete window.Telegram;
});

describe("selecting Ledger rows by long press", () => {
  it("starts selecting with that row ticked, and doesn't open it", async () => {
    const { onEdit } = setup();
    await screen.findByText("Corner Cafe");
    await longPress("Mystery shop");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Select Mystery shop/ })).toBeChecked();
    expect(rowOf("Mystery shop")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Done" })).toHaveAttribute("aria-pressed", "true");
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("is not a long press when the finger moves first (a scroll) or lifts early", async () => {
    const { onEdit } = setup();
    await screen.findByText("Corner Cafe");
    const row = rowOf("Mystery shop");
    fireEvent.pointerDown(row, touch);
    fireEvent.pointerMove(row, { ...touch, clientY: 90 });
    await sleep(550);
    fireEvent.pointerUp(row, { ...touch, clientY: 90 });
    expect(screen.queryByText(/selected/)).toBeNull();

    fireEvent.pointerDown(row, touch);
    await sleep(200);
    fireEvent.pointerUp(row, touch);
    fireEvent.click(screen.getByRole("button", { name: "Mystery shop" }));
    expect(screen.queryByText(/selected/)).toBeNull();
    // A short tap opens the entry as ever.
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: "t2" }));
  });

  it("makes a tap tick or untick a row while selecting, instead of opening it", async () => {
    const { onEdit } = setup();
    await screen.findByText("Corner Cafe");
    await longPress("Mystery shop");
    await userEvent.click(screen.getByRole("button", { name: "Kopi Stall" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    // Anywhere on the row counts, not only the name.
    await userEvent.click(within(rowOf("Corner Cafe")).getByText("12.40", { exact: false }));
    expect(screen.getByText("3 selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Kopi Stall" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(rowOf("Kopi Stall")).toHaveAttribute("aria-selected", "false");
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("stays in selecting, with Delete off, when the last row is unticked, until Cancel", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    await longPress("Mystery shop");
    await userEvent.click(screen.getByRole("button", { name: "Mystery shop" }));
    expect(screen.getByText("0 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
    expect(screen.getByRole("button", { name: "Select" })).toHaveAttribute("aria-pressed", "false");
  });

  it("deletes the selected rows at once (no confirm step) and offers Undo", async () => {
    const { calls } = setup();
    await screen.findByText("Corner Cafe");
    await longPress("Mystery shop");
    await userEvent.click(screen.getByRole("button", { name: "Kopi Stall" }));
    const bar = screen.getByRole("region", { name: "Selection" });
    await userEvent.click(within(bar).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.getByText("Deleted 2 transactions.")).toBeInTheDocument());
    const deleted = calls.find((c) => c.path === "/transactions/bulk-delete");
    expect(deleted?.body).toEqual({ ids: ["t2", "t3"] });
    // Selecting is over.
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
    expect(screen.getByRole("button", { name: "Select" })).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.getByText("Restored.")).toBeInTheDocument());
    expect(calls.find((c) => c.path === "/transactions/bulk-restore")?.body).toEqual({ ids: ["t2", "t3"] });
  });

  it("clears the selection on Cancel and leaves the rows alone", async () => {
    const { calls, onEdit } = setup();
    await screen.findByText("Corner Cafe");
    await longPress("Mystery shop");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/selected/)).toBeNull();
    expect(screen.queryAllByRole("checkbox", { checked: true })).toHaveLength(0);
    expect(calls.some((c) => c.path === "/transactions/bulk-delete")).toBe(false);
    // Taps open rows again.
    await userEvent.click(screen.getByRole("button", { name: "Mystery shop" }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("keeps the Select button, and announces the count politely", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    const count = screen.getByText("0 selected");
    expect(count).toHaveAttribute("aria-live", "polite");
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Kopi Stall/ }));
    expect(count).toHaveTextContent("1 selected");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("opens an entry from the keyboard when not selecting, and ticks it when selecting", async () => {
    const { onEdit } = setup();
    await screen.findByText("Corner Cafe");
    screen.getByRole("button", { name: "Kopi Stall" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onEdit).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    screen.getByRole("button", { name: "Kopi Stall" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("gives a haptic when the long press takes hold and a tick on later toggles", async () => {
    const impactOccurred = vi.fn();
    const selectionChanged = vi.fn();
    window.Telegram = { WebApp: { ready() {}, expand() {}, HapticFeedback: { impactOccurred, selectionChanged } } };
    setup();
    await screen.findByText("Corner Cafe");
    await longPress("Mystery shop");
    expect(impactOccurred).toHaveBeenCalledWith("medium");
    expect(selectionChanged).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Kopi Stall" }));
    expect(selectionChanged).toHaveBeenCalledTimes(1);
  });
});
