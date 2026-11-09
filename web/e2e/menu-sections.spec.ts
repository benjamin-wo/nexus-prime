import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Invest and Travel are in the menu only when turned on (or used in chat). Their pages open by link either way.

// Set SHOT_DIR to also save a picture of each bar to look at.
const SHOTS = process.env.SHOT_DIR;

function menu(page: import("@playwright/test").Page, isMobile: boolean) {
  return page.getByRole("navigation", isMobile ? { name: "Main (mobile)" } : { name: "Main", exact: true });
}

test("Invest and Travel are not in the menu until they are on", async ({ page, isMobile }) => {
  await fakeApi(page, { showInvest: null, showTravel: null });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  const nav = menu(page, isMobile);
  await expect(nav.getByRole("link", { name: /^Money|^Money/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Invest/ })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: /Travel/ })).toHaveCount(0);
});

test("a section that was switched off stays out of the menu", async ({ page, isMobile }) => {
  await fakeApi(page, { showInvest: false, showTravel: true });
  await page.goto("/");
  const nav = menu(page, isMobile);
  await expect(nav.getByRole("link", { name: /Travel/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Invest/ })).toHaveCount(0);
});

test("a switch in Settings puts the tab in the menu, and turning it off takes it out", async ({ page, isMobile }) => {
  const state = await fakeApi(page, { showInvest: null, showTravel: null });
  await page.goto("/settings");
  const invest = page.getByRole("switch", { name: "Investing" });
  const travel = page.getByRole("switch", { name: "Travel" });
  await expect(page.getByText("Portfolio, watchlist and trade plans in the menu")).toBeVisible();
  await expect(page.getByText("Trips and trip research in the menu")).toBeVisible();
  await expect(invest).not.toBeChecked();
  await expect(travel).not.toBeChecked();
  const nav = menu(page, isMobile);
  await expect(nav.getByRole("link", { name: /Invest/ })).toHaveCount(0);

  await invest.click();
  await expect(invest).toBeChecked();
  await expect.poll(() => state.preferencePuts).toEqual([{ show_invest: true }]);
  await expect(nav.getByRole("link", { name: /Invest/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Travel/ })).toHaveCount(0);

  await travel.click();
  await expect(nav.getByRole("link", { name: /Travel/ })).toBeVisible();
  // Still there after a reload: it was saved, not just shown.
  await page.reload();
  await expect(page.getByRole("switch", { name: "Investing" })).toBeChecked();
  await expect(page.getByRole("switch", { name: "Travel" })).toBeChecked();

  await page.getByRole("switch", { name: "Investing" }).click();
  await expect(nav.getByRole("link", { name: /Invest/ })).toHaveCount(0);
  await expect.poll(() => state.preferencePuts).toEqual([{ show_invest: true }, { show_travel: true }, { show_invest: false }]);
});

test("a switch goes back and says why when the save fails", async ({ page }) => {
  await fakeApi(page, { showInvest: null, showTravel: null, preferencesFail: true });
  await page.goto("/settings");
  await page.getByRole("switch", { name: "Investing" }).click();
  await expect(page.getByRole("alert")).toContainText("Couldn't save that preference");
  await expect(page.getByRole("switch", { name: "Investing" })).not.toBeChecked();
});

test("a hidden section's page still opens by its address, with no tab marked", async ({ page, isMobile }) => {
  await fakeApi(page, { showInvest: null, showTravel: null });
  await page.goto("/investment/plans");
  await expect(page.getByRole("heading", { name: "Trade plans", level: 1 })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Investment pages" })).toBeVisible();
  const nav = menu(page, isMobile);
  await expect(nav.getByRole("link", { name: /Invest/ })).toHaveCount(0);
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(0);
  await page.goto("/travel");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(nav.getByRole("link", { name: /Travel/ })).toHaveCount(0);
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(0);
});

test.describe("the bottom bar on a phone", () => {
  test.skip(({ isMobile }) => !isMobile, "the bottom bar is a phone thing");

  for (const [name, invest, travel, count] of [
    ["3", null, null, 2],
    ["4", true, null, 3],
    ["5", true, true, 4],
  ] as const) {
    test(`keeps Kaya in the middle with ${name} items`, async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 700 });
      await fakeApi(page, { showInvest: invest, showTravel: travel });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      const bar = page.getByRole("navigation", { name: "Main (mobile)" });
      await expect(bar.getByRole("link")).toHaveCount(count);
      const centres = await page.evaluate(() => {
        const nav = document.querySelector("nav.bottom-nav")!.getBoundingClientRect();
        const chat = document.querySelector(".nexus-button.in-bar")!.getBoundingClientRect();
        return { bar: nav.left + nav.width / 2, chat: chat.left + chat.width / 2 };
      });
      expect(Math.abs(centres.chat - centres.bar)).toBeLessThan(1.5);
      // Nothing is cut off or crowded: every label is fully inside the bar and the links don't overlap.
      const boxes = await bar.getByRole("link").evaluateAll((els) =>
        els.map((el) => {
          const r = el.getBoundingClientRect();
          return { left: r.left, right: r.right, label: el.scrollWidth <= el.clientWidth + 1 };
        }),
      );
      for (const [i, b] of boxes.entries()) {
        expect(b.label).toBe(true);
        if (i > 0) expect(b.left).toBeGreaterThanOrEqual(boxes[i - 1].right - 0.5);
      }
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/bottom-bar-${name}-items.png`, clip: { x: 0, y: 700 - 110, width: 390, height: 110 } });
    });
  }
});
