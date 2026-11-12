import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Cover, Money, Prep, PrepSuggestion, Todo, Trip, TripDetail } from "../api";
import { type Call, mockApi, renderWithProviders } from "../testing";
import { MoneyTab } from "./TripMoney";
import { PrepTab } from "./TripPrep";
import { coverDates, dueLine } from "./TripPrepParts";

const plain = (text: string | null) => (text ?? "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
const sgd = (amount: string): Money => ({ amount, currency: "SGD" });

const trip = (extra: Partial<Trip> = {}): Trip => ({
  id: "t1",
  destination: "Tokyo",
  start: "2027-04-01",
  end: "2027-04-09",
  days: 9,
  currency: "JPY",
  budget: sgd("3000"),
  companions: [],
  set_aside: null,
  planned: {},
  status: "upcoming",
  days_until: 90,
  day_number: null,
  notes: null,
  day_labels: {},
  stops: [],
  split_evenly: true,
  role: "owner",
  owner_name: null,
  ...extra,
});

const todo = (id: string, text: string, extra: Partial<Todo> = {}): Todo => ({ id, text, due: null, done: false, ...extra });
const cover = (id: string, extra: Partial<Cover> = {}): Cover => ({
  id,
  kind: "insurance",
  name: "Harbour Cover",
  reference: "TX-4471",
  phone: "+65 6123 4567",
  starts: "2027-04-02",
  ends: "2027-04-09",
  cost: sgd("89"),
  logged: false,
  note: null,
  ...extra,
});
const suggestion = (key: string, text: string, action: PrepSuggestion["action"], sub = "Why"): PrepSuggestion => ({ key, text, sub, action });

function detail(extra: Omit<Partial<TripDetail>, "trip"> & { trip?: Partial<Trip> } = {}): TripDetail {
  const { trip: tripExtra, ...rest } = extra;
  return {
    trip: trip(tripExtra),
    bookings: [],
    suggested_stops: [],
    places: false,
    booked: null,
    booked_unlogged: null,
    to_spend: null,
    ready: { nights_without_stay: [], has_transport: true, has_budget: true, done: 3, total: 3 },
    spending: { spent: sgd("0"), left: null, percent: null, before: sgd("0"), today: null, per_day: null, per_day_left: null, categories: [], unconverted: 0 },
    saving: null,
    owed: [],
    to_split: [],
    just_mine: [],
    paid_by_others: [],
    balances: [],
    items: [],
    todos: [],
    covers: [],
    prep_suggestions: [],
    ...rest,
  };
}

const me = { "GET /me": () => ({ user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" } }) };

function show(d: TripDetail, props: { adding?: boolean; onFix?: () => void } = {}) {
  const onChange = vi.fn();
  const onAddDone = vi.fn();
  renderWithProviders(<PrepTab detail={d} onChange={onChange} onFix={props.onFix ?? vi.fn()} adding={props.adding ?? false} onAddDone={onAddDone} />);
  return { onChange, onAddDone };
}

const ready = () => screen.getByRole("region", { name: "Getting ready" });
const coverCard = () => screen.getByRole("region", { name: "Cover and documents" });
const rowTitles = () => within(within(ready()).getByRole("list", { name: "Things to do" })).getAllByRole("listitem").map((li) => plain(li.querySelector(".prep-title")?.textContent ?? ""));

afterEach(() => vi.restoreAllMocks());

describe("Getting ready", () => {
  const mixed = () =>
    detail({
      ready: { nights_without_stay: ["2027-04-02", "2027-04-03"], has_transport: true, has_budget: true, done: 2, total: 3 },
      prep_suggestions: [suggestion("insurance", "Travel insurance", "add_cover", "Medical and cancellation cover")],
      todos: [todo("a", "Book airport taxi", { done: true }), todo("b", "Buy a power adapter"), todo("c", "Print tickets")],
    });

  it("merges the gaps, the suggestions and the to-dos, with a count, and done to-dos sink to the bottom", () => {
    show(mixed());
    expect(plain(ready().textContent)).toContain("4 to do");
    expect(rowTitles()).toEqual([expect.stringMatching(/^2 nights without a place to stay/), "Travel insurance", "Buy a power adapter", "Print tickets", "Book airport taxi"]);
    expect(within(ready()).getByRole("checkbox", { name: "Book airport taxi" })).toBeChecked();
    expect(within(ready()).getByText("Book airport taxi").closest("li")).toHaveClass("is-done");
  });

  it("keeps the Fix action of a gap", async () => {
    const onFix = vi.fn();
    show(mixed(), { onFix });
    await userEvent.click(within(ready()).getByRole("button", { name: /^Add: 2 nights without a place to stay/ }));
    expect(onFix).toHaveBeenCalledWith({ kind: "hotel", day: "2027-04-02" });
  });

  it("says all sorted when nothing is left, and a member is not asked for a budget", () => {
    show(detail({ todos: [todo("a", "Done thing", { done: true })] }));
    expect(within(ready()).getByRole("status")).toHaveTextContent("All sorted: a place every night, a way there and a budget.");
    expect(plain(ready().textContent)).not.toContain("to do");
  });

  it("adds a to-do with a date, and the form clears", async () => {
    const calls = mockApi({
      ...me,
      "PUT /travel/trips/t1/todos": () => ({ todos: [todo("n1", "Book the taxi", { due: "2099-12-08" })], covers: [], prep_suggestions: [] }),
    });
    const { onChange } = show(detail());
    expect(within(ready()).getByText("With a date, Nexus reminds you the day before.")).toBeInTheDocument();
    await userEvent.type(within(ready()).getByLabelText("To-do"), "Book the taxi");
    await userEvent.type(within(ready()).getByLabelText("By (optional)"), "2099-12-08");
    await userEvent.click(within(ready()).getByRole("button", { name: /^Add$/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ todos: [{ text: "Book the taxi", due: "2099-12-08", done: false }] }));
    expect(await within(ready()).findByRole("checkbox", { name: "Book the taxi" })).toBeInTheDocument();
    expect(within(ready()).getByText("By Tue 8 Dec")).toBeInTheDocument();
    expect(within(ready()).getByLabelText("To-do")).toHaveValue("");
    expect(onChange).toHaveBeenCalled();
  });

  it("ticking a to-do sends the whole list with it done", async () => {
    const calls = mockApi({
      ...me,
      "PUT /travel/trips/t1/todos": () => ({ todos: [todo("a", "Print tickets", { done: true }), todo("b", "Buy a power adapter", { due: "2099-12-08" })], covers: [], prep_suggestions: [] }),
    });
    show(detail({ todos: [todo("a", "Print tickets"), todo("b", "Buy a power adapter", { due: "2099-12-08" })] }));
    await userEvent.click(within(ready()).getByRole("checkbox", { name: "Print tickets" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ todos: [{ id: "a", text: "Print tickets", due: null, done: true }, { id: "b", text: "Buy a power adapter", due: "2099-12-08", done: false }] }));
    // It sinks below the one still to do.
    await waitFor(() => expect(rowTitles()).toEqual(["Buy a power adapter", "Print tickets"]));
  });

  it("puts a to-do back when it can't be saved, and says so", async () => {
    mockApi({ ...me });
    show(detail({ todos: [todo("a", "Print tickets")] }));
    await userEvent.click(within(ready()).getByRole("checkbox", { name: "Print tickets" }));
    expect(await within(ready()).findByRole("alert")).toBeInTheDocument();
    expect(within(ready()).getByRole("checkbox", { name: "Print tickets" })).not.toBeChecked();
  });

  it("removes a to-do from the list", async () => {
    const calls = mockApi({ ...me, "PUT /travel/trips/t1/todos": () => ({ todos: [todo("b", "Keep me")], covers: [], prep_suggestions: [] }) });
    show(detail({ todos: [todo("a", "Drop me"), todo("b", "Keep me")] }));
    await userEvent.click(within(ready()).getByRole("button", { name: "Remove Drop me" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ todos: [{ id: "b", text: "Keep me", due: null, done: false }] }));
    expect(within(ready()).queryByText("Drop me")).toBeNull();
  });

  it("shows a date past and not done as overdue, in the warning style", () => {
    show(detail({ todos: [todo("a", "Renew passport", { due: "2020-01-06" }), todo("b", "Old and done", { due: "2020-01-06", done: true })] }));
    const overdue = within(ready()).getByText("Overdue · Mon 6 Jan");
    expect(overdue).toHaveClass("is-overdue");
    expect(within(ready()).getByText("By Mon 6 Jan")).not.toHaveClass("is-overdue");
    expect(dueLine(todo("x", "x", { due: "2099-12-08" }), "2026-10-20")).toEqual({ text: "By Tue 8 Dec", overdue: false });
  });

  it("'Not needed' dismisses a suggestion", async () => {
    const after: Prep = { todos: [], covers: [], prep_suggestions: [] };
    const calls = mockApi({ ...me, "POST /travel/trips/t1/prep/dismiss": () => after });
    show(detail({ prep_suggestions: [suggestion("passport", "Passport valid 6 months after you're back", "add_todo", "Many countries ask for it")] }));
    expect(within(ready()).getByText("Many countries ask for it")).toBeInTheDocument();
    await userEvent.click(within(ready()).getByRole("button", { name: /^Not needed: Passport valid/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ key: "passport" }));
    await waitFor(() => expect(within(ready()).queryByText(/Passport valid/)).toBeNull());
  });

  it("a suggestion that adds a to-do adds it with its text", async () => {
    const calls = mockApi({
      ...me,
      "PUT /travel/trips/t1/todos": () => ({ todos: [todo("n1", "Check entry rules for Japan")], covers: [], prep_suggestions: [] }),
    });
    show(detail({ prep_suggestions: [suggestion("visa", "Check entry rules for Japan", "add_todo")] }));
    await userEvent.click(within(ready()).getByRole("button", { name: "Add: Check entry rules for Japan" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ todos: [{ text: "Check entry rules for Japan", due: null, done: false }] }));
    expect(await within(ready()).findByRole("checkbox", { name: "Check entry rules for Japan" })).toBeInTheDocument();
  });

  it("a suggestion that adds cover opens the cover sheet with its kind chosen", async () => {
    mockApi({ ...me });
    show(detail({ prep_suggestions: [suggestion("visa", "Check a visa", "add_cover")] }));
    await userEvent.click(within(ready()).getByRole("button", { name: "Add: Check a visa" }));
    const sheet = await screen.findByRole("dialog", { name: "Add cover or a document" });
    expect(within(sheet).getByRole("radio", { name: "Visa" })).toBeChecked();
    expect(within(sheet).getByRole("radio", { name: "Insurance" })).not.toBeChecked();
    expect(within(sheet).getByLabelText("Name")).toBeInTheDocument();
  });

  it("an insurance suggestion presets Insurance, whose name is called the insurer", async () => {
    mockApi({ ...me });
    show(detail({ prep_suggestions: [suggestion("insurance", "Travel insurance", "add_cover")] }));
    await userEvent.click(within(ready()).getByRole("button", { name: "Add: Travel insurance" }));
    const sheet = await screen.findByRole("dialog", { name: "Add cover or a document" });
    expect(within(sheet).getByRole("radio", { name: "Insurance" })).toBeChecked();
    expect(within(sheet).getByLabelText("Insurer")).toBeInTheDocument();
  });

  it("is left out for a trip that is over, apart from to-dos still there", () => {
    const { unmount } = renderWithProviders(<PrepTab detail={detail({ trip: { status: "finished", days_until: -20 } })} onChange={vi.fn()} onFix={vi.fn()} adding={false} onAddDone={() => undefined} />);
    expect(screen.queryByRole("region", { name: "Getting ready" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Cover and documents" })).toBeNull();
    unmount();
  });
});

describe("Cover and documents", () => {
  it("is empty with one line, a way to add and what to tell Nexus", async () => {
    mockApi({ ...me });
    show(detail());
    const card = coverCard();
    expect(within(card).getByText("Travel insurance, visas and other documents go here.")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Add cover or a document" })).toBeInTheDocument();
    expect(plain(card.textContent)).toContain('Or tell Nexus: "Add travel insurance, Harbour Cover, SGD 89, policy TX-4471".');
  });

  it("a row has its icon's name, one line, the cost, a Log it, a call link and a copy button", async () => {
    mockApi({ ...me });
    const written = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: written }, configurable: true });
    show(detail({ covers: [cover("c1")] }));
    const row = within(coverCard()).getByRole("listitem");
    expect(plain(row.textContent)).toContain("Harbour Cover");
    expect(plain(row.textContent)).toContain("Insurance · TX-4471 · 2–9 Apr");
    expect(plain(row.textContent)).toContain("SGD 89.00");
    expect(within(row).getByRole("link", { name: "Call +65 6123 4567" })).toHaveAttribute("href", "tel:+6561234567");
    expect(within(row).getByRole("button", { name: "Log it: Harbour Cover" })).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Copy reference TX-4471" }));
    expect(written).toHaveBeenCalledWith("TX-4471");
    expect(await within(row).findByText("Copied")).toBeInTheDocument();
  });

  it("a member's row has no cost and no Log it, and a logged cover says Logged", () => {
    const { unmount } = renderWithProviders(
      <PrepTab detail={detail({ trip: { role: "member" }, covers: [cover("c1", { cost: null })] })} onChange={vi.fn()} onFix={vi.fn()} adding={false} onAddDone={() => undefined} />,
    );
    const row = within(coverCard()).getByRole("listitem");
    expect(plain(row.textContent)).not.toContain("SGD");
    expect(within(row).queryByRole("button", { name: /Log it/ })).toBeNull();
    expect(within(row).queryByText("Logged")).toBeNull();
    unmount();
    show(detail({ covers: [cover("c1", { logged: true })] }));
    const logged = within(coverCard()).getByRole("listitem");
    expect(within(logged).getByText("Logged")).toBeInTheDocument();
    expect(within(logged).queryByRole("button", { name: /Log it/ })).toBeNull();
  });

  it("asks in place before logging, records on Log it, and Not now changes nothing", async () => {
    const calls = mockApi({ ...me, "POST /travel/trips/t1/covers/c1/log": () => cover("c1", { logged: true }) });
    const { onChange } = show(detail({ covers: [cover("c1")] }));
    const row = within(coverCard()).getByRole("listitem");
    await userEvent.click(within(row).getByRole("button", { name: "Log it: Harbour Cover" }));
    const box = within(row).getByRole("group", { name: "Log Harbour Cover" });
    expect(plain(box.textContent)).toContain("Record SGD 89.00 as spent on Travel? Nexus only records it.");
    await userEvent.click(within(box).getByRole("button", { name: "Not now" }));
    expect(within(row).queryByRole("group")).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);

    await userEvent.click(within(row).getByRole("button", { name: "Log it: Harbour Cover" }));
    await userEvent.click(within(within(row).getByRole("group")).getByRole("button", { name: "Log it" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/travel/trips/t1/covers/c1/log")).toBe(true));
    expect(await within(row).findByText("Logged")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalled();
  });

  it("shows why a log was refused", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ detail: "this cost is already logged as an expense" }), { status: 409 }));
    show(detail({ covers: [cover("c1")] }));
    const row = within(coverCard()).getByRole("listitem");
    await userEvent.click(within(row).getByRole("button", { name: "Log it: Harbour Cover" }));
    await userEvent.click(within(within(row).getByRole("group")).getByRole("button", { name: "Log it" }));
    expect(await within(row).findByRole("alert")).toHaveTextContent("this cost is already logged as an expense");
  });

  it("tapping the row opens it to change, and saves the whole cover", async () => {
    const calls = mockApi({ ...me, "PUT /travel/trips/t1/covers/c1": () => cover("c1", { name: "Harbour Cover Plus" }) });
    const { onChange } = show(detail({ covers: [cover("c1")] }));
    await userEvent.click(within(coverCard()).getByRole("button", { name: /^Harbour Cover/ }));
    const sheet = await screen.findByRole("dialog", { name: "Change Harbour Cover" });
    expect(within(sheet).getByRole("radio", { name: "Insurance" })).toBeChecked();
    expect(within(sheet).getByLabelText("Insurer")).toHaveValue("Harbour Cover");
    expect(within(sheet).getByLabelText("Policy or reference")).toHaveValue("TX-4471");
    expect(within(sheet).getByLabelText("Emergency phone")).toHaveAttribute("type", "tel");
    expect(within(sheet).getByLabelText("Cost")).toHaveValue("89");
    await userEvent.type(within(sheet).getByLabelText("Insurer"), " Plus");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      kind: "insurance",
      name: "Harbour Cover Plus",
      reference: "TX-4471",
      phone: "+65 6123 4567",
      starts: "2027-04-02",
      ends: "2027-04-09",
      note: null,
      cost: "89",
      currency: "SGD",
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(coverCard()).getByText("Harbour Cover Plus")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalled();
  });

  it("adds a cover from the sheet and shows an error from the server in it", async () => {
    let fail = true;
    const calls: Call[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      calls.push({ method: init?.method ?? "GET", path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (path === "/me") return new Response(JSON.stringify(me["GET /me"]()), { status: 200 });
      if (init?.method !== "POST") return new Response("null", { status: 200 });
      if (fail) {
        fail = false;
        return new Response(JSON.stringify({ detail: "a cover can't end before it starts" }), { status: 422 });
      }
      return new Response(JSON.stringify(cover("c9", { kind: "visa", name: "Japan e-visa", reference: null, phone: null, starts: null, ends: null, cost: null })), { status: 201 });
    });
    show(detail());
    await userEvent.click(within(coverCard()).getByRole("button", { name: "Add cover or a document" }));
    const sheet = await screen.findByRole("dialog", { name: "Add cover or a document" });
    await userEvent.click(within(sheet).getByRole("radio", { name: "Visa" }));
    await userEvent.type(within(sheet).getByLabelText("Name"), "Japan e-visa");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("a cover can't end before it starts");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((c) => c.method === "POST")[1].body).toEqual({ kind: "visa", name: "Japan e-visa", reference: null, phone: null, starts: null, ends: null, note: null, cost: null, currency: null });
    expect(within(coverCard()).getByText("Japan e-visa")).toBeInTheDocument();
  });

  it("a member's sheet has no cost fields and sends none", async () => {
    const calls = mockApi({ ...me, "PUT /travel/trips/t1/covers/c1": () => cover("c1", { cost: null }) });
    show(detail({ trip: { role: "member" }, covers: [cover("c1", { cost: null })] }));
    await userEvent.click(within(coverCard()).getByRole("button", { name: /^Harbour Cover/ }));
    const sheet = await screen.findByRole("dialog", { name: "Change Harbour Cover" });
    expect(within(sheet).queryByLabelText("Cost")).toBeNull();
    expect(within(sheet).queryByLabelText("Currency")).toBeNull();
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")).toBeDefined());
    expect(Object.keys(calls.find((c) => c.method === "PUT")!.body as object)).not.toContain("cost");
  });

  it("deletes from inside the sheet, asked first", async () => {
    const calls = mockApi({ ...me, "DELETE /travel/trips/t1/covers/c1": () => null });
    show(detail({ covers: [cover("c1")] }));
    await userEvent.click(within(coverCard()).getByRole("button", { name: /^Harbour Cover/ }));
    const sheet = await screen.findByRole("dialog", { name: "Change Harbour Cover" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([]);
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete Harbour Cover" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/travel/trips/t1/covers/c1")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(coverCard()).queryByText("Harbour Cover")).toBeNull();
  });

  it("formats the dates a cover holds", () => {
    expect(coverDates("2027-12-02", "2027-12-09")).toBe("2–9 Dec");
    expect(coverDates("2027-11-28", "2027-12-03")).toBe("28 Nov – 3 Dec");
    expect(coverDates("2027-12-02", "2027-12-02")).toBe("2 Dec");
    expect(coverDates("2027-12-02", null)).toBe("from 2 Dec");
    expect(coverDates(null, "2027-12-09")).toBe("until 9 Dec");
    expect(coverDates(null, null)).toBe("");
  });
});

describe("the + on Prep", () => {
  it("asks what to add, and each choice goes to its form", async () => {
    mockApi({ ...me });
    const { onAddDone } = show(detail(), { adding: true });
    const choose = await screen.findByRole("dialog", { name: "Add to prep" });
    expect(onAddDone).toHaveBeenCalled();
    expect(within(choose).getAllByRole("button").map((b) => plain(b.textContent))).toEqual(expect.arrayContaining([expect.stringContaining("A to-do"), expect.stringContaining("Cover or a document"), expect.stringContaining("Something to pack")]));
    await userEvent.click(within(choose).getByRole("button", { name: /Cover or a document/ }));
    expect(await screen.findByRole("dialog", { name: "Add cover or a document" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Add to prep" })).toBeNull();
  });

  it("a to-do puts the cursor in its field, and something to pack in the packing field", async () => {
    mockApi({ ...me });
    const first = renderWithProviders(<PrepTab detail={detail()} onChange={vi.fn()} onFix={vi.fn()} adding onAddDone={() => undefined} />);
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Add to prep" })).getByRole("button", { name: /A to-do/ }));
    await waitFor(() => expect(screen.getByLabelText("To-do")).toHaveFocus());
    first.unmount();

    renderWithProviders(<PrepTab detail={detail()} onChange={vi.fn()} onFix={vi.fn()} adding onAddDone={() => undefined} />);
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Add to prep" })).getByRole("button", { name: /Something to pack/ }));
    await waitFor(() => expect(screen.getByLabelText("Thing to pack")).toHaveFocus());
  });
});

describe("Packing list", () => {
  it("keeps its names: the list, the checkboxes, Remove and the count", async () => {
    const calls = mockApi({ ...me, "PUT /travel/trips/t1/packing": () => trip({ packing: [{ text: "Passport", done: true }, { text: "Charger", done: false }] }) });
    show(detail({ trip: { packing: [{ text: "Passport", done: false }, { text: "Charger", done: false }] } }));
    const packing = screen.getByRole("region", { name: "Packing list" });
    expect(within(packing).getByRole("list", { name: "Things to pack" })).toBeInTheDocument();
    await userEvent.click(within(packing).getByRole("checkbox", { name: "Passport" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ items: [{ text: "Passport", done: true }, { text: "Charger", done: false }] }));
    expect(await within(packing).findByText("1 of 2 packed")).toBeInTheDocument();
    expect(within(packing).getByRole("button", { name: "Remove Charger" })).toBeInTheDocument();
    expect(within(packing).getByLabelText("Thing to pack")).toBeInTheDocument();
  });
});

describe("Money: Bookings paid", () => {
  it("lists a cover with a cost after the bookings, with Logged or Log it asked first", async () => {
    const calls = mockApi({ ...me, "POST /travel/trips/t1/covers/c2/log": () => cover("c2", { logged: true }) });
    const onChange = vi.fn();
    renderWithProviders(
      <MoneyTab
        detail={detail({ covers: [cover("c1", { kind: "visa", name: "Japan e-visa", cost: sgd("30"), logged: true }), cover("c2"), cover("c3", { name: "No cost", cost: null })] })}
        onChange={onChange}
        adding={false}
        onAddDone={() => undefined}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^Bookings paid/ }));
    const list = await screen.findByRole("list", { name: "Bookings paid" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(plain(rows[0].textContent)).toContain("Japan e-visa");
    expect(plain(rows[0].textContent)).toContain("Visa · from Prep");
    expect(plain(rows[0].textContent)).toContain("SGD 30.00");
    expect(within(rows[0]).getByText("Logged")).toBeInTheDocument();
    expect(plain(rows[1].textContent)).toContain("Harbour Cover");
    expect(plain(rows[1].textContent)).toContain("Insurance · from Prep");
    await userEvent.click(within(rows[1]).getByRole("button", { name: "Log it: Harbour Cover" }));
    const box = within(rows[1]).getByRole("group", { name: "Log Harbour Cover" });
    expect(plain(box.textContent)).toContain("Record SGD 89.00 as spent on Travel? Nexus only records it.");
    await userEvent.click(within(box).getByRole("button", { name: "Log it" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/travel/trips/t1/covers/c2/log")).toBe(true));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it("is left out when there are no bookings and no covers with a cost", () => {
    renderWithProviders(<MoneyTab detail={detail({ covers: [cover("c3", { cost: null })] })} onChange={vi.fn()} adding={false} onAddDone={() => undefined} />);
    expect(screen.queryByRole("button", { name: /^Bookings paid/ })).toBeNull();
  });
});
