import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// The app on a phone left in the background and brought back, and a page pulled down. Made-up data only.

/** What a WebView does when the app goes away and comes back: the page is hidden, then shown. */
async function leaveAndReturn(page: Page) {
  const set = (state: "hidden" | "visible") =>
    page.evaluate((s) => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => s });
      document.dispatchEvent(new Event("visibilitychange"));
    }, state);
  await set("hidden");
  await set("visible");
}

test("Home shows what changed elsewhere once the app is brought back", async ({ page }) => {
  const api = await fakeApi(page);
  await page.goto("/");
  const money = page.getByRole("region", { name: "Money this month" });
  await expect(money).toContainText("SGD 37.40");

  // An expense is edited on another device.
  api.txs.find((t) => t.id === "t2")!.amount.amount = "125.00";
  await leaveAndReturn(page);

  await expect(money).toContainText("SGD 137.40");
});

test("the Ledger follows too", async ({ page }) => {
  const api = await fakeApi(page);
  await page.goto("/accounting/ledger");
  await expect(page.getByRole("button", { name: "Grab", exact: true })).toBeVisible();
  api.txs.find((t) => t.id === "t2")!.counterparty = "Gojek";
  await leaveAndReturn(page);
  await expect(page.getByRole("button", { name: "Gojek", exact: true })).toBeVisible();
});

test("a page pulled down at the top refreshes", async ({ page, browserName }, info) => {
  test.skip(info.project.name !== "mobile" || browserName !== "chromium", "needs a touch screen");
  const api = await fakeApi(page);
  await page.goto("/");
  const money = page.getByRole("region", { name: "Money this month" });
  await expect(money).toContainText("SGD 37.40");
  api.txs.find((t) => t.id === "t2")!.amount.amount = "125.00";

  const cdp = await page.context().newCDPSession(page);
  const touch = (type: "touchStart" | "touchMove" | "touchEnd", y?: number) =>
    cdp.send("Input.dispatchTouchEvent", { type, touchPoints: y === undefined ? [] : [{ x: 180, y }] });
  await touch("touchStart", 200);
  for (let y = 210; y <= 400; y += 20) await touch("touchMove", y);
  await expect(page.locator(".ptr-spinner")).toHaveCSS("opacity", "1");
  await touch("touchEnd");

  await expect(money).toContainText("SGD 137.40");
  await expect(page.getByText("Updated")).toBeAttached();
});
