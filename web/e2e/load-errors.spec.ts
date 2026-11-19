import { expect, test, type Page, type Route } from "@playwright/test";

import { fakeApi } from "./fake-api";

// When a read fails, the page says so and offers Retry: it never reads as if there were nothing.
// A failed read is tried twice more (a few seconds) before the page gives up on it.
const GIVE_UP = { timeout: 20_000 };

const refuse = (route: Route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) });

/** Makes every GET of `path` (any query string) answer 500; the returned function lets it through again. */
async function failing(page: Page, path: string): Promise<() => Promise<void>> {
  const pattern = new RegExp(`/api${path}(\\?|$)`);
  await page.route(pattern, refuse);
  return () => page.unroute(pattern, refuse);
}

test("Home says what it could not load, never that nothing needs you, and Retry loads it", async ({ page }) => {
  await fakeApi(page);
  const feedUp = await failing(page, "/home");
  const summaryUp = await failing(page, "/summary");
  await page.goto("/");

  const needs = page.getByRole("region", { name: "Needs you", exact: true });
  await expect(needs.getByRole("alert")).toContainText("Couldn't load what needs you.", GIVE_UP);
  const money = page.getByRole("region", { name: "Money this month", exact: true });
  await expect(money.getByRole("alert")).toContainText("Couldn't load this month's spending.", GIVE_UP);
  const hero = page.getByRole("region", { name: "Nexus", exact: true });
  await expect(hero.getByRole("alert")).toContainText("Couldn't load this month's spending.");
  await expect(hero.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByText("Nothing needs you right now")).toHaveCount(0);
  await expect(money).not.toContainText("Loading…");

  await feedUp();
  await needs.getByRole("button", { name: "Retry" }).click();
  await expect(needs.getByRole("alert")).toHaveCount(0, GIVE_UP);
  await expect(needs.getByRole("listitem").first()).toBeVisible();

  await summaryUp();
  await money.getByRole("button", { name: "Retry" }).click();
  await expect(money.getByRole("alert")).toHaveCount(0, GIVE_UP);
  await expect(money.locator(".glance-figure")).toContainText("SGD");
  await expect(hero.getByRole("alert")).toHaveCount(0);
  await expect(hero.locator(".hero-value")).toContainText("SGD");
});

test("Overview says the totals could not be loaded, not that no spending was recorded", async ({ page }) => {
  await fakeApi(page);
  const up = await failing(page, "/summary");
  await page.goto("/accounting");

  const went = page.getByRole("region", { name: "Where it went", exact: true });
  await expect(went.getByRole("alert")).toContainText("Couldn't load where this month's money went.", GIVE_UP);
  await expect(page.getByText("No spending recorded")).toHaveCount(0);

  await up();
  await went.getByRole("button", { name: "Retry" }).click();
  await expect(went.getByRole("alert")).toHaveCount(0, GIVE_UP);
  await expect(went.getByRole("button", { name: /Dining Out/ })).toBeVisible();
});

test("the trips list says it could not be loaded, shows no Where to next, and Retry loads the trips", async ({ page }) => {
  await fakeApi(page);
  const up = await failing(page, "/travel/trips");
  await page.goto("/travel");

  const alert = page.getByRole("alert").filter({ hasText: "Couldn't load your trips." });
  await expect(alert).toBeVisible(GIVE_UP);
  await expect(page.getByRole("heading", { name: "Where to next?" })).toHaveCount(0);

  await up();
  await alert.getByRole("button", { name: "Retry" }).click();
  await expect(alert).toHaveCount(0, GIVE_UP);
  await expect(page.getByRole("heading", { name: "Where to next?" })).toBeVisible();
});
