import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

test("the owner opens Model costs from Settings, sees the figures and switches to 7 days", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/settings");
  await page.getByRole("region", { name: "Model costs" }).getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/settings\/costs$/);
  await expect(page.getByRole("heading", { name: "Model costs", level: 1 })).toBeVisible();

  // The three headline tiles.
  const tile = (name: string) => page.getByRole("region", { name });
  await expect(tile("This month so far")).toContainText("US$12.35");
  await expect(tile("Projected for the month")).toContainText("US$18.20");
  await expect(tile("Per active user per month")).toContainText("US$3.10");

  // The chart: 30 bars, the latest day named until another is picked.
  await expect(page.getByRole("heading", { name: "Last 30 days", level: 2 })).toBeVisible();
  const bars = page.getByRole("list", { name: "Cost per day" }).getByRole("button");
  await expect(bars).toHaveCount(30);
  // The pointer may still rest where the Open button was, over a bar; move it off.
  await page.mouse.move(1, 1);
  await expect(page.locator(".cost-readout")).toContainText("Wed 28 Oct");
  await bars.nth(2).click();
  await expect(page.locator(".cost-readout")).toContainText("Thu 1 Oct");

  // Lists, with friendly names and an unknown key as it is.
  const features = page.getByRole("region", { name: "By feature" });
  await expect(features).toContainText("Chat");
  await expect(features).toContainText("Voice notes");
  await expect(features).toContainText("Memory");
  await expect(features).toContainText("Trip photos");
  await expect(features).toContainText("brief.daily");
  await expect(page.getByRole("region", { name: "By user" })).toContainText("Mia K.");
  const models = page.getByRole("region", { name: "By model" });
  await expect(models).toContainText("deepseek/deepseek-v4.1-flash");
  await expect(models).toContainText("3.4M in · 220k out");
  await expect(models).toContainText("US$0.0042");
  await expect(page.getByText("Exact costs reported by OpenRouter. Search and Maps APIs are billed separately and aren't included.")).toBeVisible();

  // No sideways scroll, at any width.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  // Seven days asks again with ?days=7.
  await page.getByRole("button", { name: "7 days" }).click();
  await expect(page.getByRole("heading", { name: "Last 7 days", level: 2 })).toBeVisible();
  await expect(bars).toHaveCount(7);
  await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  expect(state.costRequests).toEqual(["30", "7"]);

  await page.getByRole("link", { name: "Back to Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
});

test("a member has no Model costs link, and the page says it isn't available", async ({ page }) => {
  const state = await fakeApi(page, { member: true });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Time zone" })).toBeVisible();
  await expect(page.getByRole("link", { name: /model costs/i })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Model costs" })).toHaveCount(0);

  await page.goto("/settings/costs");
  await expect(page.getByText("Model costs aren't available.")).toBeVisible();
  await expect(page.getByRole("button", { name: "7 days" })).toHaveCount(0);
  // A member never even asks.
  expect(state.costRequests).toEqual([]);
});
