import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Home as a Today page: what needs you across areas, the setup checklist, a trip that is on. Made-up data only.

test("Home reads top to bottom: the brief, what needs you, ask, then the cards at a glance", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  const order = ["Nexus", "Needs you", "Ask anything", "Get set up", "Money this month", "Portfolio today", "Next trip"];
  const tops: number[] = [];
  for (const name of order) {
    const region = page.getByRole("region", { name, exact: true });
    await expect(region).toBeVisible();
    tops.push((await region.boundingBox())!.y);
  }
  const [hero, needs, ask, setup, money, portfolio, trip] = tops;
  expect(hero).toBeLessThan(needs);
  // The brief points at the list directly below it.
  await expect(page.getByRole("region", { name: "Nexus" })).toContainText("2 things need you below.");
  if (page.viewportSize()!.width < 1024) {
    // One column on a phone: the cards at a glance come last.
    expect(needs).toBeLessThan(ask);
    expect(ask).toBeLessThan(setup);
    expect(setup).toBeLessThan(money);
    expect(money).toBeLessThan(portfolio);
    expect(portfolio).toBeLessThan(trip);
  } else {
    // Two columns on a wide screen: Needs you on the left and the cards on the right, side by side.
    const needsBox = (await page.getByRole("region", { name: "Needs you", exact: true }).boundingBox())!;
    const moneyBox = (await page.getByRole("region", { name: "Money this month" }).boundingBox())!;
    expect(moneyBox.x).toBeGreaterThan(needsBox.x + needsBox.width - 1);
    expect(money).toBeLessThanOrEqual(needs + 1);
    expect(needs).toBeLessThan(ask);
    expect(ask).toBeLessThan(setup);
  }
});

test("items from every area come in the server's order, the urgent ones marked, and Show all lists the rest", async ({ page }) => {
  await fakeApi(page, { todayItems: true });
  await page.goto("/");
  const needs = page.getByRole("region", { name: "Needs you" });
  const items = needs.getByRole("listitem");
  // Five at first: urgent, then about today, then the rest.
  await expect(items).toHaveCount(5);
  await expect(items.nth(0)).toContainText("NVDA reached its stop (182.40)");
  await expect(items.nth(1)).toContainText("Check in at Hotel Sakura today");
  await expect(items.nth(2)).toContainText("AMD −6.2% today");
  await expect(items.nth(3)).toContainText("2 receipts from email waiting for you");
  await expect(items.nth(4)).toContainText("Rent (SGD 1,800.00) due tomorrow");
  // The urgent ones carry a marker in words; the one about today says Today, quietly; the rest say neither.
  await expect(items.nth(0).getByText("Now", { exact: true })).toBeVisible();
  await expect(items.nth(1).getByText("Now", { exact: true })).toBeVisible();
  await expect(items.nth(2).getByText("Now", { exact: true })).toHaveCount(0);
  await expect(items.nth(2)).toContainText("Investment · Today");
  await expect(items.nth(1)).toContainText("Travel");
  await expect(items.nth(3)).not.toContainText("Today");
  await expect(items.nth(3).getByText("Now", { exact: true })).toHaveCount(0);
  await expect(items.nth(0).getByRole("link")).toHaveAttribute("href", "/investment/plans/p1");
  await expect(page.getByRole("region", { name: "Nexus" })).toContainText("8 things need you below.");

  const more = needs.getByRole("button", { name: "Show all (8)" });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.click();
  await expect(items).toHaveCount(8);
  await expect(items.nth(5)).toContainText("MSFT reports earnings tomorrow");
  await expect(items.nth(6)).toContainText("Flight SQ12 to Tokyo tomorrow 09:40");
  await expect(items.nth(7)).toContainText("3 things to sort before Tokyo");
  await expect(needs.getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
  await needs.getByRole("button", { name: "Show fewer" }).click();
  await expect(items).toHaveCount(5);
});

test("a short list has no Show all", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  const needs = page.getByRole("region", { name: "Needs you" });
  await expect(needs.getByRole("listitem")).toHaveCount(2);
  await expect(needs.getByRole("button", { name: /Show all/ })).toHaveCount(0);
});

