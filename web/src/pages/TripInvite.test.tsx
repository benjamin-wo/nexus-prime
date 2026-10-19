import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "../api";
import { TripInvite } from "./TripInvite";

const member: Me = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
const guest: Me = { user: { telegram_user_id: 3, role: "guest", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };

/** Answer fetches by "METHOD /path" with a status and a body; anything else is a 404. */
function answer(routes: Record<string, [number, unknown]>): string[] {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init?.method ?? "GET"} ${url.pathname.replace(/^\/api/, "")}`;
    calls.push(key);
    const [status, body] = routes[key] ?? [404, { detail: "not mocked" }];
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

/** Stands in for the trip page: shows which trip opened and the notice sent along. */
function Trip() {
  const { id } = useParams();
  const notice = (useLocation().state as { notice?: string | null } | null)?.notice;
  return <p>Trip {id} opened{notice ? `: ${notice}` : " with no notice"}</p>;
}

function open(me: Me) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/trip-invite/tok123"]}>
        <Routes>
          <Route path="/trip-invite/:token" element={<TripInvite me={me} />} />
          <Route path="/travel/trips/:id" element={<Trip />} />
          <Route path="/travel" element={<p>On the Trips page</p>} />
          <Route path="*" element={<p>On Home</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const trips = [{ id: "t9", destination: "Kyoto" }];

describe("a trip invite for someone signed in", () => {
  it("joins the trip once and opens it with a notice naming it", async () => {
    const calls = answer({
      "POST /travel/invites/tok123/accept": [200, { trip_id: "t9", new: true }],
      "GET /travel/trips": [200, trips],
    });
    open(member);
    expect(screen.getByText("Joining the trip…")).toBeInTheDocument();
    expect(await screen.findByText("Trip t9 opened: You've joined the trip to Kyoto.")).toBeInTheDocument();
    expect(calls.filter((c) => c.startsWith("POST"))).toEqual(["POST /travel/invites/tok123/accept"]);
  });

  it("still opens the trip when its name can't be found", async () => {
    answer({ "POST /travel/invites/tok123/accept": [200, { trip_id: "t9", new: true }] });
    open(member);
    expect(await screen.findByText("Trip t9 opened: You've joined the trip.")).toBeInTheDocument();
  });

  it("just opens a trip they are already on, with nothing said", async () => {
    answer({ "POST /travel/invites/tok123/accept": [200, { trip_id: "t9", new: false }] });
    open(member);
    expect(await screen.findByText("Trip t9 opened with no notice")).toBeInTheDocument();
  });

  it("tells the owner it is their own link", async () => {
    answer({ "POST /travel/invites/tok123/accept": [409, { detail: "that's your own trip" }] });
    open(member);
    expect(await screen.findByRole("heading", { name: "That's your own invite link" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Trips" })).toHaveAttribute("href", "/travel");
  });

  it("explains a link that is used, expired or unknown, and points to Home", async () => {
    answer({ "POST /travel/invites/tok123/accept": [404, { detail: "that invite link doesn't work" }] });
    open(member);
    expect(await screen.findByRole("heading", { name: "This invite doesn't work any more" })).toBeInTheDocument();
    expect(screen.getByText("Ask the trip's owner for a new link.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Home" })).toHaveAttribute("href", "/");
  });

  it("points a guest with a bad link to Trips, the only place they have", async () => {
    answer({ "POST /travel/invites/tok123/accept": [404, { detail: "that invite link doesn't work" }] });
    open(guest);
    expect(await screen.findByRole("heading", { name: "This invite doesn't work any more" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Trips" })).toHaveAttribute("href", "/travel");
  });

  it("says plainly when joining failed for another reason, and can try again", async () => {
    const calls = answer({ "POST /travel/invites/tok123/accept": [429, { detail: "too many tries, wait a little" }] });
    open(member);
    expect(await screen.findByText("too many tries, wait a little")).toBeInTheDocument();
    screen.getByRole("button", { name: "Try again" }).click();
    await waitFor(() => expect(calls.filter((c) => c.startsWith("POST"))).toHaveLength(2));
  });
});
