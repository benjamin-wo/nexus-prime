import { expect, type Page, test } from "@playwright/test";

import { fakeApi, sharedTrip } from "./fake-api";

/** Adds a trip of the owner's own through the form, as the journeys do. */
async function addTrip(page: Page, where: string, from: string, to: string) {
  await page.goto("/travel");
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  await form.getByLabel("Where").fill(where);
  await form.getByLabel("From").fill(from);
  await form.getByLabel("To").fill(to);
  await expect(form).toContainText("Spending in");
  await form.getByRole("button", { name: "Add trip" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip1(\?.*)?$/);
}

const tabs = (page: Page) => page.getByRole("navigation", { name: "Trip sections" });

test("the owner makes an invite link, sees it once with how long it works, and cancels it", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");

  await page.getByRole("button", { name: "Share the plan" }).click();
  const sheet = page.getByRole("dialog", { name: "Share the plan" });
  // The owner is on their own trip, with the read-only link below the people.
  await expect(sheet.getByRole("heading", { name: "People" })).toBeVisible();
  await expect(sheet.getByRole("list", { name: "People on this trip" })).toContainText("You · Owner");
  await expect(sheet.getByRole("heading", { name: "Read-only link" })).toBeVisible();

  await sheet.getByRole("button", { name: "Invite someone" }).click();
  await expect(sheet.getByLabel("Invite link")).toHaveValue(/\/trip-invite\/fakeInvite0001x+$/);
  await expect(sheet.getByText("Works once, for 7 days.")).toBeVisible();
  const open = sheet.getByRole("list", { name: "Invite links not used yet" });
  await expect(open.getByRole("listitem")).toHaveCount(1);
  expect(state.invites.trip1).toHaveLength(1);

  await open.getByRole("button", { name: /^Cancel the invite/ }).click();
  await expect(sheet.getByRole("list", { name: "Invite links not used yet" })).toHaveCount(0);
  await expect(sheet.getByLabel("Invite link")).toHaveCount(0);
  expect(state.invites.trip1).toHaveLength(0);
});

test("the owner removes someone after a confirmation", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  state.members.trip1 = [{ id: "u-alex", name: "Alex T.", role: "member", added_at: "2026-09-20T03:00:00Z", you: false }];
  await page.reload();

  const asked: string[] = [];
  page.on("dialog", (d) => {
    asked.push(d.message());
    void d.accept();
  });
  await page.getByRole("button", { name: "Share the plan" }).click();
  const sheet = page.getByRole("dialog", { name: "Share the plan" });
  const people = sheet.getByRole("list", { name: "People on this trip" });
  await expect(people.getByRole("listitem")).toHaveCount(2);
  await expect(people).toContainText("Alex T.");
  await people.getByRole("button", { name: "Remove Alex T." }).click();
  await expect(people.getByRole("listitem")).toHaveCount(1);
  expect(asked).toEqual(["Remove Alex T. from this trip? They'll lose access straight away."]);
  expect(state.members.trip1).toEqual([]);
});

