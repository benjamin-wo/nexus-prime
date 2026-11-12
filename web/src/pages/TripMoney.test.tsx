import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Balance, BalancePart, Booking, Money, ToSplit, Trip, TripDetail } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { MoneyTab } from "./TripMoney";

// Made-up people and amounts only. Intl puts a no-break space after the currency code.
const plain = (text: string | null) => (text ?? "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
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

const cost = (id: string, counterparty: string, amount: string): ToSplit => ({
  transaction_id: id,
  day: "2027-04-02",
  counterparty,
  category: null,
  amount: sgd(amount),
  home: sgd(amount),
});

const part = (kind: BalancePart["kind"], amount: Money, label: string): BalancePart => ({ kind, id: label, label, amount, home: amount, on: "2027-04-03" });
const balance = (person: string, net: Money, extra: Partial<Balance> = {}): Balance => ({
  person,
  direction: Number(net.amount) > 0 ? "owes_you" : "you_owe",
  net,
  net_by_currency: [net],
  owes_you: [],
  you_owe: [],
  ...extra,
});

/** A trip's detail as the owner sees it, with only what a test cares about changed. */
function detail(extra: Partial<TripDetail> & { trip?: Partial<Trip> } = {}): TripDetail {
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
    spending: {
      spent: sgd("0"),
      left: null,
      percent: null,
      before: sgd("0"),
      today: null,
      per_day: null,
      per_day_left: null,
      categories: [],
      unconverted: 0,
    },
    saving: null,
    owed: [],
    to_split: [],
    just_mine: [],
    paid_by_others: [],
    balances: [],
    items: [],
    ...rest,
  };
}

const spending = (spent: string, extra: Partial<NonNullable<TripDetail["spending"]>> = {}): NonNullable<TripDetail["spending"]> => ({
  spent: sgd(spent),
  left: null,
  percent: null,
  before: sgd("0"),
  today: null,
  per_day: null,
  per_day_left: null,
  categories: [],
  unconverted: 0,
  ...extra,
});

function show(d: TripDetail, onChange = vi.fn()) {
  renderWithProviders(<MoneyTab detail={d} onChange={onChange} adding={false} onAddDone={() => undefined} />);
  return onChange;
}

const card = (name: string) => screen.getByRole("region", { name });

