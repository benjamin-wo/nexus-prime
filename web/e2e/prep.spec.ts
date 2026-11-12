import { expect, type Page, test } from "@playwright/test";

import { fakeApi, sharedTrip } from "./fake-api";

// The Prep tab's journeys: to-dos, suggestions, cover and documents and what they do on Money. Made-up data only.

/** Adds a trip of the owner's own through the form, as the other journeys do. */
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

async function openTab(page: Page, name: "Plan" | "Ideas" | "Money" | "Prep") {
  const tab = page.getByRole("navigation", { name: "Trip sections" }).getByRole("button", { name, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-current", "page");
}

/** The trip page's + for the open tab: a floating button on a phone, a button in the header on a wide screen. */
const tripAdd = (page: Page) => page.locator(".trip-fab-button, .trip-add-desktop").filter({ visible: true });
const gettingReady = (page: Page) => page.getByRole("region", { name: "Getting ready" });
const coverCard = (page: Page) => page.getByRole("region", { name: "Cover and documents" });

/** A day this many days ahead on this device, which is how the app reads a to-do's date. */
const daysAhead = (n: number) => new Date(Date.now() + n * 86_400_000).toLocaleDateString("en-CA");

test("a to-do with a date is added from Prep, ticked, and sinks struck through", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  await openTab(page, "Prep");

  const ready = gettingReady(page);
  const add = ready.getByRole("form", { name: "Add a to-do" });
  await expect(add.getByRole("button", { name: "Add", exact: true })).toBeDisabled(); // nothing typed yet
  await add.getByLabel("To-do").fill("Book the airport taxi");
  await add.getByLabel("By (optional)").fill(daysAhead(5));
  await add.getByRole("button", { name: "Add", exact: true }).click();
  // Wait for the first to go through: the form clears then, and would wipe a second
  // to-do typed before it.
  await expect(ready.locator(".prep-todo")).toHaveCount(1);
  await expect(add.getByLabel("To-do")).toHaveValue("");
  await add.getByLabel("To-do").fill("Buy a SIM card");
  await add.getByRole("button", { name: "Add", exact: true }).click();

  const rows = ready.locator(".prep-todo");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Book the airport taxi");
  await expect(rows.nth(0)).toContainText("By ");
  await expect(rows.nth(1)).not.toContainText("By ");
  await expect(add.getByLabel("To-do")).toHaveValue(""); // the form clears once it went through
  expect(state.todos.trip1.map((t) => [t.text, t.due !== null, t.done])).toEqual([
    ["Book the airport taxi", true, false],
    ["Buy a SIM card", false, false],
  ]);

  // Ticking the first sinks it below the one still to do, struck through.
  await ready.getByRole("checkbox", { name: "Book the airport taxi" }).check();
  await expect(rows.nth(0)).toContainText("Buy a SIM card");
  await expect(rows.nth(1)).toContainText("Book the airport taxi");
  await expect(rows.nth(1)).toHaveClass(/is-done/);
  await expect(rows.nth(1).locator(".prep-title")).toHaveCSS("text-decoration-line", "line-through");
  await expect(rows.nth(0).locator(".prep-title")).toHaveCSS("text-decoration-line", "none");
  await expect.poll(() => state.todos.trip1.map((t) => t.done)).toEqual([true, false]);

  // A date gone by, and not done, is called overdue; once done it is not.
  state.todos.trip1 = [...state.todos.trip1, { id: "late1", text: "Renew the passport", due: "2020-01-15", done: false }];
  await page.reload();
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(1)).toContainText("Renew the passport");
  await expect(rows.nth(1)).toContainText("Overdue · ");
  await expect(rows.nth(0)).not.toContainText("Overdue");
  await ready.getByRole("checkbox", { name: "Renew the passport" }).check();
  await expect(rows.nth(2)).toContainText("Renew the passport");
  await expect(rows.nth(2)).not.toContainText("Overdue");

  // Remove takes one off the list for good.
  await ready.getByRole("button", { name: "Remove Buy a SIM card" }).click();
  await expect(rows).toHaveCount(2);
  await expect.poll(() => state.todos.trip1.map((t) => t.text)).toEqual(["Book the airport taxi", "Renew the passport"]);
});