test("a trip you were added to has no Money tab, no cost field and says whose it is", async ({ page }) => {
  const state = await fakeApi(page);
  state.trips = [sharedTrip()];
  // An address for the Money tab opens Plan instead.
  await page.goto("/travel/trips/shared1?tab=money");
  await expect(page.getByRole("heading", { level: 1, name: "Lisbon" })).toBeVisible();
  await expect(page.getByText("Shared by Alex T.")).toBeVisible();
  await expect(tabs(page).getByRole("button")).toHaveText(["Plan", "Ideas", "Prep"]);
  await expect(tabs(page).getByRole("button", { name: "Plan", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page).toHaveURL(/tab=plan/);
  await expect(page.getByRole("region", { name: /Spending|Budget/ })).toHaveCount(0);

  // Owner actions are gone: the menu (edit, photo, delete) and the read-only link.
  await expect(page.getByRole("button", { name: "Trip options" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Share the plan" })).toHaveCount(0);
  // Nothing about a budget is offered as the next thing to do.
  await expect(page.getByText("No budget yet")).toHaveCount(0);

  // Adding a booking or a plan has no cost or currency.
  await page.locator(".trip-fab-button, .trip-add-desktop").filter({ visible: true }).click();
  const add = page.getByRole("dialog", { name: "Add to Lisbon" });
  await expect(add.getByRole("button", { name: "Type it" })).toHaveCount(0);
  await add.getByRole("button", { name: /A booking/ }).click();
  await add.getByText("More details").click();
  await expect(add.getByLabel("Booking reference")).toBeVisible();
  await expect(add.getByLabel("Cost")).toHaveCount(0);
  await expect(add.getByLabel("Currency")).toHaveCount(0);
});

test("a member's notes are saved through the notes endpoint", async ({ page }) => {
  const state = await fakeApi(page);
  state.trips = [sharedTrip()];
  await page.goto("/travel/trips/shared1?tab=prep");
  await page.getByRole("textbox", { name: "Notes" }).fill("Bring the tickets");
  await page.getByRole("form", { name: "Trip notes" }).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => state.notesPuts.at(-1)).toEqual({ notes: "Bring the tickets" });
  expect(state.tripPuts).toHaveLength(0);
});

test("a member sees the people, can leave, and is told they're no longer on the trip afterwards", async ({ page }) => {
  const state = await fakeApi(page);
  state.trips = [sharedTrip()];
  page.on("dialog", (d) => void d.accept());
  await page.goto("/travel");
  // The list keeps their own trips apart from the ones shared with them.
  const shared = page.getByRole("region", { name: "Shared with you" });
  await expect(shared.getByRole("link", { name: "Lisbon" })).toBeVisible();
  await expect(shared).toContainText("Shared by Alex T.");
  await shared.getByRole("link", { name: "Lisbon" }).click();

  await page.getByRole("button", { name: "People on this trip" }).click();
  const sheet = page.getByRole("dialog", { name: "People on this trip" });
  const people = sheet.getByRole("list", { name: "People on this trip" });
  await expect(people.getByRole("listitem")).toHaveCount(2);
  await expect(people.getByRole("listitem").first()).toContainText("Alex T.");
  await expect(people.getByRole("listitem").nth(1)).toContainText("You · Member");
  await expect(sheet.getByRole("button", { name: "Invite someone" })).toHaveCount(0);
  await expect(sheet.getByRole("heading", { name: "Read-only link" })).toHaveCount(0);

  await sheet.getByRole("button", { name: "Leave trip" }).click();
  await expect(page).toHaveURL(/\/travel$/);
  expect(state.trips).toHaveLength(0);

  // Opening the trip again, from an old link: the server says there is no such trip.
  await page.goto("/travel/trips/shared1");
  await expect(page.getByText("You're no longer on this trip.")).toBeVisible();
  await page.getByRole("link", { name: "Go to your trips" }).click();
  await expect(page).toHaveURL(/\/travel$/);
});

test("the latest change to a shared plan shows under Next up, and a tap lists the recent ones", async ({ page }) => {
  const state = await fakeApi(page);
  state.trips = [sharedTrip()];
  const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
  state.activity.shared1 = [
    { actor: "Alex T.", summary: "added Dinner at Sushi Ten", at: ago(5 * 60_000 + 5_000) },
    { actor: "Alex T.", summary: "changed the notes", at: ago(2 * 24 * 3_600_000) },
  ];
  await page.goto("/travel/trips/shared1");
  const line = page.getByRole("button", { name: /Alex T\. added Dinner at Sushi Ten/ });
  await expect(line).toContainText("Alex T. added Dinner at Sushi Ten · 5 min ago");
  await line.click();
  const sheet = page.getByRole("dialog", { name: "Recent changes" });
  await expect(sheet.getByRole("listitem")).toHaveCount(2);
  await expect(sheet).toContainText("changed the notes");
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
});

test("a trip nobody else is on has no activity line", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  state.activity.trip1 = [{ actor: "Ben", summary: "changed the notes", at: new Date().toISOString() }];
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Tokyo" })).toBeVisible();
  await expect(page.getByRole("button", { name: /changed the notes/ })).toHaveCount(0);
});

test("a guest on a trip is asked for nothing a guest can't have", async ({ page }) => {
  const state = await fakeApi(page, { guest: true });
  state.trips = [sharedTrip()];
  await page.goto("/travel");
  await expect(page.getByRole("region", { name: "Shared with you" }).getByRole("link", { name: "Lisbon" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New trip" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Where to next?" })).toHaveCount(0);
  await page.getByRole("link", { name: "Lisbon" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Lisbon" })).toBeVisible();
  await expect(tabs(page).getByRole("button")).toHaveText(["Plan", "Ideas", "Prep"]);
  await page.locator(".trip-fab-button, .trip-add-desktop").filter({ visible: true }).click();
  await expect(page.getByRole("button", { name: "Type it" })).toHaveCount(0);
  expect(state.forbidden).toEqual([]);
});
