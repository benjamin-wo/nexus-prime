import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, type Mock, vi } from "vitest";

import type { Booking, Place, Trip, TripDetail, TripMember } from "../api";
import { mockApi } from "../testing";
import { TripPage } from "./Trips";

// No Google script in a test: the map just never gets to draw.
vi.mock("../maps", () => ({ onMapsAuthFailure: () => () => undefined, loadMaps: () => new Promise(() => undefined) }));

const trip = {
  id: "t1", destination: "Tokyo", start: "2027-04-02", end: "2027-04-05", days: 4, currency: "JPY", budget: null, companions: [], set_aside: null,
  planned: {}, status: "upcoming", days_until: 120, day_number: null, notes: null, day_labels: {}, stops: [], split_evenly: true,
  role: "owner", owner_name: "Ben", packing: [],
} as unknown as Trip;
const detail = {
  trip, bookings: [], days: [], places_order: [], places: true, ideas: false, suggested_stops: [], routes: true, map_key: "k",
  booked: null, booked_unlogged: null, to_spend: null,
  ready: { nights_without_stay: [], has_transport: true, has_budget: false, done: 2, total: 3 },
  spending: null, saving: null, owed: [], to_split: [], just_mine: [], paid_by_others: [], balances: [], items: [],
} as unknown as TripDetail;