test("a suggestion is hidden with Not needed, or added: the visa one becomes a to-do", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  await openTab(page, "Prep");

  const ready = gettingReady(page);
  const list = ready.getByRole("list", { name: "Things to do" });
  await expect(list).toContainText("Travel insurance");
  await expect(list).toContainText("Check entry rules for Tokyo");
  await expect(list).toContainText("Passport valid 6 months after you're back");

  // Not needed hides it, and it stays hidden after a reload.
  await ready.getByRole("button", { name: "Not needed: Passport valid 6 months after you're back" }).click();
  await expect(list).not.toContainText("Passport valid 6 months");
  await expect.poll(() => state.dismissed.trip1).toEqual(["passport"]);
  await page.reload();
  await expect(gettingReady(page).getByRole("list", { name: "Things to do" })).toContainText("Check entry rules for Tokyo");
  await expect(gettingReady(page).getByRole("list", { name: "Things to do" })).not.toContainText("Passport valid 6 months");

  // Add on the visa one makes it a to-do and takes the suggestion away.
  await ready.getByRole("button", { name: "Add: Check entry rules for Tokyo" }).click();
  const todo = ready.getByRole("checkbox", { name: "Check entry rules for Tokyo" });
  await expect(todo).toBeVisible();
  await expect(todo).not.toBeChecked();
  await expect(ready.getByRole("button", { name: "Add: Check entry rules for Tokyo" })).toHaveCount(0);
  await expect(ready.getByRole("button", { name: "Not needed: Check entry rules for Tokyo" })).toHaveCount(0);
  expect(state.todos.trip1.map((t) => [t.text, t.due, t.done])).toEqual([["Check entry rules for Tokyo", null, false]]);
});

test("travel insurance is added from Add to prep, counted under Money, and logged as an expense", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  await openTab(page, "Prep");

  await tripAdd(page).click();
  const choice = page.getByRole("dialog", { name: "Add to prep" });
  await expect(choice.locator(".way")).toHaveText([/A to-do/, /Cover or a document/, /Something to pack/]);
  await choice.getByRole("button", { name: /Cover or a document/ }).click();

  const sheet = page.getByRole("dialog", { name: "Add cover or a document" });
  await expect(sheet.getByRole("radio", { name: "Insurance" })).toBeChecked();
  await sheet.getByLabel("Insurer").fill("Harbour Cover");
  await sheet.getByLabel("Policy or reference").fill("TX-4471");
  await sheet.getByLabel("Emergency phone").fill("+65 6123 4567");
  await sheet.getByLabel("Cost").fill("89");
  await expect(sheet.getByLabel("Currency")).toHaveValue("SGD");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toHaveCount(0);

  // The row has a Call link, the reference to copy and the cost; the insurance suggestion is gone.
  const row = coverCard(page).getByRole("listitem");
  await expect(row).toContainText("Harbour Cover");
  await expect(row).toContainText("Insurance · TX-4471");
  await expect(row).toContainText("SGD 89.00");
  await expect(row.getByRole("link", { name: "Call +65 6123 4567" })).toHaveAttribute("href", "tel:+6561234567");
  await expect(row.getByRole("button", { name: "Copy reference TX-4471" })).toBeVisible();
  await expect(gettingReady(page)).not.toContainText("Travel insurance");
  expect(state.covers.trip1).toMatchObject([{ kind: "insurance", name: "Harbour Cover", reference: "TX-4471", phone: "+65 6123 4567", cost: { currency: "SGD" }, logged: false }]);
  expect(Number(state.covers.trip1[0].cost?.amount)).toBe(89);

  // Money counts it as booked, and lists it under Bookings paid.
  await openTab(page, "Money");
  const summary = page.getByRole("region", { name: "Spent and booked", exact: true });
  await expect(summary).toContainText("SGD 909.00");
  await page.getByRole("button", { name: /^Bookings paid/ }).click();
  const paid = page.getByRole("list", { name: "Bookings paid" });
  await expect(paid).toContainText("Harbour Cover");
  await expect(paid).toContainText("SGD 89.00");

  // Log it asks first; Not now leaves it as it was.
  await paid.getByRole("button", { name: "Log it: Harbour Cover" }).click();
  const confirm = paid.getByRole("group", { name: "Log Harbour Cover" });
  await expect(confirm).toContainText("Record SGD 89.00 as spent on Travel? Nexus only records it.");
  await confirm.getByRole("button", { name: "Not now" }).click();
  await expect(confirm).toHaveCount(0);
  expect(state.coverItems.trip1 ?? []).toHaveLength(0);

  await paid.getByRole("button", { name: "Log it: Harbour Cover" }).click();
  await paid.getByRole("group", { name: "Log Harbour Cover" }).getByRole("button", { name: "Log it", exact: true }).click();
  await expect(paid).toContainText("Logged");
  await expect(paid.getByRole("button", { name: /^Log it/ })).toHaveCount(0);
  expect(state.prepRequests.filter((r) => r.request.endsWith("/log")).map((r) => r.request)).toEqual(["POST /travel/trips/trip1/covers/cover1/log"]);
  expect(state.coverItems.trip1).toMatchObject([{ counterparty: "Harbour Cover", category: "Travel", amount: { currency: "SGD" } }]);
  expect(Number(state.coverItems.trip1[0].amount.amount)).toBe(89);
  expect(state.covers.trip1[0].logged).toBe(true);

  // Prep says the same.
  await openTab(page, "Prep");
  await expect(coverCard(page).getByRole("listitem")).toContainText("Logged");
  await expect(coverCard(page).getByRole("button", { name: /^Log it/ })).toHaveCount(0);
});

