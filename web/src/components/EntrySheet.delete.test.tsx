import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Me, Transaction } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { EntrySheet } from "./EntrySheet";

const me: Me = {
  user: { telegram_user_id: 77, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};

const existing: Transaction = {
  id: "t9",
  direction: "out",
  amount: { amount: "5.00", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Kopi",
  category_id: null,
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
};

function setup(props: { editing?: Transaction; withDeleted?: boolean; del?: () => unknown } = {}) {
  const { editing, withDeleted = true, del = () => ({ ...existing, deleted: true }) } = props;
  const calls = mockApi({
    "GET /categories": () => [],
    "GET /wallets": () => [],
    "GET /transactions/suggestions": () => [],
    "GET /transactions/t9/category-explanation": () => ({ text: "" }),
    "DELETE /transactions/t9": del,
  });
  const onDeleted = vi.fn();
  const onSaved = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(
    <EntrySheet me={me} editing={editing} onClose={onClose} onSaved={onSaved} onDeleted={withDeleted ? onDeleted : undefined} />,
  );
  return { calls, onDeleted, onSaved, onClose };
}

describe("deleting from the edit sheet", () => {
  it("has a Delete button, apart from Save, that deletes the entry and hands it to onDeleted", async () => {
    const { calls, onDeleted, onSaved } = setup({ editing: existing });
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button).toHaveClass("btn-danger");
    // First in the row of actions, so bottom-left; Save stays where it was.
    const actions = button.parentElement!;
    expect(actions.firstElementChild).toBe(button);
    await userEvent.click(button);
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(expect.objectContaining({ id: "t9", deleted: true })));
    expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/transactions/t9"]);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("is not there for a new entry", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("is not there for an entry already deleted, or when the page can't take a deletion", () => {
    setup({ editing: { ...existing, deleted: true } });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("is not there when nothing handles onDeleted", () => {
    setup({ editing: existing, withDeleted: false });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("is off with no connection", () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    setup({ editing: existing });
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("says why when the server refuses, and keeps the sheet open", async () => {
    const { onDeleted, onClose } = setup({
      editing: existing,
      del: () => new Response(JSON.stringify({ detail: "transaction not found" }), { status: 404 }),
    });
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("transaction not found");
    expect(onDeleted).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
