import { type CDPSession, expect, type Locator, type Page, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Touch gestures, sent as real touches through the browser (Playwright's own touchscreen only taps).
const touchOnly = (info: { project: { name: string } }) => test.skip(info.project.name !== "mobile", "a touch gesture");

type Point = { x: number; y: number };

async function centre(target: Locator): Promise<Point> {
  await target.scrollIntoViewIfNeeded();
  const box = (await target.boundingBox())!;
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

const send = (cdp: CDPSession, type: "touchStart" | "touchMove" | "touchEnd" | "touchCancel", at?: Point) =>
  cdp.send("Input.dispatchTouchEvent", { type, touchPoints: at ? [{ x: Math.round(at.x), y: Math.round(at.y) }] : [] });

/** A finger held on the target for longer than a long press takes. */
async function hold(page: Page, cdp: CDPSession, target: Locator, ms = 700) {
  const at = await centre(target);
  await send(cdp, "touchStart", at);
  await page.waitForTimeout(ms);
  await send(cdp, "touchEnd");
}

const row = (page: Page, name: string) => page.getByRole("row").filter({ has: page.getByRole("button", { name, exact: true }) });
const bar = (page: Page) => page.getByRole("region", { name: "Selection" });
const toast = (page: Page) => page.locator(".toast");

async function setup(page: Page, options: Parameters<typeof fakeApi>[1] = {}) {
  const state = await fakeApi(page, options);
  const cdp = await page.context().newCDPSession(page);
  await page.goto("/accounting/ledger");
  await expect(row(page, "Grab")).toBeVisible();
  return { state, cdp };
}

test("holding a row selects it, taps add more, and Delete acts at once with Undo", async ({ page }, info) => {
  touchOnly(info);
  const { cdp } = await setup(page);
  await expect(bar(page)).toHaveCount(0);

  await hold(page, cdp, row(page, "Grab"));
  await expect(bar(page)).toBeVisible();
  await expect(bar(page)).toContainText("1 selected");
  await expect(row(page, "Grab")).toHaveAttribute("aria-selected", "true");
  // Letting go didn't also open the entry.
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The bar is at the bottom, above the tab bar, in the screen.
  const box = (await bar(page).boundingBox())!;
  const nav = (await page.locator(".bottom-nav").boundingBox())!;
  const view = page.viewportSize()!;
  expect(box.y).toBeGreaterThan(view.height / 2);
  expect(box.y + box.height).toBeLessThanOrEqual(nav.y);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(view.width);

  // A tap now ticks instead of opening.
  await page.touchscreen.tap(...Object.values(await centre(row(page, "Employer"))) as [number, number]);
  await expect(bar(page)).toContainText("2 selected");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await bar(page).getByRole("button", { name: "Delete" }).click();
  await expect(toast(page)).toContainText("Deleted 2 transactions.");
  await expect(row(page, "Grab")).toHaveCount(0);
  await expect(row(page, "Employer")).toHaveCount(0);
  await expect(bar(page)).toHaveCount(0);

  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(row(page, "Grab")).toBeVisible();
  await expect(row(page, "Employer")).toBeVisible();
  await expect(toast(page)).toContainText("Restored.");
});

test("Cancel clears the selection, and taps open entries again", async ({ page }, info) => {
  touchOnly(info);
  const { cdp } = await setup(page);
  await hold(page, cdp, row(page, "Grab"));
  await expect(bar(page)).toContainText("1 selected");
  await bar(page).getByRole("button", { name: "Cancel" }).click();
  await expect(bar(page)).toHaveCount(0);
  await expect(row(page, "Grab")).toHaveAttribute("aria-selected", "false");
  await page.touchscreen.tap(...Object.values(await centre(row(page, "Grab"))) as [number, number]);
  await expect(page.getByRole("dialog", { name: "Edit transaction" })).toBeVisible();
});

test("a short tap still opens the edit sheet and selects nothing", async ({ page }, info) => {
  touchOnly(info);
  const { cdp } = await setup(page);
  const at = await centre(row(page, "Grab"));
  await send(cdp, "touchStart", at);
  await page.waitForTimeout(120);
  await send(cdp, "touchEnd");
  await expect(page.getByRole("dialog", { name: "Edit transaction" })).toBeVisible();
  await expect(bar(page)).toHaveCount(0);
});

test("dragging to scroll doesn't select, even when it takes longer than a long press", async ({ page }, info) => {
  touchOnly(info);
  const { cdp } = await setup(page, { longLedger: true });
  const start = await centre(row(page, "Grab"));
  const scrolled = () => page.locator(".main-viewport").evaluate((el) => el.scrollTop);
  expect(await scrolled()).toBe(0);
  await send(cdp, "touchStart", start);
  for (let i = 1; i <= 6; i++) {
    await send(cdp, "touchMove", { x: start.x, y: start.y - i * 30 });
    await page.waitForTimeout(20);
  }
  await page.waitForTimeout(700);
  await send(cdp, "touchEnd");
  await expect.poll(scrolled).toBeGreaterThan(50);
  await expect(bar(page)).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("tr[aria-selected=true]")).toHaveCount(0);
});

test("the bar never covers the last row, and steps aside for the keyboard", async ({ page }, info) => {
  touchOnly(info);
  const { cdp } = await setup(page, { longLedger: true });
  await hold(page, cdp, row(page, "Corner Stall 3"));
  await expect(bar(page)).toContainText("1 selected");
  await page.locator(".main-viewport").evaluate((el) => el.scrollTo({ top: 100000 }));
  const last = (await row(page, "Corner Stall 40").boundingBox())!;
  const box = (await bar(page).boundingBox())!;
  expect(last.y + last.height).toBeLessThanOrEqual(box.y);

  await page.evaluate(() => document.documentElement.classList.add("keyboard"));
  await expect(bar(page)).toBeHidden();
  await page.evaluate(() => document.documentElement.classList.remove("keyboard"));
  await expect(bar(page)).toBeVisible();
});

test("the Select button still works without a long press", async ({ page }, info) => {
  touchOnly(info);
  await setup(page);
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: /Select Grab/ }).check();
  await expect(bar(page)).toContainText("1 selected");
  await page.getByRole("button", { name: "Done" }).click();
  await expect(bar(page)).toHaveCount(0);
});

test("the edit sheet deletes the entry, and Undo brings it back", async ({ page }) => {
  await setup(page);
  await page.getByRole("button", { name: "Grab", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await expect(sheet).toBeVisible();
  await sheet.getByRole("button", { name: "Delete" }).click();
  await expect(sheet).toBeHidden();
  await expect(toast(page)).toContainText("Deleted Grab.");
  await expect(row(page, "Grab")).toHaveCount(0);

  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(toast(page)).toContainText("Restored.");
  await expect(row(page, "Grab")).toBeVisible();
});

test("a new entry has no Delete", async ({ page }) => {
  await setup(page);
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Delete" })).toHaveCount(0);
});
