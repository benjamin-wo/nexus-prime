import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Trip, TripDetail, TripMember } from "../api";
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

function renderIdeas() {
  mockApi({
    "GET /me": () => ({ user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" }),
    "GET /travel/trips/t1": () => detail,
    "GET /travel/trips/t1/members": () => [] as TripMember[],
    "GET /travel/trips/t1/activity": () => [],
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/travel/trips/t1?tab=ideas"]}>
        <Routes>
          <Route path="/travel/trips/:id" element={<TripPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Ideas with a map", () => {
  it("shows the list and the map side by side on a wide screen, with no List/Map switch", async () => {
    screenIs(true);
    renderIdeas();
    expect(await screen.findByRole("region", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ideas" })).toBeInTheDocument();
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
