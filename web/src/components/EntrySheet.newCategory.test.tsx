import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Category, Me, Transaction } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { EntrySheet } from "./EntrySheet";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
  preferences: { track_cards: false },
};

const saved: Transaction = {
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

type Handlers = Parameters<typeof mockApi>[0];

function setup(list: Category[] = [{ id: "c-food", name: "Dining Out" }, { id: "c-pets", name: "Pets" }], extra: Handlers = {}) {
  let current = list;
  const calls = mockApi({
    "GET /categories": () => current,
    "GET /wallets": () => [],
    "GET /transactions/suggestions": () => [],
    "POST /transactions": () => saved,
    "POST /categories": (body) => {
      const made = { id: "c-new", name: String((body as { name: string }).name) };
      current = [...current, made];
      return made;
    },
    ...extra,
  });
  const onClose = vi.fn();
  renderWithProviders(<EntrySheet me={me} onClose={onClose} onSaved={vi.fn()} />);
  return { calls, onClose };
}

const select = () => screen.getByRole("combobox", { name: "Category" }) as HTMLSelectElement;
const optionTexts = () => Array.from(select().options).map((o) => o.text);
const newCategory = () => screen.getByRole("form", { name: "New category" });
const noNewCategory = () => expect(screen.queryByRole("form", { name: "New category" })).toBeNull();
const nameBox = () => within(newCategory()).getByLabelText("Name");
const addButton = () => within(newCategory()).getByRole("button", { name: "Add category" });
const posted = (calls: ReturnType<typeof mockApi>) => calls.filter((c) => c.method === "POST" && c.path === "/categories");
const written = (calls: ReturnType<typeof mockApi>) =>
  calls.find((c) => c.method === "POST" && c.path === "/transactions")?.body as Record<string, unknown>;

const ready = () => waitFor(() => expect(optionTexts()).toContain("Dining Out"));

describe("+ New category… in the entry sheet", () => {
  it("is the last option of the Category select, after Uncategorised and the categories", async () => {
    setup([{ id: "c-food", name: "Dining Out" }]);
    await ready();
    expect(optionTexts()).toEqual(["Uncategorised", "Dining Out", "+ New category…"]);
  });

  it("opens an inline form with a Name box, Add category and Cancel, leaving the select where it was", async () => {
    setup();
    await ready();
    await userEvent.selectOptions(select(), "Dining Out");
    await userEvent.selectOptions(select(), "+ New category…");
    expect(newCategory()).toBeTruthy();
    expect(nameBox()).toHaveAttribute("placeholder", "e.g. Pets");
    expect(nameBox()).toHaveFocus();
    expect(addButton()).toBeTruthy();
    expect(within(newCategory()).getByRole("button", { name: "Cancel new category" })).toBeTruthy();
    expect(select().value).toBe("c-food");
  });

  it("adds the category, selects it, keeps what was typed, and saves the expense with it", async () => {
    const { calls } = setup([{ id: "c-food", name: "Dining Out" }]);
    await ready();
    await userEvent.type(screen.getByLabelText("Amount"), "8.40");
    await userEvent.type(screen.getByLabelText("Paid to"), "Kopi");
    await userEvent.type(screen.getByLabelText("Notes"), "with Sam");
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.type(nameBox(), "  Pets ");
    await userEvent.click(addButton());

    await waitFor(noNewCategory);
    expect(posted(calls).map((c) => c.body)).toEqual([{ name: "Pets" }]);
    await waitFor(() => expect(select().value).toBe("c-new"));
    expect(select().selectedOptions[0].text).toBe("Pets");
    expect(screen.getByLabelText("Amount")).toHaveValue("8.40");
    expect(screen.getByLabelText("Paid to")).toHaveValue("Kopi");
    expect(screen.getByLabelText("Notes")).toHaveValue("with Sam");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ category_id: "c-new", counterparty: "Kopi", amount: "8.40" }));
  });

  it("never sends the option itself as a category", async () => {
    const { calls } = setup();
    await ready();
    await userEvent.type(screen.getByLabelText("Amount"), "5");
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.click(within(newCategory()).getByRole("button", { name: "Cancel new category" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ category_id: null }));
  });

  it("works for money in too", async () => {
    const { calls } = setup([{ id: "c-food", name: "Dining Out" }]);
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Money in" }));
    await userEvent.type(screen.getByLabelText("Amount"), "20");
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.type(nameBox(), "Gifts");
    await userEvent.click(addButton());
    await waitFor(() => expect(select().value).toBe("c-new"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ direction: "in", category_id: "c-new" }));
  });

  it("Cancel closes the form, returns the select to what it was, and keeps what was typed", async () => {
    const { calls } = setup();
    await ready();
    await userEvent.type(screen.getByLabelText("Amount"), "8.40");
    await userEvent.selectOptions(select(), "Dining Out");
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.type(nameBox(), "Pets");
    await userEvent.click(within(newCategory()).getByRole("button", { name: "Cancel new category" }));
    noNewCategory();
    expect(select().value).toBe("c-food");
    expect(screen.getByLabelText("Amount")).toHaveValue("8.40");
    expect(posted(calls)).toHaveLength(0);
    // Open again: the box starts empty.
    await userEvent.selectOptions(select(), "+ New category…");
    expect(nameBox()).toHaveValue("");
  });

  it("Cancel returns an untouched select to Uncategorised", async () => {
    setup();
    await ready();
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.click(within(newCategory()).getByRole("button", { name: "Cancel new category" }));
    noNewCategory();
    expect(select().value).toBe("");
    expect(select().selectedOptions[0].text).toBe("Uncategorised");
  });

  it("a name they already have, in any case, selects it with a note and creates nothing", async () => {
    const { calls } = setup();
    await ready();
    await userEvent.type(screen.getByLabelText("Amount"), "8.40");
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.type(nameBox(), " pETS");
    await userEvent.click(addButton());
    await waitFor(noNewCategory);
    expect(posted(calls)).toHaveLength(0);
    expect(select().value).toBe("c-pets");
    expect(screen.getByRole("status")).toHaveTextContent("You already have Pets, picked it.");
    expect(screen.getByLabelText("Amount")).toHaveValue("8.40");
    // Choosing something else clears the note.
    await userEvent.selectOptions(select(), "Dining Out");
    expect(screen.queryByText("You already have Pets, picked it.")).toBeNull();
  });

  it("shows the API's message in the form when it refuses a duplicate anyway", async () => {
    const { calls } = setup([{ id: "c-food", name: "Dining Out" }], {
      "POST /categories": () =>
        new Response(JSON.stringify({ detail: "a category with that name already exists" }), { status: 409 }),
    });
    await ready();
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.type(nameBox(), "Pets");
    await userEvent.click(addButton());
    expect(await within(newCategory()).findByRole("alert")).toHaveTextContent("a category with that name already exists");
    expect(posted(calls)).toHaveLength(1);
    expect(select().value).toBe("");
    expect(addButton()).toBeEnabled();
  });

  it("disables Add while the name is empty or only spaces", async () => {
    const { calls } = setup();
    await ready();
    await userEvent.selectOptions(select(), "+ New category…");
    expect(addButton()).toBeDisabled();
    await userEvent.type(nameBox(), "   ");
    expect(addButton()).toBeDisabled();
    await userEvent.type(nameBox(), "{Enter}");
    expect(posted(calls)).toHaveLength(0);
    await userEvent.type(nameBox(), "Rent");
    expect(addButton()).toBeEnabled();
  });

  it("does not save the entry while the form is open; Enter in the box adds the category, not the entry", async () => {
    const { calls } = setup([{ id: "c-food", name: "Dining Out" }]);
    await ready();
    await userEvent.type(screen.getByLabelText("Amount"), "5");
    await userEvent.selectOptions(select(), "+ New category…");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(nameBox(), "Pets{Enter}");
    await waitFor(noNewCategory);
    expect(posted(calls).map((c) => c.body)).toEqual([{ name: "Pets" }]);
    expect(calls.some((c) => c.method === "POST" && c.path === "/transactions")).toBe(false);
    await waitFor(() => expect(select().value).toBe("c-new"));
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("Escape closes only the form, then the sheet on the next press", async () => {
    const { calls, onClose } = setup();
    await ready();
    await userEvent.selectOptions(select(), "+ New category…");
    await userEvent.keyboard("{Escape}");
    noNewCategory();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
