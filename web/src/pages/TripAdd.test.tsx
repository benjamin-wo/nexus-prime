import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Trip } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { AddSheet } from "./TripAdd";

const trip = { id: "t1", destination: "Tokyo", start: "2026-11-10", end: "2026-11-13", currency: "JPY" } as unknown as Trip;
const sheet = (over: Partial<Parameters<typeof AddSheet>[0]> = {}) => (
  <AddSheet trip={trip} preset={null} places onScreenshot={() => {}} onChanged={() => {}} onClose={() => {}} {...over} />
);

describe("the add sheet", () => {
  it("offers a booking, a plan or an idea, and the quick ways below", () => {
    mockApi({});
    renderWithProviders(sheet());
    expect(screen.getByRole("dialog", { name: "Add to Tokyo" })).toBeInTheDocument();
    for (const name of [/A booking/, /A plan/, /An idea/, "Type it", "Find a place"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.getByLabelText("Screenshot or photo")).toBeInTheDocument();
    expect(screen.queryByText(/Fill in a form/)).toBeNull();
  });

  const me = (role: "owner" | "member" | "guest") => ({ user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" });

  it("offers Type it to a member of someone's trip, and says which trip it is", async () => {
    Element.prototype.scrollIntoView = () => {}; // jsdom has none
    const calls = mockApi({ "GET /me": () => me("member"), "POST /chat": () => [{ text: "Added.", buttons: [] }] });
    renderWithProviders(sheet({ trip: { ...trip, role: "member" } as unknown as Trip }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Type it" }));
    await user.type(screen.getByLabelText("Tell Nexus about a booking"), "Dinner at Sushi Ten on Saturday at 7pm");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Added.");
    expect(calls.find((c) => c.path === "/chat")?.body).toEqual({
      message: "For the Tokyo trip shared with me (Nov 10 to Nov 13), add this: Dinner at Sushi Ten on Saturday at 7pm",
    });
  });

  it("keeps Type it from a guest, who has no chat", async () => {
    mockApi({ "GET /me": () => me("guest") });
    renderWithProviders(sheet({ trip: { ...trip, role: "member" } as unknown as Trip }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Type it" })).toBeNull());
    expect(screen.getByRole("button", { name: "Find a place" })).toBeInTheDocument();
  });

  it("saves a plan on the day open, then refreshes and closes", async () => {
    const calls = mockApi({ "POST /travel/trips/t1/bookings": () => ({}) });
    let changed = 0;
    let closed = 0;
    renderWithProviders(sheet({ viewing: "2026-11-12", onChanged: () => (changed += 1), onClose: () => (closed += 1) }));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /A plan/ }));
    expect(screen.getByLabelText("Day")).toHaveValue("2026-11-12");
    await user.type(screen.getByLabelText("Name"), "Dinner at Sushi Ten");
    await user.type(screen.getByLabelText("Time"), "19:00");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(closed).toBe(1));
    expect(changed).toBe(1);
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ kind: "activity", name: "Dinner at Sushi Ten", day: "2026-11-12", at: "19:00" });
  });

  it("saves a ticket as a plan with where it was booked", async () => {
    const calls = mockApi({ "POST /travel/trips/t1/bookings": () => ({}) });
    renderWithProviders(sheet());
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /A booking/ }));
    expect(screen.getByRole("button", { name: "Flight" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Ticket" }));
    expect(screen.getByRole("button", { name: "Ticket" })).toHaveAttribute("aria-pressed", "true");
    await user.type(screen.getByLabelText("Name"), "Lantern Museum");
    await user.click(screen.getByText("More details"));
    await user.type(screen.getByLabelText("Booking reference"), "LM-204");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ kind: "activity", name: "Lantern Museum", day: "2026-11-10", reference: "LM-204" });
  });

  it("files an idea under an existing list and shows the API's error", async () => {
    const calls = mockApi({});
    renderWithProviders(sheet({ preset: { kind: "place" }, lists: ["Eat", "Must see"] }));
    const user = userEvent.setup();
    expect(screen.getByRole("dialog", { name: "Add an idea" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Name"), "Fish market");
    await user.click(screen.getByRole("button", { name: "Eat" }));
    expect(screen.getByRole("button", { name: "Eat" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not mocked");
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ kind: "activity", name: "Fish market", day: null, list_name: "Eat" });
  });
});
