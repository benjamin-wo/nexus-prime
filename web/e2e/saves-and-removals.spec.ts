import { expect, type Page, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const toast = (page: Page) => page.locator(".toast");

// Nothing here answers a browser dialog: with no handler Playwright dismisses one, so a flow that still
// used window.confirm would stop at it.

test("logging an expense says so with Undo, and Undo takes it out again", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await sheet.getByLabel("Amount").fill("5.50");
  await sheet.getByLabel("Paid to").fill("Kopi Stall");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();

  await expect(toast(page)).toContainText("Logged SGD 5.50 · Kopi Stall.");
  await expect(page.getByRole("button", { name: "Kopi Stall", exact: true })).toBeVisible();
  // Everything in the toast fits the screen, and its button isn't broken over two lines.
  const box = (await toast(page).boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  const undo = toast(page).getByRole("button", { name: "Undo" });
  expect((await undo.boundingBox())!.height).toBeLessThan(60);

  await undo.click();
  await expect(toast(page)).toContainText("Removed Kopi Stall.");
  await expect(page.getByRole("button", { name: "Kopi Stall", exact: true })).toHaveCount(0);
  expect(state.txs.find((t) => t.counterparty === "Kopi Stall")?.deleted).toBe(true);
});

test("changing an expense says Saved", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Grab", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await sheet.getByLabel("Paid to").fill("Grab Ride");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(toast(page)).toContainText("Saved.");
  await expect(toast(page).getByRole("button", { name: "Undo" })).toHaveCount(0);
});

test("removing a holding asks in the page, and Keep leaves it", async ({ page }) => {
  const state = await fakeApi(page);
  state.holdings = [{ symbol: "NVDA", quantity: "10", average_cost: { amount: "118.4000", currency: "USD" }, cost: { amount: "1184.0000", currency: "USD" }, updated_at: "2026-09-28T03:00:00Z" }];
  await page.goto("/investment");
  const holdings = page.getByRole("region", { name: "Holdings" });
  await holdings.getByRole("button", { name: /^NVDA, / }).click();
  const sheet = page.getByRole("dialog", { name: "NVDA" });
  // Edit and Remove are not twins: Remove is the quiet one, and sits apart.
  const edit = (await sheet.getByRole("button", { name: "Edit NVDA" }).boundingBox())!;
  const remove = sheet.getByRole("button", { name: "Remove NVDA" });
  const removeBox = (await remove.boundingBox())!;
  expect(removeBox.x - (edit.x + edit.width)).toBeGreaterThan(16);
  await expect(remove).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");

  await remove.click();
  const ask = sheet.getByRole("group", { name: "Remove NVDA" });
  await expect(ask).toContainText("Remove NVDA from your holdings?");
  await ask.getByRole("button", { name: "Keep" }).click();
  await expect(sheet.getByRole("button", { name: "Remove NVDA" })).toBeVisible();
  expect(state.holdings).toHaveLength(1);

  await remove.click();
  await ask.getByRole("button", { name: "Remove" }).click();
  await expect(holdings.getByRole("button", { name: /^NVDA, / })).toHaveCount(0);
  await expect(toast(page)).toContainText("Removed NVDA");
});

test("adding a holding and recording a trade say what was done", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/investment");
  await page.getByRole("button", { name: "Add one by hand" }).click();
  const add = page.getByRole("form", { name: "Add a holding" });
  await add.getByLabel("Ticker").fill("msft");
  await add.getByLabel("Shares").fill("3");
  await add.getByLabel(/Avg cost/).fill("400");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(toast(page)).toContainText("Added MSFT");

  await page.getByRole("button", { name: "Record a trade" }).click();
  const trade = page.getByRole("form", { name: "Record a trade" });
  await trade.getByLabel("Side").selectOption("sell");
  await trade.getByLabel("Ticker").fill("msft");
  await trade.getByLabel("Shares").fill("1");
  await trade.getByLabel("Price (USD)").fill("410");
  await trade.getByRole("button", { name: "Record" }).click();
  await expect(toast(page)).toContainText("Recorded: sold 1 MSFT");
});

test("forgetting a memory asks first", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings/memory");
  const card = page.getByRole("region", { name: "What Nexus remembers" });
  await card.getByRole("button", { name: "Forget: Ann is the user's sister." }).click();
  const ask = card.getByRole("group", { name: "Forget: Ann is the user's sister." });
  await ask.getByRole("button", { name: "Keep" }).click();
  await expect(card.getByText("Ann is the user's sister.")).toBeVisible();
  await card.getByRole("button", { name: "Forget: Ann is the user's sister." }).click();
  await ask.getByRole("button", { name: "Forget" }).click();
  await expect(card.getByText("Ann is the user's sister.")).toHaveCount(0);
});

async function addTokyo(page: Page) {
  await page.goto("/travel");
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  await form.getByLabel("Where").fill("Tokyo");
  await form.getByLabel("From").fill("2026-11-10");
  await form.getByLabel("To").fill("2026-11-12");
  await form.getByRole("button", { name: "Add trip" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip1(\?.*)?$/);
}

test("Delete trip is apart from the photo options and asks in the menu", async ({ page }) => {
  const state = await fakeApi(page);
  await addTokyo(page);
  await page.getByRole("button", { name: "Trip options" }).click();
  const menu = page.getByRole("menu", { name: "Trip options" });
  const another = (await menu.getByRole("menuitem", { name: "Another photo" }).boundingBox())!;
  const noPhoto = (await menu.getByRole("menuitem", { name: "No photo" }).boundingBox())!;
  const del = (await menu.getByRole("menuitem", { name: "Delete trip" }).boundingBox())!;
  // The last in the menu, with a gap the photo items don't have between them.
  expect(del.y - (noPhoto.y + noPhoto.height)).toBeGreaterThan(noPhoto.y - (another.y + another.height) + 2);

  await menu.getByRole("menuitem", { name: "Delete trip" }).click();
  const ask = page.getByRole("group", { name: "Delete the trip to Tokyo" });
  await expect(ask).toContainText("Its expenses stay in the ledger.");
  await ask.getByRole("button", { name: "Keep" }).click();
  expect(state.trips).toHaveLength(1);

  await page.getByRole("menuitem", { name: "Delete trip" }).click();
  await ask.getByRole("button", { name: "Delete trip" }).click();
  await expect(page).toHaveURL(/\/travel$/);
  expect(state.trips).toHaveLength(0);
});

test("stopping the shared link asks in the sheet", async ({ page }) => {
  const state = await fakeApi(page);
  await addTokyo(page);
  await page.getByRole("button", { name: "Share the plan" }).click();
  const sheet = page.getByRole("dialog", { name: "Share the plan" });
  await sheet.getByRole("button", { name: "Create a link" }).click();
  await expect(sheet.getByLabel("The trip's link")).toBeVisible();
  await sheet.getByRole("button", { name: "Stop sharing" }).click();
  await expect(sheet.getByRole("group", { name: "Stop sharing" })).toContainText("The link stops working for everyone who has it.");
  await sheet.getByRole("button", { name: "Keep sharing" }).click();
  expect(Object.keys(state.shares)).toHaveLength(1);
});
