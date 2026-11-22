import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Home as a Today page: For today across areas, a trip that is on. Made-up data only.

test("Home reads top to bottom: the headline, For today, then the cards at a glance", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  const order = ["This month", "For today", "Money this month", "Portfolio today", "Next trip"];
  const tops: number[] = [];
  for (const name of order) {
    const region = page.getByRole("region", { name, exact: true });
    await expect(region).toBeVisible();
    tops.push((await region.boundingBox())!.y);
  }
  const [hero, needs, money, portfolio, trip] = tops;
  expect(hero).toBeLessThan(needs);
  // No ask panel: the chat opens from the Nexus mark.
  await expect(page.getByRole("region", { name: "Just ask Nexus", exact: true })).toHaveCount(0);
  if (page.viewportSize()!.width < 1024) {
    // One column on a phone: the cards at a glance come last.
    expect(needs).toBeLessThan(money);
    expect(money).toBeLessThan(portfolio);
    expect(portfolio).toBeLessThan(trip);
  } else {
    // Two columns on a wide screen: the headline and For today on the left, the cards on the right, side by side.
    const needsBox = (await page.getByRole("region", { name: "For today", exact: true }).boundingBox())!;
    const moneyBox = (await page.getByRole("region", { name: "Money this month" }).boundingBox())!;
    expect(moneyBox.x).toBeGreaterThan(needsBox.x + needsBox.width - 1);
    expect(money).toBeLessThanOrEqual(hero + 1);
  }
});

test("items from every area come in the server's order, the urgent ones in warning, and See all lists the rest", async ({ page }) => {
  await fakeApi(page, { todayItems: true });
  await page.goto("/");
  const needs = page.getByRole("region", { name: "For today" });
  const items = needs.getByRole("listitem");
  // Five at first: urgent, then about today, then the rest.
  await expect(items).toHaveCount(5);
  await expect(items.nth(0)).toContainText("NVDA reached its stop (182.40)");
  await expect(items.nth(1)).toContainText("Check in at Hotel Sakura today");
  await expect(items.nth(2)).toContainText("AMD −6.2% today");
  await expect(items.nth(3)).toContainText("2 receipts from email waiting for you");
  await expect(items.nth(4)).toContainText("Rent (SGD 1,800.00) due tomorrow");
  // The urgent ones have their word in the warning colour; the one about today says Today, quietly; no badges.
  await expect(items.nth(0).locator(".today-word")).toHaveClass(/is-now/);
  await expect(items.nth(1).locator(".today-word")).toHaveClass(/is-now/);
  await expect(items.nth(2).locator(".today-word")).toHaveText("Today");
  await expect(items.nth(2)).toContainText("Investment");
  await expect(items.nth(1)).toContainText("Travel");
  await expect(items.nth(3).locator(".today-word")).toHaveText("Look");
  await expect(needs.locator(".badge, .row-icon")).toHaveCount(0);
  await expect(items.nth(0).getByRole("link")).toHaveAttribute("href", "/investment/plans/p1");

  const more = needs.getByRole("button", { name: "See all 8" });
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

test("a short list has no See all", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  const needs = page.getByRole("region", { name: "For today" });
  await expect(needs.getByRole("listitem")).toHaveCount(2);
  await expect(needs.getByRole("button", { name: /See all/ })).toHaveCount(0);
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
  await expect(trip).toContainText("Late ramen at Fuji");
  await expect(trip).toContainText("23:59");
  await expect(trip).not.toContainText("Early market walk");
  await expect(trip).toContainText("Spent today");
  await expect(trip).toContainText("SGD 42.00");
  await expect(trip).toContainText("SGD 380.00 a day left in your budget");
  await expect(trip).toContainText("Next booking");
  await expect(trip).toContainText("ZZ13 NRT → SIN");
  // It leads: above For today; the Next trip card gives way to it.
  const tripTop = (await trip.boundingBox())!.y;
  const needsTop = (await page.getByRole("region", { name: "For today" }).boundingBox())!.y;
  expect(tripTop).toBeLessThan(needsTop);
  await expect(page.getByRole("region", { name: "Next trip" })).toHaveCount(0);
  // What is next is also a row of For today, with the trip as its sub-line.
  await expect(page.getByRole("region", { name: "For today" })).toContainText("Tokyo, from 23:59");
});

test("during a trip the Plan tab is one day panel: pills first, each plan once, tonight's stay on a strip", async ({ page }) => {
  await fakeApi(page, { tripMode: true });
  await page.clock.setFixedTime(new Date(`${new Date().toLocaleDateString("en-CA")}T04:00:00Z`));
  await page.goto("/travel/trips/tripnow");
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  const pills = itinerary.getByRole("navigation", { name: "Days" });
  // Every day is on the page, side by side to swipe between: this is the one in view.
  const day = itinerary.getByRole("group", { name: /^Day 3 · .*, 3 of 6$/ });
  const plans = day.getByRole("list", { name: /^Day 3 · / });
  await expect(plans).toBeVisible();

  // The day once: each plan's name appears a single time on the page, there is no second list of them.
  for (const name of ["Early market walk", "Late ramen at Fuji"]) await expect(page.getByText(name, { exact: true })).toHaveCount(1);
  await expect(page.getByRole("list", { name: /^Plans for/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /^Day 3 of 6 · / })).toHaveCount(0); // today's reads "Today · …"
  await expect(day.getByRole("heading", { name: /^Today · Day 3 of 6 · / })).toBeVisible();
  await expect(day.locator(".day-weather")).toContainText("% rain");

  // Tonight's stay: one strip with directions and the address to copy; the reference is a tap away.
  const stay = day.locator(".day-stay");
  await expect(stay).toHaveCount(1);
  await expect(stay).toContainText("Hotel Kumo Shinjuku");
  await expect(stay.getByRole("link", { name: "Open Hotel Kumo Shinjuku in Maps" })).toHaveAttribute("href", /google\.com\/maps\/search\/.*Hotel%20Kumo%20Shinjuku/);
  await expect(stay.getByRole("button", { name: "Copy the address of Hotel Kumo Shinjuku" })).toBeVisible();
  await expect(stay.getByRole("button", { name: "Copy booking reference HK4471" })).toBeHidden();
  await stay.getByText("Address and booking").click();
  await expect(stay.getByRole("button", { name: "Copy booking reference HK4471" })).toBeVisible();

  // In the page's order: the stops and day pills come first, then the day, then its plans.
  const before = (a: string, b: string) =>
    page.evaluate(([x, y]) => Boolean(document.querySelector(x)!.compareDocumentPosition(document.querySelector(y)!) & Node.DOCUMENT_POSITION_FOLLOWING), [a, b]);
  await expect(pills).toBeVisible();
  const slide = ".day-slide:nth-child(3)";
  expect(await before(".day-strip", `${slide} .day-stay`)).toBe(true);
  expect(await before(".day-strip", `${slide} .timeline`)).toBe(true);
  expect(await before(`${slide} .day-stay`, `${slide} .timeline`)).toBe(true);
  expect(await before(".stops-row", ".day-strip")).toBe(true);
  const [strip, panel] = await Promise.all([pills.boundingBox(), plans.boundingBox()]);
  expect(strip!.y).toBeLessThan(panel!.y);

  // The page never scrolls sideways, even at the narrowest phone.
  await page.setViewportSize({ width: 320, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
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