test("a cover is changed and deleted from its sheet, after asking", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  state.covers.trip1 = [
    { id: "cv1", kind: "visa", name: "Japan e-visa", reference: "EV-2209", phone: null, starts: "2026-11-10", ends: "2026-11-12", cost: null, logged: false, note: null },
  ];
  await page.reload();
  await openTab(page, "Prep");
  const card = coverCard(page);
  await expect(card).toContainText("Visa · EV-2209 · 10–12 Nov");
  await card.getByRole("button", { name: /Japan e-visa/ }).click();
  const sheet = page.getByRole("dialog", { name: "Change Japan e-visa" });
  await sheet.getByLabel("Policy or reference").fill("EV-9981");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(card).toContainText("EV-9981");
  expect(state.covers.trip1[0].reference).toBe("EV-9981");

  await card.getByRole("button", { name: /Japan e-visa/ }).click();
  await page.getByRole("dialog", { name: "Change Japan e-visa" }).getByRole("button", { name: "Delete" }).click();
  await page.getByRole("group", { name: "Delete Japan e-visa" }).getByRole("button", { name: "Delete Japan e-visa" }).click();
  await expect(card.getByRole("listitem")).toHaveCount(0);
  expect(state.covers.trip1).toEqual([]);
});

test("a member sees cover without its cost or a way to log it, and can add a to-do", async ({ page }) => {
  const state = await fakeApi(page);
  state.trips = [sharedTrip()];
  state.covers.shared1 = [
    { id: "cv1", kind: "insurance", name: "Harbour Cover", reference: "TX-4471", phone: "+65 6123 4567", starts: "2026-11-10", ends: "2026-11-12", cost: { amount: "89.0000", currency: "SGD" }, logged: false, note: null },
  ];
  await page.goto("/travel/trips/shared1?tab=prep");
  await expect(page.getByRole("heading", { level: 1, name: "Lisbon" })).toBeVisible();

  const card = coverCard(page);
  const rows = card.getByRole("list", { name: "Cover and documents" });
  await expect(rows).toContainText("Harbour Cover");
  await expect(rows).toContainText("Insurance · TX-4471");
  await expect(rows.getByRole("link", { name: "Call +65 6123 4567" })).toHaveAttribute("href", "tel:+6561234567");
  await expect(rows).not.toContainText("89");
  await expect(rows).not.toContainText("SGD");
  await expect(page.getByRole("button", { name: /^Log it/ })).toHaveCount(0);

  // The cover's sheet has no cost to fill in.
  await card.getByRole("button", { name: /Harbour Cover/ }).click();
  const sheet = page.getByRole("dialog", { name: "Change Harbour Cover" });
  await expect(sheet.getByLabel("Policy or reference")).toHaveValue("TX-4471");
  await expect(sheet.getByLabel("Cost")).toHaveCount(0);
  await expect(sheet.getByLabel("Currency")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);

  // A to-do is theirs to add, and the money tab isn't theirs to see.
  const add = gettingReady(page).getByRole("form", { name: "Add a to-do" });
  await add.getByLabel("To-do").fill("Book the airport taxi");
  await add.getByRole("button", { name: "Add", exact: true }).click();
  await expect(gettingReady(page).getByRole("checkbox", { name: "Book the airport taxi" })).toBeVisible();
  expect(state.todos.shared1.map((t) => t.text)).toEqual(["Book the airport taxi"]);
  await expect(page.getByRole("navigation", { name: "Trip sections" }).getByRole("button")).toHaveText(["Plan", "Ideas", "Prep"]);
  expect(state.prepRequests.every((r) => !r.request.endsWith("/log"))).toBe(true);
});
