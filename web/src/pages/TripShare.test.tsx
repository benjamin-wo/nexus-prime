import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Trip, TripInvite, TripMember } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { ShareSheet } from "./TripShare";

const trip = (over: Partial<Trip> = {}) => ({ id: "t1", destination: "Tokyo", role: "owner", owner_name: "Ben", ...over }) as unknown as Trip;
const ben: TripMember = { id: "u1", name: "Ben", role: "owner", added_at: null, you: true };
const alex: TripMember = { id: "u2", name: "Alex T.", role: "member", added_at: "2026-09-20T03:00:00Z", you: false };
const issued = { id: "inv1", created_at: "2026-09-28T03:00:00Z", expires_at: "2026-10-05T03:00:00Z", token: "tok123", url: "https://nexus.test/trip-invite/tok123" };

describe("the share sheet for the owner", () => {
  it("lists the people with a You marker and roles, and the read-only link below", async () => {
    mockApi({
      "GET /travel/trips/t1/members": () => [ben, alex],
      "GET /travel/trips/t1/invites": () => [],
      "GET /travel/trips/t1/share": () => ({ token: null, show_bookings: true }),
    });
    renderWithProviders(<ShareSheet trip={trip()} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: "Share the plan" });
    const people = await within(dialog).findByRole("list", { name: "People on this trip" });
    const rows = within(people).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Ben");
    expect(rows[0]).toHaveTextContent("You · Owner");
    expect(rows[1]).toHaveTextContent("Alex T.");
    expect(rows[1]).toHaveTextContent("Member");
    expect(within(rows[0]).queryByRole("button", { name: /Remove/ })).toBeNull();
    expect(within(rows[1]).getByRole("button", { name: "Remove Alex T." })).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "Read-only link" })).toBeInTheDocument();
    expect(await within(dialog).findByRole("button", { name: "Create a link" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Leave trip" })).toBeNull();
  });

  it("makes a single-use invite link and shows it with Copy and how long it works", async () => {
    let open: TripInvite[] = [];
    const calls = mockApi({
      "GET /travel/trips/t1/members": () => [ben],
      "GET /travel/trips/t1/invites": () => open,
      "POST /travel/trips/t1/invites": () => {
        const { token: _token, url: _url, ...invite } = issued;
        open = [invite];
        return issued;
      },
      "GET /travel/trips/t1/share": () => ({ token: null, show_bookings: true }),
    });
    renderWithProviders(<ShareSheet trip={trip()} onClose={() => {}} />);
    const user = userEvent.setup();
    const dialog = screen.getByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: "Invite someone" }));
    expect(await within(dialog).findByLabelText("Invite link")).toHaveValue("https://nexus.test/trip-invite/tok123");
    expect(within(dialog).getByText("Works once, for 7 days.")).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button", { name: "Copy" })).toHaveLength(1);
    // It is also listed as an open link, with the dates it was made and expires.
    const list = await within(dialog).findByRole("list", { name: "Invite links not used yet" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(list).toHaveTextContent(/Made .* · expires /);
    expect(calls.filter((c) => c.method === "POST" && c.path === "/travel/trips/t1/invites")).toHaveLength(1);
  });

  it("cancels an open invite link and takes it off the list", async () => {
    let open: TripInvite[] = [{ id: "inv9", created_at: "2026-09-27T03:00:00Z", expires_at: "2026-10-04T03:00:00Z" }];
    const calls = mockApi({
      "GET /travel/trips/t1/members": () => [ben],
      "GET /travel/trips/t1/invites": () => open,
      "DELETE /travel/trips/t1/invites/inv9": () => {
        open = [];
        return undefined;
      },
      "GET /travel/trips/t1/share": () => ({ token: null, show_bookings: true }),
    });
    renderWithProviders(<ShareSheet trip={trip()} onClose={() => {}} />);
    const user = userEvent.setup();
    const list = await screen.findByRole("list", { name: "Invite links not used yet" });
    await user.click(within(list).getByRole("button", { name: /^Cancel the invite/ }));
    await waitFor(() => expect(screen.queryByRole("list", { name: "Invite links not used yet" })).toBeNull());
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/travel/trips/t1/invites/inv9")).toBe(true);
  });

  it("asks before removing someone, and only removes them when told to", async () => {
    let people = [ben, alex];
    const calls = mockApi({
      "GET /travel/trips/t1/members": () => people,
      "GET /travel/trips/t1/invites": () => [],
      "DELETE /travel/trips/t1/members/u2": () => {
        people = [ben];
        return undefined;
      },
      "GET /travel/trips/t1/share": () => ({ token: null, show_bookings: true }),
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderWithProviders(<ShareSheet trip={trip()} onClose={() => {}} />);
    const user = userEvent.setup();
    const remove = await screen.findByRole("button", { name: "Remove Alex T." });
    await user.click(remove);
    expect(confirm).toHaveBeenLastCalledWith("Remove Alex T. from this trip? They'll lose access straight away.");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Remove Alex T." }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove Alex T." })).toBeNull());
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });
});

describe("the share sheet for a member", () => {
  const mine: TripMember = { id: "u3", name: "Sam R.", role: "member", added_at: "2026-09-21T03:00:00Z", you: true };
  const lead: TripMember = { id: "u1", name: "Alex T.", role: "owner", added_at: null, you: false };
  const member = () => trip({ role: "member", owner_name: "Alex T." });

  it("shows the people and a way to leave, with no invites, removing or read-only link", async () => {
    const calls = mockApi({ "GET /travel/trips/t1/members": () => [lead, mine] });
    renderWithProviders(<ShareSheet trip={member()} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: "People on this trip" });
    const people = await within(dialog).findByRole("list", { name: "People on this trip" });
    const rows = within(people).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Alex T.");
    expect(rows[0]).toHaveTextContent("Owner");
    expect(rows[1]).toHaveTextContent("You · Member");
    expect(within(dialog).getByRole("button", { name: "Leave trip" })).toBeInTheDocument();
    for (const name of [/Invite someone/, /Remove/, /Create a link/]) expect(within(dialog).queryByRole("button", { name })).toBeNull();
    expect(within(dialog).queryByRole("heading", { name: "Read-only link" })).toBeNull();
    // None of the owner's endpoints is asked: invites and the share link are refused to a member.
    expect(calls.map((c) => c.path).filter((p) => /\/(invites|share)$/.test(p))).toEqual([]);
  });

  it("leaves after a confirmation, then goes back to the trips", async () => {
    let left = 0;
    const calls = mockApi({
      "GET /travel/trips/t1/members": () => [lead, mine],
      "DELETE /travel/trips/t1/members/u3": () => undefined,
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderWithProviders(<ShareSheet trip={member()} onClose={() => {}} onLeft={() => (left += 1)} />);
    const user = userEvent.setup();
    const leave = await screen.findByRole("button", { name: "Leave trip" });
    await user.click(leave);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Leave trip" }));
    await waitFor(() => expect(left).toBe(1));
    expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/travel/trips/t1/members/u3"]);
  });
});
