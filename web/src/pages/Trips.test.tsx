import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Booking, Trip, TripActivity, TripDetail, TripMember } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { EntryEditor } from "./TripEntry";
import { nextUp, stillToSort } from "./TripStage";
import { TripPage, TripsPage } from "./Trips";

const me = (role: "owner" | "member" | "guest") => ({ user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" });

// Made-up trips with only the fields the cards and the page read.
const trip = (over: Partial<Trip> = {}): Trip =>
  ({
    id: "t1", destination: "Tokyo", start: "2027-04-02", end: "2027-04-05", days: 4, currency: "JPY", budget: null, companions: [], set_aside: null,
    planned: {}, status: "upcoming", days_until: 120, day_number: null, notes: null, day_labels: {}, stops: [], split_evenly: true,
    role: "owner", owner_name: "Ben", packing: [], ...over,
  }) as Trip;
const mine = trip({ id: "t1", destination: "Tokyo", budget: { amount: "3000.0000", currency: "SGD" } });
const shared = trip({ id: "t2", destination: "Lisbon", role: "member", owner_name: "Alex T.", start: "2027-05-02", end: "2027-05-05" });

describe("the trips list", () => {
  it("puts trips shared with you in their own section, saying whose they are", async () => {
    mockApi({
      "GET /me": () => me("owner"),
      "GET /travel/trips": () => [mine, shared],
      "GET /travel/bookings": () => [],
      "GET /runs": () => [],
    });
    renderWithProviders(<TripsPage />);
    const own = await screen.findByRole("region", { name: "Coming up" });
    expect(within(own).getByRole("link", { name: "Tokyo" })).toBeInTheDocument();
    expect(within(own).queryByText("Lisbon")).toBeNull();
    const section = screen.getByRole("region", { name: "Shared with you" });
    expect(within(section).getByRole("link", { name: "Lisbon" })).toBeInTheDocument();
    expect(within(section).getByText("Shared by Alex T.")).toBeInTheDocument();
    expect(within(section).queryByText("Tokyo")).toBeNull();
    expect(screen.getByRole("button", { name: "New trip" })).toBeInTheDocument();
  });

  it("has no Shared with you section when nothing is shared", async () => {
    mockApi({ "GET /me": () => me("owner"), "GET /travel/trips": () => [mine], "GET /travel/bookings": () => [], "GET /runs": () => [] });
    renderWithProviders(<TripsPage />);
    await screen.findByRole("link", { name: "Tokyo" });
    expect(screen.queryByRole("region", { name: "Shared with you" })).toBeNull();
  });

  it("gives a guest only the trips they are on, and never asks for what a guest can't have", async () => {
    const calls = mockApi({
      "GET /me": () => me("guest"),
      "GET /travel/trips": () => [shared],
      "GET /travel/bookings": () => [],
      "GET /runs": () => [],
      "GET /travel/next": () => null,
    });
    renderWithProviders(<TripsPage onAsk={() => {}} />);
    const section = await screen.findByRole("region", { name: "Shared with you" });
    expect(within(section).getByRole("link", { name: "Lisbon" })).toBeInTheDocument();
    for (const name of ["New trip", "Add a trip", "Research it"]) expect(screen.queryByRole("button", { name })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Where to next?" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Bookings not on a trip" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Research" })).toBeNull();
    // Give the page time to ask for anything else it would.
    await new Promise((resolve) => setTimeout(resolve, 30));
    const asked = calls.map((c) => c.path);
    expect(asked).toContain("/travel/trips");
    expect(asked.filter((p) => ["/travel/bookings", "/runs", "/travel/next"].includes(p) || p.startsWith("/travel/research"))).toEqual([]);
  });
});

// A trip as a member gets it: the plan, no budget, spending or costs.
const planOnly = (t: Trip, over: Partial<TripDetail> = {}): TripDetail =>
  ({
    trip: t, bookings: [], days: [], places_order: [], places: false, ideas: false, suggested_stops: [], routes: false, map_key: null,
    booked: null, booked_unlogged: null, to_spend: null,
    ready: { nights_without_stay: [], has_transport: true, has_budget: false, done: 2, total: 3 },
    spending: null, saving: null, owed: [], to_split: [], just_mine: [], paid_by_others: [], balances: [], items: [], ...over,
  }) as unknown as TripDetail;

const owner: TripMember = { id: "u1", name: "Alex T.", role: "owner", added_at: null, you: false };
const sam: TripMember = { id: "u3", name: "Sam R.", role: "member", added_at: "2026-09-21T03:00:00Z", you: true };

function renderTrip(path: string, onAsk?: (text: string) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/travel/trips/:id" element={<TripPage onAsk={onAsk} />} />
          <Route path="/travel" element={<p>Trips list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("a trip you were added to", () => {
  const handlers = (over: Record<string, () => unknown> = {}) => ({
    "GET /me": () => me("member"),
    "GET /travel/trips/t2": () => planOnly(shared),
    "GET /travel/trips/t2/members": () => [owner, sam],
    "GET /travel/trips/t2/activity": () => [] as TripActivity[],
    ...over,
  });

  it("has no Money tab, opens Plan for a Money address, and says whose trip it is", async () => {
    mockApi(handlers());
    renderTrip("/travel/trips/t2?tab=money");
    const tabs = await screen.findByRole("navigation", { name: "Trip sections" });
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["Plan", "Ideas", "Prep"]);
    await waitFor(() => expect(within(tabs).getByRole("button", { name: "Plan" })).toHaveAttribute("aria-current", "page"));
    expect(screen.getByText("Shared by Alex T.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Spending|Budget/ })).toBeNull();
  });

  it("has no owner actions in the header: Share becomes People, and there is no menu", async () => {
    mockApi(handlers());
    renderTrip("/travel/trips/t2");
    await screen.findByRole("navigation", { name: "Trip sections" });
    expect(screen.getByRole("button", { name: "People on this trip" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Share the plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Trip options" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Delete trip" })).toBeNull();
  });

  it("lets a member ask Nexus about the plan, with no budget in the question", async () => {
    mockApi(handlers());
    const asked: string[] = [];
    renderTrip("/travel/trips/t2", (text) => asked.push(text));
    await userEvent.setup().click(await screen.findByRole("button", { name: /Ask Nexus about this trip/ }));
    expect(asked).toEqual(["How's the Lisbon trip shared with me looking? What's booked and what's missing?"]);
  });

  it("shows the people on the trip as the faces, owner first", async () => {
    mockApi(handlers());
    renderTrip("/travel/trips/t2");
    expect(await screen.findByLabelText("With Alex T., Sam R.")).toBeInTheDocument();
  });

  it("never offers to set a budget", () => {
    const detail = planOnly(shared);
    expect(stillToSort(detail)).toEqual([]);
    expect(nextUp(detail, () => 0)?.text ?? "").not.toMatch(/budget/i);
    // The owner of the same trip, with no budget, is still told.
    expect(stillToSort({ ...detail, trip: mine, ready: { ...detail.ready, has_budget: false } }).map((i) => i.text)).toEqual(["No budget yet"]);
  });

  it("has no cost or currency field on an entry", async () => {
    mockApi({});
    const user = userEvent.setup();
    const { unmount } = render(<EntryEditor trip={shared} home="SGD" preset={{ kind: "activity" }} onDone={() => {}} />);
    await user.click(screen.getByText("More details"));
    expect(screen.getByLabelText("Booking reference")).toBeInTheDocument();
    expect(screen.queryByLabelText("Cost")).toBeNull();
    expect(screen.queryByLabelText("Currency")).toBeNull();
    unmount();
    render(<EntryEditor trip={mine} home="SGD" preset={{ kind: "activity" }} onDone={() => {}} />);
    await user.click(screen.getByText("More details"));
    expect(screen.getByLabelText("Cost")).toBeInTheDocument();
  });

  it("sends no cost when a member saves an entry", async () => {
    const calls = mockApi({ "POST /travel/trips/t2/bookings": () => ({}) });
    const user = userEvent.setup();
    const flight = { id: "b1", kind: "activity", title: "Dinner", cost: null } as unknown as Booking;
    render(<EntryEditor trip={shared} home="SGD" entry={{ ...flight, name: "Dinner", scheduled: true, day: "2027-05-03", segments: [] } as unknown as Booking} onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ cost: null, currency: null });
  });

  it("says you're no longer on the trip when it has gone, with a way back", async () => {
    // The mock answers 404 for anything it has no handler for, as the server does for a trip you aren't on.
    const calls = mockApi({ "GET /me": () => me("member") });
    renderTrip("/travel/trips/t2");
    expect(await screen.findByText("You're no longer on this trip.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to your trips" })).toHaveAttribute("href", "/travel");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(calls.some((c) => c.path === "/travel/trips/t2")).toBe(true);
  });
});

describe("the activity line on a trip", () => {
  const recent: TripActivity[] = [{ actor: "Alex T.", summary: "added Dinner at Sushi Ten", at: new Date(Date.now() - 5 * 60_000 - 5_000).toISOString() }];

  it("shows under Next up on the Plan tab of a shared trip", async () => {
    mockApi({
      "GET /me": () => me("member"),
      "GET /travel/trips/t2": () => planOnly(shared),
      "GET /travel/trips/t2/members": () => [owner, sam],
      "GET /travel/trips/t2/activity": () => recent,
    });
    renderTrip("/travel/trips/t2");
    expect(await screen.findByRole("button", { name: /Alex T\. added Dinner at Sushi Ten/ })).toHaveTextContent("Alex T. added Dinner at Sushi Ten · 5 min ago");
  });

  it("is not there on a trip nobody else is on, and doesn't ask for it", async () => {
    const calls = mockApi({
      "GET /me": () => me("owner"),
      "GET /travel/trips/t1": () => planOnly(mine),
      "GET /travel/trips/t1/members": () => [{ ...owner, you: true }],
      "GET /travel/trips/t1/activity": () => recent,
    });
    renderTrip("/travel/trips/t1");
    await screen.findByRole("navigation", { name: "Trip sections" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByRole("button", { name: /added Dinner/ })).toBeNull();
    expect(calls.some((c) => c.path.endsWith("/activity"))).toBe(false);
  });
});
