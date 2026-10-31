import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const scrollTo = (page: import("@playwright/test").Page, top: number) =>
  page.locator(".main-viewport").evaluate((el, y) => el.scrollTo({ top: y }), top);

test("a long ledger gets a floating Add once the header's has scrolled away", async ({ page }) => {
  await fakeApi(page, { longLedger: true });
  await page.goto("/accounting/ledger");
  const header = page.getByRole("button", { name: "Add transaction" });
  const floating = page.getByRole("button", { name: "Add a transaction" });
  await expect(page.getByRole("button", { name: "Corner Stall 40", exact: true })).toBeAttached();

  // At the top the header's Add is in view and nothing floats.
  await expect(header).toBeVisible();
  await expect(floating).toHaveCount(0);

  // Down the page the floating one appears, and stays while scrolling down (unlike the trip's, which
  // steps aside on a phone): no scroll back up is needed.
  await scrollTo(page, 600);
  await scrollTo(page, 1200);
  await expect(page.locator(".shell")).toHaveClass(/scrolling-down/);
  await expect(floating).toBeVisible();
  await expect(floating).toHaveCSS("opacity", "1");
  await expect(floating).toHaveCSS("pointer-events", "auto");
  await expect(floating).toHaveText("Add");

  // It stays inside the screen, and on a phone clears the bottom bar.
  const box = (await floating.boundingBox())!;
  const view = page.viewportSize()!;
  expect(box.x + box.width).toBeLessThanOrEqual(view.width);
  expect(box.y + box.height).toBeLessThanOrEqual(view.height);
  const bar = page.locator(".bottom-nav");
  if (await bar.isVisible()) expect(box.y + box.height).toBeLessThanOrEqual((await bar.boundingBox())!.y);

  // At the very end it doesn't sit over the last row.
  await scrollTo(page, 100000);
  const last = (await page.getByRole("row").filter({ hasText: "Corner Stall 40" }).boundingBox())!;
  expect(last.y + last.height).toBeLessThanOrEqual((await floating.boundingBox())!.y);

  // It adds an expense like the header's.
  await floating.click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await expect(sheet).toBeVisible();
  await sheet.getByLabel("Amount").fill("4.20");
  await sheet.getByLabel("Paid to").fill("Kopi");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();

  // Back at the top the header's Add is the only one.
  await scrollTo(page, 0);
  await expect(floating).toHaveCount(0);
  await expect(header).toBeVisible();
  await expect(page.getByRole("button", { name: "Kopi", exact: true })).toBeVisible();
});
