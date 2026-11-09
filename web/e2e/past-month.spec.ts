import { expect, type Page, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Today is Monday 2 November 2026 in Singapore: October is the month just closed, and September the one before.
// The fixed clock also stalls the figures' count-up part-way, so they are shown as they are.
test.use({ timezoneId: "Asia/Singapore", reducedMotion: "reduce" });

async function openAt(page: Page) {
  const state = await fakeApi(page, { today: "2026-11-02" });
  state.budgets.push({ id: "b1", category_id: null, limit: 2000, spent: 600 });
  state.budgets.push({ id: "b2", category_id: "food", limit: 1000, spent: 90 });
  await page.clock.setFixedTime(new Date("2026-11-02T04:00:00Z"));
  return state;
}

test("step back a month on the overview: that month's totals, categories and the comparison, and a category opens the ledger for it", async ({
  page,
}) => {
  await openAt(page);
  await page.goto("/accounting");
  await expect(page.getByRole("heading", { name: "This month", level: 1 })).toBeVisible();
  const picker = page.getByRole("group", { name: "Month", exact: true });
  await expect(picker).toContainText(/November.*2026/);
  await expect(picker.getByRole("button", { name: "Next month" })).toBeDisabled();
  await expect(page.getByRole("region", { name: "Latest" })).toBeVisible();

  await picker.getByRole("button", { name: "Previous month" }).click();
  await expect(page).toHaveURL(/\/accounting\?month=2026-10$/);
  await expect(page.getByRole("heading", { name: "Looking back", level: 1 })).toBeVisible();
  await expect(picker).toContainText(/October.*2026/);
  await expect(picker.getByRole("button", { name: "Next month" })).toBeEnabled();
  // The picker stays inside the screen on a phone.
  const box = (await picker.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);

  // That month's own figures, and how it compares with September.
  await expect(page.getByText(/^SGD.180\.00 less than September$/)).toBeVisible();
  await expect(page.locator(".overview-headline")).toHaveText(/^SGD.2,140\.00 spent in October$/);
  await expect(page.getByRole("region", { name: "Spent" })).toContainText(/SGD.2,140\.00/);
  await expect(page.getByRole("region", { name: "Received" })).toContainText(/SGD.5,200\.00/);
  await expect(page.getByRole("region", { name: "Saved" })).toContainText(/SGD.1,000\.00/);
  await expect(page.getByRole("region", { name: "Saved" })).toContainText("19% of income");
  const went = page.getByRole("region", { name: "Where it went" });
  await expect(went.getByRole("button", { name: /Dining Out: SGD.900\.00/ })).toBeVisible();
  await expect(went.getByRole("button", { name: /Uncategorised: SGD.1,240\.00/ })).toBeVisible();

  // What is only about now isn't there.
  for (const name of ["Latest", "Who owes you", "From Kaya"]) await expect(page.getByRole("region", { name })).toHaveCount(0);
  await expect(page.getByText(/Budget left|Left to spend|Still due/)).toHaveCount(0);

  // The budgets that month, against today's limits.
  const budgets = page.getByRole("region", { name: "Budgets" });
  await expect(budgets).toContainText("Against today's limits");
  await expect(budgets.getByRole("listitem").filter({ hasText: "Overall" })).toContainText(/Over by SGD.140\.00/);
  await expect(budgets.getByRole("listitem").filter({ hasText: "Dining Out" })).toContainText(/SGD.100\.00 under/);

  // A category opens the ledger for it, in that month.
  await went.getByRole("button", { name: /Dining Out: SGD.900\.00/ }).click();
  await went.getByRole("link", { name: /in the ledger/ }).click();
  await expect(page).toHaveURL(/\/accounting\/ledger\?view=out&start=2026-10-01&end=2026-10-31&category=food$/);
  await expect(page.getByRole("heading", { name: "Ledger", level: 1 })).toBeVisible();
  const chips = page.getByRole("group", { name: "Active filters" });
  await expect(chips.locator(".filter-chip").filter({ hasText: "Dining Out" })).toBeVisible();
  await expect(chips.locator(".filter-chip").filter({ hasText: "Last month" })).toBeVisible();
  await expect(chips.locator(".filter-chip").filter({ hasText: "Money out" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Filter, 3 active" })).toBeVisible();

  // Back lands on October again, not on this month.
  await page.goBack();
  await expect(page).toHaveURL(/\/accounting\?month=2026-10$/);
  await expect(picker).toContainText(/October.*2026/);
});

test("a bar in the Spending by month chart opens that month, and this month's brings the page back", async ({ page }) => {
  await openAt(page);
  await page.goto("/accounting");
  const chart = page.getByRole("region", { name: "Spending by month" });
  await expect(chart.getByRole("button")).toHaveCount(6);
  const september = chart.getByRole("button", { name: /^September 2026: SGD.2,320\.00/ });
  await expect(september).toHaveAttribute("aria-pressed", "false");
  await september.click();
  await expect(page).toHaveURL(/\/accounting\?month=2026-09$/);
  await expect(page.getByRole("group", { name: "Month", exact: true })).toContainText(/September.*2026/);
  await expect(page.getByText(/^SGD.665\.00 more than August$/)).toBeVisible();
  await expect(page.locator(".overview-headline")).toHaveText(/^SGD.2,320\.00 spent in September$/);
  // The picked month is marked, and the chart still shows the same six months ending now.
  await expect(september).toHaveAttribute("aria-pressed", "true");
  await expect(chart.getByRole("button")).toHaveCount(6);
  await expect(chart.locator(".month.picked")).toHaveCount(1);
  await expect(chart.locator(".legend")).toContainText("Month shown");
  await expect(chart.getByRole("button", { name: /^November 2026, so far/ })).toBeVisible();

  await chart.getByRole("button", { name: /^November 2026, so far/ }).click();
  await expect(page).toHaveURL(/\/accounting$/);
  await expect(page.getByRole("heading", { name: "This month", level: 1 })).toBeVisible();
});

test("an address that isn't a month, or is in the future, shows this month", async ({ page }) => {
  await openAt(page);
  for (const bad of ["2026-13", "2027-01", "soon"]) {
    await page.goto(`/accounting?month=${bad}`);
    await expect(page.getByRole("heading", { name: "This month", level: 1 })).toBeVisible();
    await expect(page.getByRole("group", { name: "Month", exact: true })).toContainText(/November.*2026/);
  }
});

test("the Budgets page has the same picker, and last month shows each budget's spend against its limit", async ({ page }) => {
  await openAt(page);
  await page.goto("/accounting/budgets");
  const picker = page.getByRole("group", { name: "Month", exact: true });
  await expect(picker).toContainText(/November.*2026/);
  await expect(page.getByRole("button", { name: "Change" }).first()).toBeVisible();

  await picker.getByRole("button", { name: "Previous month" }).click();
  await expect(page).toHaveURL(/\/accounting\/budgets\?month=2026-10$/);
  await expect(picker).toContainText(/October.*2026/);
  const budgets = page.getByRole("region", { name: "Budgets" });
  const overall = budgets.getByRole("listitem").filter({ hasText: "Overall" });
  await expect(overall).toContainText(/SGD.2,140\.00\s+of SGD.2,000\.00/);
  await expect(overall).toContainText(/107% used · Over by SGD.140\.00/);
  const dining = budgets.getByRole("listitem").filter({ hasText: "Dining Out" });
  await expect(dining).toContainText(/SGD.900\.00\s+of SGD.1,000\.00/);
  await expect(dining).toContainText(/90% used · SGD.100\.00 under/);
  // Read-only: limits are changed on this month.
  await expect(page.getByRole("button", { name: "Change" })).toHaveCount(0);
  await expect(page.getByRole("form", { name: "Add a budget" })).toHaveCount(0);

  await picker.getByRole("button", { name: "Next month" }).click();
  await expect(page).toHaveURL(/\/accounting\/budgets$/);
  await expect(page.getByRole("button", { name: "Change" }).first()).toBeVisible();
});
