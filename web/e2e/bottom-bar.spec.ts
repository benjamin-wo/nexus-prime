import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// On a phone the bottom bar is fixed over the page: whatever a page ends with must scroll clear of it.

const ROUTES = [
  "/",
  "/accounting",
  "/accounting/ledger",
  "/accounting/budgets",
  "/accounting/cashflow",
  "/investment",
  "/investment/watchlist",
  "/investment/plans",
  "/travel",
  "/settings",
  "/settings/notifications",
];

test.describe("the bottom bar never covers the end of a page", () => {
  test.skip(({ isMobile }) => !isMobile, "the fixed bottom bar is a phone thing");

  for (const width of [390, 320]) {
    for (const route of ROUTES) {
      test(`${route} at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 700 });
        await fakeApi(page, { research: true, tripMode: true, todayItems: true });
        await page.goto(route);
        await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
        await expect(page.getByText("Loading…")).toHaveCount(0);
        await page.waitForLoadState("networkidle");

        const bar = page.getByRole("navigation", { name: "Main (mobile)" });
        await expect(bar).toBeVisible();
        // Scroll the page's own scroll area to its end.
        await page.locator(".main-viewport").evaluate((el) => {
          el.scrollTop = el.scrollHeight;
        });
        await page.waitForTimeout(300);

        const { last, barTop } = await page.evaluate(() => {
          const nav = document.querySelector<HTMLElement>("nav.bottom-nav")!;
          const content = document.querySelector<HTMLElement>(".main-viewport .content")!;
          let last = 0;
          for (const el of content.querySelectorAll<HTMLElement>("*")) {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            const style = getComputedStyle(el);
            if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") continue;
            // Fixed things (the trip's + button, toasts) float over the page on purpose.
            let floating = false;
            for (let up: HTMLElement | null = el; up && up !== content; up = up.parentElement) {
              if (getComputedStyle(up).position === "fixed") floating = true;
            }
            if (floating) continue;
            last = Math.max(last, rect.bottom);
          }
          return { last, barTop: nav.getBoundingClientRect().top };
        });
        expect(last, `the page ends at ${last}px, the bar starts at ${barTop}px`).toBeGreaterThan(0);
        expect(last).toBeLessThanOrEqual(barTop);
        // And a little air above it, not a page ending flush against the bar.
        expect(barTop - last).toBeGreaterThanOrEqual(8);
      });
    }
  }
});