/** A screen that is (or isn't) wide enough for the list and the map side by side. */
function screenIs(wide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: wide && query.includes("min-width: 1024px"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

function renderIdeas(over: Partial<TripDetail> = {}, handlers: Record<string, (body: unknown) => unknown> = {}) {
  const calls = mockApi({
    "GET /me": () => ({ user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" }),
    "GET /travel/trips/t1": () => ({ ...detail, ...over }),
    "GET /travel/trips/t1/members": () => [] as TripMember[],
    "GET /travel/trips/t1/activity": () => [],
    "GET /travel/trips/t1/places": () => [],
    ...handlers,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/travel/trips/t1?tab=ideas"]}>
        <Routes>
          <Route path="/travel/trips/:id" element={<TripPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Ideas with a map", () => {
  it("shows the list and the map side by side on a wide screen, with no List/Map switch", async () => {
    screenIs(true);
    renderIdeas();
    expect(await screen.findByRole("region", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "0 ideas" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Show ideas as" })).toBeNull();
    expect(document.querySelector(".ideas-layout")).toHaveAttribute("data-view", "list");
  });

  it("keeps the switch on a phone, with the map only when asked for", async () => {
    screenIs(false);
    renderIdeas();
    const switcher = await screen.findByRole("group", { name: "Show ideas as" });
    expect(screen.queryByRole("region", { name: "Map" })).toBeNull();
    await userEvent.setup().click(within(switcher).getByRole("button", { name: "Map" }));
    expect(await screen.findByRole("region", { name: "Map" })).toBeInTheDocument();
  });
});

/** A made-up idea: a place to visit with no day yet. */
const idea = (id: string, title: string, extra: Partial<Booking> = {}): Booking =>
  ({
    id, trip_id: "t1", kind: "activity", title, name: title, provider: null, starts: "2027-04-02", ends: null, segments: [], hotel: null, address: null,
    check_in: null, check_out: null, reference: null, booked_via: null, category: null, place_id: null, note: null, scheduled: false, cost: null,
    logged: false, manual: true, at: null, day: null, ...extra,
  }) as Booking;

const withIdeas = {
  map_key: null,
  bookings: [
    idea("b1", "Fish market", { address: "Tsukiji 4-16", list_name: "Eat", note: "Go early", cost: { amount: "1500", currency: "JPY" } }),
    idea("b2", "Old temple", { category: "Temple" }),
  ],
} as unknown as Partial<TripDetail>;

describe("the ideas list", () => {
  it("counts the ideas, one quiet row each with one grey line and an icon button to put it on a day", async () => {
    screenIs(false);
    renderIdeas(withIdeas);
    expect(await screen.findByRole("heading", { name: "2 ideas" })).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Ideas" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const fish = rows[0];
    expect(within(fish).getByRole("button", { name: /^Fish market/ })).toHaveTextContent("Fish marketTsukiji 4-16 · Eat");
    expect(within(fish).getByRole("button", { name: "Put Fish market on a day" })).toBeInTheDocument();
    expect(within(fish).getByRole("button", { name: "Put Fish market on a day" })).toHaveTextContent("");
    // The kind stands in for a missing address.
    expect(rows[1]).toHaveTextContent("Old templeTemple");
    // Closed: nothing of what is inside.
    expect(within(fish).queryByRole("button", { name: "Change Fish market" })).toBeNull();
  });

  it("opens a row to show its note, Google Maps, Change and Remove, and takes it off the trip", async () => {
    screenIs(false);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const calls = renderIdeas(withIdeas, { "DELETE /travel/bookings/b1": () => ({}) });
    const user = userEvent.setup();
    const fish = (await screen.findAllByRole("listitem"))[0];
    const name = within(fish).getByRole("button", { name: /^Fish market/ });
    expect(name).toHaveAttribute("aria-expanded", "false");
    await user.click(name);
    expect(name).toHaveAttribute("aria-expanded", "true");
    expect(within(fish).getByText("Go early")).toBeInTheDocument();
    expect(within(fish).getByRole("link", { name: /Open in Google Maps/ })).toHaveAttribute("href", expect.stringContaining("google.com/maps/search"));
    expect(within(fish).getByRole("button", { name: "Change Fish market" })).toBeInTheDocument();
    await user.click(within(fish).getByRole("button", { name: "Remove Fish market" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/travel/bookings/b1")).toBe(true));
    // Change opens the editor in place of the row.
    await user.click(within(fish).getByRole("button", { name: "Change Fish market" }));
    expect(await screen.findByRole("form", { name: "Change the entry" })).toBeInTheDocument();
  });

  it("shows the drag grips only while arranging", async () => {
    screenIs(false);
    renderIdeas(withIdeas);
    const user = userEvent.setup();
    const arrange = await screen.findByRole("button", { name: "Arrange" });
    expect(arrange).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: "Drag Fish market" })).toBeNull();
    expect(screen.queryByText(/Drag an idea by its grip/)).toBeNull();
    await user.click(arrange);
    expect(screen.getByRole("button", { name: "Done" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Drag Fish market" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Drag Old temple" })).toBeInTheDocument();
    expect(screen.getByText(/Drag an idea by its grip/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("button", { name: "Drag Fish market" })).toBeNull();
  });

  it("has Find ideas as a soft button (the trip's + stays the one primary), with the List/Map switch beside it on a phone", async () => {
    screenIs(false);
    renderIdeas({ ...withIdeas, map_key: "k" });
    const switcher = await screen.findByRole("group", { name: "Show ideas as" });
    expect(within(switcher).getAllByRole("button").map((b) => b.textContent)).toEqual(["List", "Map"]);
    expect(within(switcher).getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Find ideas" })).toHaveClass("btn-soft");
    expect(screen.getByRole("button", { name: "Find ideas" })).not.toHaveClass("btn-primary");
    expect(screen.queryByRole("button", { name: "Find places or ideas" })).toBeNull();
  });
});

const place = (id: string, name: string, extra: Partial<Place> = {}): Place =>
  ({ id, name, address: `${name} street`, kind: "Noodle shop", rating: "4.6", ratings: 120, price: null, area: "Gion", ...extra }) as Place;

const japan = {
  ...withIdeas,
  trip: { ...trip, destination: "Japan", end: "2027-04-08", days: 7, stops: [{ name: "Tokyo", start: "2027-04-02", end: "2027-04-04" }, { name: "Kyoto", start: "2027-04-05", end: "2027-04-08" }] },
} as unknown as Partial<TripDetail>;
const searches = () => (globalThis.fetch as Mock).mock.calls.map((c) => String(c[0])).filter((u) => u.includes("/travel/places/search"));

describe("the finder sheet", () => {
  async function openFinder(over: Partial<TripDetail> = japan, handlers: Record<string, (body: unknown) => unknown> = {}) {
    screenIs(false);
    const calls = renderIdeas(over, { "GET /travel/places/search": () => [place("g1", "Hanok Noodle Bar"), place("g2", "Ramen Alley", { photo_url: "/photo/g2", photo_author: "A. Photographer" })], ...handlers });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Find ideas" }));
    return { user, calls, sheet: await screen.findByRole("dialog", { name: "Find ideas" }) };
  }

  it("opens with the search, one scope chip, the themes in one group and a line saying where it looks", async () => {
    const { sheet } = await openFinder();
    expect(within(sheet).getByRole("search", { name: "Search Google Maps" })).toBeInTheDocument();
    expect(within(sheet).getByLabelText("Look for")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: /^Look in: / })).toHaveAttribute("aria-haspopup", "menu");
    expect(within(sheet).getByRole("group", { name: "Themes" })).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(within(sheet).getByText(/^(Across Tokyo and Kyoto|In (Tokyo|Kyoto))\./)).toBeInTheDocument();
  });

  it("lists the scopes in a menu, and asks the same question again where it is picked", async () => {
    const { user, sheet } = await openFinder();
    await user.type(within(sheet).getByLabelText("Look for"), "ramen");
    await user.click(within(sheet).getByRole("button", { name: /^Search$/ }));
    await within(sheet).findByRole("list", { name: "Google Maps results" });
    expect(searches()).toHaveLength(1);

    await user.click(within(sheet).getByRole("button", { name: /^Look in: / }));
    const menu = within(sheet).getByRole("menu", { name: "Look in" });
    const items = within(menu).getAllByRole("menuitemradio");
    expect(items.map((i) => i.textContent)).toEqual(expect.arrayContaining(["Whole trip", "In Tokyo", "In Kyoto"]));
    expect(items.filter((i) => i.getAttribute("aria-checked") === "true")).toHaveLength(1);

    await user.click(within(menu).getByRole("menuitemradio", { name: "In Kyoto" }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(within(sheet).getByRole("button", { name: "Look in: In Kyoto" })).toBeInTheDocument();
    expect(within(sheet).getByText("In Kyoto.")).toBeInTheDocument();
    await waitFor(() => expect(searches()).toHaveLength(2));
    expect(searches()[1]).toContain("stop=Kyoto");
  });

  it("closes the menu with Escape without closing the sheet", async () => {
    const { user, sheet } = await openFinder();
    await user.click(within(sheet).getByRole("button", { name: /^Look in: / }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Find ideas" })).toBeInTheDocument();
  });

  it("keeps the sheet open after a save, so several can be saved, and marks each saved", async () => {
    const { user, sheet, calls } = await openFinder(japan, { "POST /travel/trips/t1/bookings": () => ({}) });
    await user.type(within(sheet).getByLabelText("Look for"), "noodles");
    await user.click(within(sheet).getByRole("button", { name: /^Search$/ }));
    const results = await within(sheet).findByRole("list", { name: "Google Maps results" });
    const [first, second] = within(results).getAllByRole("listitem");
    expect(first.querySelector(".find-meta")).toHaveTextContent("Rated 4.6 (120) · Gion · Google Maps");
    // The place's photo when it has one, else an icon tile.
    expect(first.querySelector(".find-tile")).not.toBeNull();
    expect(second.querySelector(".find-photo img")).toHaveAttribute("src", "/photo/g2");

    await user.click(within(results).getByRole("button", { name: "Save: Hanok Noodle Bar" }));
    const saved = await within(results).findByRole("button", { name: "Hanok Noodle Bar is saved" });
    expect(saved).toBeDisabled();
    expect(saved).toHaveTextContent("Saved");
    expect(screen.getByRole("dialog", { name: "Find ideas" })).toBeInTheDocument();
    expect(within(sheet).getByRole("status")).toHaveTextContent("Saved Hanok Noodle Bar to Ideas.");
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ name: "Hanok Noodle Bar", day: null });

    // The next one is still there to save.
    await user.click(within(results).getByRole("button", { name: "Save: Ramen Alley" }));
    expect(await within(results).findByRole("button", { name: "Ramen Alley is saved" })).toBeDisabled();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(2);
  });

  it("shows a guide's idea with its words and a link to the page, and says where it looks", async () => {
    const guide = { name: "Lantern Alley", area: null, kind: "Nightlife", why: "Hand-pulled noodles worth the queue.", source: { url: "https://food.example.com/noodles", title: "Seoul's best noodles" }, place: null };
    const { user, sheet } = await openFinder({ ...japan, ideas: true }, { "GET /travel/trips/t1/ideas": () => ({ query: "best noodles", destination: "Japan", ideas: [guide] }) });
    expect(within(sheet).getByText(/Google and guides together\.$/)).toBeInTheDocument();
    await user.type(within(sheet).getByLabelText("Look for"), "best noodles");
    await user.click(within(sheet).getByRole("button", { name: /^Search$/ }));
    const card = (await within(sheet).findAllByRole("listitem")).find((li) => li.textContent?.includes("Lantern Alley"))!;
    expect(card.querySelector(".find-meta")).toHaveTextContent("“Hand-pulled noodles worth the queue.” · From a guide");
    expect(within(card).getByRole("link", { name: /Seoul's best noodles/ })).toHaveAttribute("href", "https://food.example.com/noodles");
  });

  it("closes with the sheet's Close button", async () => {
    const { user } = await openFinder();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
