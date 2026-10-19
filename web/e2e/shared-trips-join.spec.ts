import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

/** A trip someone else owns, as a member or guest is shown it. */
const kyoto = {
  id: "trip5",
  destination: "Kyoto",
  start: "2026-12-01",
  end: "2026-12-05",
  days: 5,
  currency: "JPY",
  budget: null,
  companions: [],
  set_aside: null,
  planned: {},
  status: "upcoming",
  days_until: 64,
  day_number: null,
  notes: null,
  day_labels: {},
  stops: [],
  split_evenly: true,
  role: "member",
  owner_name: "Alex T.",
};

test("someone signed in who opens a trip invite lands on the trip", async ({ page }) => {
  const state = await fakeApi(page);
  state.trips = [kyoto];
  state.joinable.joinMe0123 = "trip5";
  await page.goto("/trip-invite/joinMe0123");
  await expect(page).toHaveURL(/\/travel\/trips\/trip5/);
  await expect(page.getByRole("heading", { level: 1, name: "Kyoto" })).toBeVisible();
  await expect(page.getByText("You've joined the trip to Kyoto.")).toBeVisible();
  // The link worked once: it is spent now.
  expect(state.joinable.joinMe0123).toBeUndefined();
});

test("a trip invite that doesn't work says so and points the way back", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/trip-invite/notALink");
  await expect(page.getByRole("heading", { name: "This invite doesn't work any more" })).toBeVisible();
  await expect(page.getByText("Ask the trip's owner for a new link.")).toBeVisible();
  await page.getByRole("link", { name: "Go to Home" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("the owner opening their own invite link is told so", async ({ page }) => {
  const state = await fakeApi(page);
  state.invites.trip1 = [{ id: "inv1", created_at: "2026-09-28T03:00:00Z", expires_at: "2026-10-05T03:00:00Z", token: "ownLink0001" }];
  await page.goto("/trip-invite/ownLink0001");
  await expect(page.getByRole("heading", { name: "That's your own invite link" })).toBeVisible();
});

test("signed out, a trip invite asks for Telegram and carries the link through sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  await page.goto("/trip-invite/tok999");
  await expect(page).toHaveURL(/\/trip-invite\/tok999$/);
  await expect(page.getByRole("heading", { name: "You've been invited to a trip" })).toBeVisible();
  await expect(page.getByText("Sign in with Telegram to join.")).toBeVisible();
  await expect(page.locator(".tg-login script")).toHaveAttribute("data-auth-url", /callback\?trip_invite=tok999$/);
});

test("a guest sees only Travel, with no chat, and nothing the server refuses is asked", async ({ page }) => {
  const state = await fakeApi(page, { guest: true });
  state.trips = [kyoto];
  await page.goto("/travel");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kyoto" }).first()).toBeVisible();

  // No other department, Settings or chat, in the header, a rail or a bar.
  for (const name of ["Home", "Accounting", "Investment", "Settings"]) {
    await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: "Ask Nexus" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main (mobile)" })).toHaveCount(0);

  // Every other address goes back to Travel.
  for (const path of ["/", "/accounting/ledger", "/settings", "/investment"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/travel$/);
  }

  // The trips they are on open.
  await page.goto("/travel/trips/trip5");
  await expect(page.getByRole("heading", { level: 1, name: "Kyoto" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask Nexus" })).toHaveCount(0);

  // Nothing on the way was a request the server refuses a guest (it would be a 403).
  expect(state.forbidden).toEqual([]);

  // Signing out goes to the sign-in page.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("a guest who opens a trip invite is joined and lands on the trip", async ({ page }) => {
  const state = await fakeApi(page, { guest: true });
  state.trips = [kyoto];
  state.joinable.guestJoin01 = "trip5";
  await page.goto("/trip-invite/guestJoin01");
  await expect(page).toHaveURL(/\/travel\/trips\/trip5/);
  await expect(page.getByRole("heading", { level: 1, name: "Kyoto" })).toBeVisible();
  await expect(page.getByText("You've joined the trip to Kyoto.")).toBeVisible();
});