test("the setup checklist shows what is left, and Hide puts it away for good", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/");
  const setup = page.getByRole("region", { name: "Get set up" });
  const steps = setup.getByRole("list", { name: "Setup steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(4);
  await expect(setup).toContainText("3 steps left.");
  // Done is ticked, in words too; each step left opens the page where it is done.
  await expect(steps.filter({ hasText: "Add your stocks" })).toContainText("Done");
  await expect(steps.filter({ hasText: "Add your stocks" }).getByRole("link")).toHaveCount(0);
  await expect(steps.filter({ hasText: "Set your payday" }).getByRole("link", { name: "Set up Set your payday" })).toHaveAttribute(
    "href",
    "/accounting/budgets",
  );
  await expect(steps.filter({ hasText: "Set a monthly budget" }).getByRole("link")).toHaveAttribute("href", "/accounting/budgets");
  // Receipts can also be asked of Nexus in the chat.
  await steps.filter({ hasText: "Get receipts" }).getByRole("button", { name: /Ask Nexus/ }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.locator(".msg-user").first()).toHaveText("Help me get my receipts in from email automatically");
  await chat.getByRole("button", { name: "Close chat" }).click();

  await setup.getByRole("button", { name: "Hide" }).click();
  await expect(setup).toHaveCount(0);
  expect(state.setup.dismissed).toBe(true);
  // It stays away.
  await page.reload();
  await expect(page.getByRole("region", { name: "Needs you" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Get set up" })).toHaveCount(0);
});

test("the setup checklist goes by itself once every step is done", async ({ page }) => {
  const state = await fakeApi(page);
  state.setup.items.forEach((i) => (i.done = true));
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Needs you" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Get set up" })).toHaveCount(0);
});

test("a trip that is on leads Home with its day, what is next, today's spending and the next booking", async ({ page }) => {
  await fakeApi(page, { tripMode: true });
  // Noon in Singapore (the user's zone) on the fake trip's day, so "what is next" doesn't
  // depend on when the test runs: in the minute after midnight there, 00:01 is still ahead.
  await page.clock.setFixedTime(new Date(`${new Date().toLocaleDateString("en-CA")}T04:00:00Z`));
  await page.goto("/");
  const trip = page.getByRole("region", { name: "Day 3 in Tokyo" });
  await expect(trip).toBeVisible();
  await expect(trip.getByRole("link", { name: "Open trip" })).toHaveAttribute("href", "/travel/trips/tripnow");
  // What is next today: the late plan (the early one is behind us).
  await expect(trip).toContainText("23:59 · Late ramen at Fuji");
  await expect(trip).not.toContainText("Early market walk");
  await expect(trip).toContainText("Spent today");
  await expect(trip).toContainText("SGD 42.00");
  await expect(trip).toContainText("SGD 380.00 a day left in your budget");
  await expect(trip).toContainText("Next booking");
  await expect(trip).toContainText("ZZ13 NRT → SIN");
  // It leads: above Needs you; the Next trip card gives way to it.
  const tripTop = (await trip.boundingBox())!.y;
  const needsTop = (await page.getByRole("region", { name: "Needs you" }).boundingBox())!.y;
  expect(tripTop).toBeLessThan(needsTop);
  await expect(page.getByRole("region", { name: "Next trip" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Nexus" })).toContainText("You're on day 3 of 6 in Tokyo.");
});

test("no trip card leads Home when the next trip has not started", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/travel");
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  await form.getByLabel("Where").fill("Tokyo");
  await form.getByLabel("From").fill("2026-11-10");
  await form.getByLabel("To").fill("2026-11-13");
  await form.getByRole("button", { name: "Add trip" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip1/);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Next trip" })).toContainText("Tokyo in 43 days");
  await expect(page.getByRole("region", { name: /^Day \d+ in/ })).toHaveCount(0);
  await expect(page.getByRole("region", { name: /^On now in/ })).toHaveCount(0);
});