describe("the summary", () => {
  const planning = () =>
    detail({
      trip: { planned: { "Dining Out": sgd("600") } },
      spending: spending("818", { categories: [{ name: "Dining Out", planned: sgd("600"), spent: sgd("18") }] }),
      booked: sgd("820"),
      booked_unlogged: sgd("820"),
    });

  it("before the trip: spent and booked against the budget, the parts, and what is left after planned costs", () => {
    show(planning());
    const summary = card("Spent and booked");
    expect(plain(summary.textContent)).toContain("SGD 1,638.00 of SGD 3,000.00");
    expect(plain(summary.textContent)).toContain("Spent SGD 818.00 · Booked SGD 820.00 · Planned SGD 582.00");
    expect(plain(summary.textContent)).toContain("Left after planned costs SGD 780.00");
    expect(plain(within(summary).getByRole("img").getAttribute("aria-label"))).toBe("spent SGD 818.00, booked SGD 820.00, planned SGD 582.00 of SGD 3,000.00");
    expect(summary.querySelectorAll(".money-seg")).toHaveLength(3);
  });

  it("says Over by, in the warning style, when planned costs do not fit", () => {
    show({ ...planning(), trip: trip({ budget: sgd("1000"), planned: { "Dining Out": sgd("600") } }) });
    const over = within(card("Spent and booked")).getByText(/^Over by/);
    expect(plain(over.textContent)).toBe("Over by SGD 1,220.00");
    expect(over.className).toContain("money-over");
  });

  it("leaves out a part that is zero", () => {
    show(detail({ spending: spending("90") }));
    const summary = card("Spent and booked");
    expect(plain(summary.textContent)).toContain("Spent SGD 90.00");
    expect(plain(summary.textContent)).not.toContain("Booked");
    expect(plain(summary.textContent)).not.toContain("Planned");
  });

  it("without a budget there is no 'of', no bar and no 'left'", () => {
    show(detail({ trip: { budget: null }, spending: spending("90"), booked_unlogged: sgd("200"), booked: sgd("200") }));
    const summary = card("Spent and booked");
    expect(plain(summary.textContent)).toContain("SGD 290.00");
    expect(plain(summary.textContent)).toContain("Spent SGD 90.00 · Booked SGD 200.00");
    expect(plain(summary.textContent)).not.toContain(" of ");
    expect(plain(summary.textContent)).not.toContain("Left after");
    expect(within(summary).queryByRole("img")).toBeNull();
  });

  it("while the trip is on: spent so far, with today and what is left a day", () => {
    show(
      detail({
        trip: { status: "ongoing", days_until: 0, day_number: 3 },
        spending: spending("500", { today: sgd("25"), per_day_left: sgd("250") }),
      }),
    );
    const summary = card("Spent so far");
    expect(plain(summary.textContent)).toContain("SGD 500.00 of SGD 3,000.00");
    expect(plain(summary.textContent)).toContain("SGD 250.00 a day left for 7 days · SGD 25.00 today");
    expect(plain(summary.textContent)).toContain("Log what you spend on Telegram");
  });

  it("after the trip: what it cost, against the budget, and your share", () => {
    show(detail({ trip: { status: "finished", days_until: -20, companions: ["Alex"] }, spending: spending("2640") }));
    const summary = card("The trip cost");
    expect(plain(summary.textContent)).toContain("SGD 2,640.00 of SGD 3,000.00");
    expect(plain(summary.textContent)).toContain("12% under budget");
    expect(plain(summary.textContent)).toContain("Your share, with Alex");
  });

  it("after the trip, To do comes before the summary", () => {
    show(detail({ trip: { status: "finished", days_until: -20, companions: ["Alex"] }, spending: spending("2640") }));
    const todo = card("To do");
    const summary = card("The trip cost");
    expect(todo.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("To do", () => {
  const costs = [cost("a", "Wi-Fi", "12.40"), cost("b", "teamLab", "300"), cost("c", "Ryokan deposit", "300")];

  it("is not there when nobody else is going and nothing is waiting", () => {
    show(detail());
    expect(screen.queryByRole("region", { name: "To do" })).toBeNull();
  });

  it("says when everything is split and settled", () => {
    show(detail({ trip: { companions: ["Alex", "Sam"] } }));
    expect(plain(card("To do").textContent)).toContain("All split and settled with Alex and Sam.");
    expect(within(card("To do")).queryByRole("button")).toBeNull();
  });

  it("offers the costs to split, and asks in place before splitting", async () => {
    const calls = mockApi({
      "POST /travel/trips/t1/split": () => ({
        with_people: ["Alex"],
        done: costs.map((c) => ({ transaction_id: c.transaction_id, counterparty: c.counterparty, amount: c.amount, own_share: sgd("150") })),
        skipped: [],
      }),
    });
    const user = userEvent.setup();
    const onChange = show(detail({ trip: { companions: ["Alex"] }, to_split: costs }));
    const todo = card("To do");
    expect(plain(todo.textContent)).toContain("3 costs to split");
    expect(plain(todo.textContent)).toContain("SGD 612.40 · Wi-Fi, teamLab, Ryokan deposit");
    expect(plain(todo.textContent)).not.toContain("All split and settled");

    await user.click(within(todo).getByRole("button", { name: "Split all evenly" }));
    const confirm = within(todo).getByRole("group", { name: "Confirm splitting all" });
    expect(plain(confirm.textContent)).toContain("Split 3 costs (SGD 612.40) evenly with Alex? Each share is SGD 306.20.");
    // The confirm is the only filled button; Not now splits nothing.
    expect(within(confirm).getByRole("button", { name: "Split evenly" }).className).toContain("btn-primary");
    await user.click(within(confirm).getByRole("button", { name: "Not now" }));
    expect(within(todo).queryByRole("group", { name: "Confirm splitting all" })).toBeNull();
    expect(calls).toHaveLength(0);

    await user.click(within(todo).getByRole("button", { name: "Split all evenly" }));
    await user.click(within(todo).getByRole("button", { name: "Split evenly" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: "/travel/trips/t1/split", body: { all: true } }]);
    expect(plain(within(todo).getByRole("status").textContent)).toContain("Split 3 costs evenly with Alex.");
  });

  it("names the first three costs and counts the rest", () => {
    show(detail({ trip: { companions: ["Alex"] }, to_split: [...costs, cost("d", "Taxi", "20")] }));
    expect(plain(card("To do").textContent)).toContain("SGD 632.40 · Wi-Fi, teamLab, Ryokan deposit and 1 more");
  });

  it("lists the costs on request, each to split or keep as just mine", async () => {
    const calls = mockApi({ "POST /travel/trips/t1/keep-mine": () => null, "POST /travel/trips/t1/split": () => ({ with_people: ["Alex"], done: [], skipped: [] }) });
    const user = userEvent.setup();
    show(detail({ trip: { companions: ["Alex"] }, to_split: costs }));
    const todo = card("To do");
    expect(within(todo).queryByRole("list", { name: "To split" })).toBeNull();
    const toggle = within(todo).getByRole("button", { name: "See costs" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await user.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const list = within(todo).getByRole("list", { name: "To split" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    await user.click(within(list).getByRole("button", { name: "Keep teamLab as just mine" }));
    await waitFor(() => expect(calls).toContainEqual({ method: "POST", path: "/travel/trips/t1/keep-mine", body: { transaction_ids: ["b"], keep: true } }));
    await user.click(within(list).getByRole("button", { name: "Split Wi-Fi evenly" }));
    await waitFor(() => expect(calls).toContainEqual({ method: "POST", path: "/travel/trips/t1/split", body: { transaction_ids: ["a"] } }));
  });

  it("is not offered when splitting evenly is off", () => {
    show(detail({ trip: { companions: ["Alex"], split_evenly: false }, to_split: [] }));
    expect(plain(card("To do").textContent)).not.toContain("to split");
  });

  const balances = () => [
    balance("Alex", sgd("768"), { owes_you: [part("iou", sgd("768"), "Dinner")] }),
    balance("Sam", sgd("-40"), { you_owe: [part("payment", sgd("40"), "Taxi")] }),
  ];

  it("has a row per person, with the items behind a Details toggle", async () => {
    const user = userEvent.setup();
    show(detail({ trip: { companions: ["Alex", "Sam"] }, balances: balances() }));
    const todo = card("To do");
    const rows = within(todo).getAllByRole("listitem");
    expect(plain(rows[0].textContent)).toContain("Alex owes you SGD 768.00");
    expect(plain(rows[1].textContent)).toContain("You owe Sam SGD 40.00");
    expect(rows[0].textContent).toContain("A");
    expect(within(todo).queryByText("All split and settled with Alex and Sam.")).toBeNull();
    const details = within(rows[0]).getByRole("button", { name: "Details" });
    expect(within(rows[0]).queryByRole("list", { name: "What Alex owes you" })).toBeNull();
    await user.click(details);
    expect(within(rows[0]).getByRole("list", { name: "What Alex owes you" }).textContent).toContain("Dinner");
  });

  it("asks in place before settling, with the payment logged by default", async () => {
    const calls = mockApi({
      "POST /travel/trips/t1/settle": () => ({ person: "Sam", ious_repaid: 0, payments_settled: 1, income: [], expenses: [sgd("40")] }),
    });
    const user = userEvent.setup();
    const onChange = show(detail({ trip: { companions: ["Alex", "Sam"] }, balances: balances() }));
    const todo = card("To do");
    await user.click(within(todo).getByRole("button", { name: "Settle up with Sam" }));
    const confirm = within(todo).getByRole("group", { name: "Settle up with Sam" });
    const log = within(confirm).getByRole("checkbox", { name: "Also record my share as spent" });
    expect((log as HTMLInputElement).checked).toBe(true);
    expect(plain(confirm.textContent)).toContain("This records that you paid Sam SGD 40.00 and counts it as spent. Nexus doesn't move any money.");
    expect(within(confirm).getByRole("button", { name: "Mark settled" }).className).toContain("btn-primary");

    // Unticked, it says it adds nothing to what was spent; Not now records nothing.
    await user.click(log);
    expect(plain(confirm.textContent)).toContain("without adding it to what you've spent");
    await user.click(within(confirm).getByRole("button", { name: "Not now" }));
    expect(calls).toHaveLength(0);

    await user.click(within(todo).getByRole("button", { name: "Settle up with Sam" }));
    await user.click(within(todo).getByRole("button", { name: "Mark settled" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: "/travel/trips/t1/settle", body: { person: "Sam", log: false } }]);
    expect(plain(within(todo).getByRole("status").textContent)).toContain("Settled with Sam: 1 payment you owed Sam marked paid, SGD 40.00 recorded as spent.");
  });

  it("has no spending choice when they only owe you", async () => {
    const user = userEvent.setup();
    show(detail({ trip: { companions: ["Alex"] }, balances: [balances()[0]] }));
    await user.click(within(card("To do")).getByRole("button", { name: "Settle up with Alex" }));
    expect(within(card("To do")).queryByRole("checkbox")).toBeNull();
  });
});

describe("Details", () => {
  const titles = ["Where it goes", "Planned costs", "Expenses", "Travellers"];
  const header = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });

  it("lists its sections closed, each with a short summary", () => {
    show(
      detail({
        trip: { planned: { Flights: sgd("900"), Tour: sgd("100") }, companions: ["Alex"] },
        spending: spending("18", { categories: [{ name: "Dining Out", planned: null, spent: sgd("18") }] }),
        items: [{ transaction_id: "k1", day: "2027-04-02", counterparty: "Ichiran", category: "Dining Out", amount: sgd("18"), home: sgd("18"), linked: false }],
      }),
    );
    for (const title of titles) expect(header(title).getAttribute("aria-expanded")).toBe("false");
    expect(plain(header("Where it goes").textContent)).toContain("1 category");
    expect(plain(header("Planned costs").textContent)).toContain("2 costs");
    expect(plain(header("Expenses").textContent)).toContain("1 so far");
    expect(plain(header("Travellers").textContent)).toContain("You and Alex");
    // Nothing paid by others, no booking with a cost and nothing set aside: those sections are not there.
    expect(screen.queryByRole("button", { name: /^Paid by others/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Bookings paid/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Setting money aside/ })).toBeNull();
    expect(header("Planned costs").getAttribute("aria-controls")).toBe("money-sec-planned-panel");
  });

  it("opens one section at a time", async () => {
    const user = userEvent.setup();
    show(detail());
    await user.click(header("Expenses"));
    expect(header("Expenses").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region", { name: "Expenses" })).toBeTruthy();
    await user.click(header("Travellers"));
    expect(header("Expenses").getAttribute("aria-expanded")).toBe("false");
    expect(header("Travellers").getAttribute("aria-expanded")).toBe("true");
    expect(screen.queryByRole("region", { name: "Expenses" })).toBeNull();
    expect(screen.getByRole("region", { name: "Travellers" })).toBeTruthy();
    // The open one closes again when its header is pressed.
    await user.click(header("Travellers"));
    expect(header("Travellers").getAttribute("aria-expanded")).toBe("false");
  });

  it("tags each expense by how it stands with the people going", async () => {
    const user = userEvent.setup();
    const item = (id: string, counterparty: string) => ({ transaction_id: id, day: "2027-04-02", counterparty, category: null, amount: sgd("10"), home: sgd("10"), linked: false });
    show(
      detail({
        trip: { companions: ["Alex"] },
        items: [item("a", "Wi-Fi"), item("b", "Taxi"), item("c", "Ramen")],
        to_split: [cost("a", "Wi-Fi", "10")],
        just_mine: ["b"],
      }),
    );
    await user.click(header("Expenses"));
    const rows = within(screen.getByRole("list", { name: "Trip expenses" })).getAllByRole("listitem");
    expect(plain(rows[0].textContent)).toContain("To split");
    expect(plain(rows[1].textContent)).toContain("Just mine");
    expect(plain(rows[2].textContent)).toContain("Split with Alex");
    expect(within(rows[0]).getByRole("button", { name: "Take Wi-Fi off the trip" })).toBeTruthy();
    expect(within(rows[1]).getByRole("button", { name: "Offer Taxi for splitting again" })).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Expenses" })).getByRole("button", { name: "Someone else paid" })).toBeTruthy();
  });

  it("puts the even-split switch with the travellers, once someone else is going", async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithProviders(<MoneyTab detail={detail()} onChange={() => undefined} adding={false} onAddDone={() => undefined} />);
    await user.click(header("Travellers"));
    expect(screen.queryByRole("switch", { name: "Split costs evenly" })).toBeNull();
    unmount();
    show(detail({ trip: { companions: ["Alex"] } }));
    await user.click(header("Travellers"));
    expect(screen.getByRole("switch", { name: "Split costs evenly" }).getAttribute("aria-checked")).toBe("true");
  });

  it("lists bookings that carry a cost, and the section is left out when none do", async () => {
    const user = userEvent.setup();
    const booking = (id: string, title: string, cost: Money | null): Booking =>
      ({ id, trip_id: "t1", kind: "hotel", title, starts: "2027-04-01", scheduled: true, logged: false, cost }) as Booking;
    show(detail({ bookings: [booking("b1", "Hotel Ume", sgd("820")), booking("b2", "Walk", null)], booked: sgd("820"), booked_unlogged: sgd("820") }));
    expect(plain(header("Bookings paid").textContent)).toContain("1 booking");
    await user.click(header("Bookings paid"));
    const list = screen.getByRole("list", { name: "Bookings paid" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(plain(list.textContent)).toContain("Hotel Ume");
    expect(plain(list.textContent)).toContain("SGD 820.00");
  });

  it("opens Planned costs with its form from the tab's +", () => {
    renderWithProviders(<MoneyTab detail={detail()} onChange={() => undefined} adding onAddDone={() => undefined} />);
    expect(header("Planned costs").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("form", { name: "Add a planned cost" })).toBeTruthy();
  });
});
