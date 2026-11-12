import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Home's one first-run guide, "Get started": four steps for a new person, ticking as they happen, gone when
// done or hidden, and never for a demo. Made-up data only.

const guide = (page: Page) => page.getByRole("region", { name: "Get started", exact: true });
const step = (page: Page, name: string) => guide(page).getByRole("listitem").filter({ hasText: name });
const needsYou = (page: Page) => page.getByRole("region", { name: "Needs you", exact: true });

/** Do something as the app would, through the fake API: a first expense and a first budget. */
const send = (page: Page, url: string, method: string, body: unknown) =>
  page.evaluate(
    ([u, m, b]) =>
      fetch(u as string, {
        method: m as string,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-1" },
        body: JSON.stringify(b),
      }),
    [url, method, body],
  );
const logOne = (page: Page) => send(page, "/api/transactions", "POST", { direction: "out", amount: "4.20", counterparty: "Kopi Stall" });
const budgetOne = (page: Page) => send(page, "/api/budgets", "PUT", { category_id: null, amount: "1500" });

const fresh = { setupDismissed: false, telegramLinked: false, noTransactions: true };

test("a brand-new person sees the guide with all four steps to do, above Needs you, and its actions work", async ({ page }) => {
  await fakeApi(page, fresh);
  await page.goto("/");
  await expect(guide(page)).toBeVisible();
  await expect(guide(page)).toContainText("0 of 4");
  const names = ["Connect Telegram", "Log your first expense", "Set a monthly budget", "Get receipts in automatically"];
  for (const name of names) await expect(step(page, name)).toContainText("To do");
  await expect(guide(page)).toContainText("Log in Telegram or the chat button; review here.");
  // It is the only first-run card: the old checklist is gone.
  await expect(page.getByRole("region", { name: "Get set up" })).toHaveCount(0);
  expect((await guide(page).boundingBox())!.y).toBeLessThan((await needsYou(page).boundingBox())!.y);

  // The bot is the one the app signs in with; a budget is set on the budgets page, email in Settings.
  await expect(step(page, "Connect Telegram").getByRole("link")).toHaveAttribute("href", "https://t.me/nexus_test_bot");
  await expect(step(page, "Set a monthly budget").getByRole("link")).toHaveAttribute("href", "/accounting/budgets");
  await expect(step(page, "Get receipts in automatically").getByRole("link")).toHaveAttribute("href", "/settings/email");

  // Logging one brings the person to the Just ask Nexus box.
  await step(page, "Log your first expense").getByRole("button").click();
  await expect(page.getByPlaceholder(/^Just ask Nexus… e.g./)).toBeFocused();

  // It stays compact and inside the screen.
  const box = (await guide(page).boundingBox())!;
  expect(box.height).toBeLessThan(400);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("the steps tick as they happen, and the guide goes by itself when all four are done", async ({ page }) => {
  const state = await fakeApi(page, { ...fresh, telegramLinked: true });
  await page.goto("/");
  await expect(guide(page)).toContainText("1 of 4");
  await expect(step(page, "Connect Telegram")).toContainText("Done");
  await expect(step(page, "Log your first expense")).toContainText("To do");

  await logOne(page);
  await page.reload();
  await expect(guide(page)).toContainText("2 of 4");
  await expect(step(page, "Log your first expense")).toContainText("Done");
  await expect(step(page, "Set a monthly budget")).toContainText("To do");

  await budgetOne(page);
  await page.reload();
  await expect(guide(page)).toContainText("3 of 4");
  await expect(step(page, "Set a monthly budget")).toContainText("Done");
  await expect(step(page, "Get receipts in automatically")).toContainText("To do");

  // Email connected: the last step.
  state.setup.items.find((i) => i.key === "receipts")!.done = true;
  await page.reload();
  await expect(needsYou(page)).toBeVisible();
  await expect(guide(page)).toHaveCount(0);
});

test("Hide puts the guide away for good, also after a reload", async ({ page }) => {
  const state = await fakeApi(page, fresh);
  await page.goto("/");
  await expect(guide(page)).toBeVisible();
  await guide(page).getByRole("button", { name: "Hide" }).click();
  await expect(guide(page)).toHaveCount(0);
  expect(state.setup.dismissed).toBe(true);
  await page.reload();
  await expect(needsYou(page)).toBeVisible();
  await expect(guide(page)).toHaveCount(0);
});

test("someone who put away the old checklist never sees it, and a demo never does either", async ({ page }) => {
  // The default: the same dismissal as the old checklist, already made.
  await fakeApi(page, { noTransactions: true, telegramLinked: false });
  await page.goto("/");
  await expect(needsYou(page)).toBeVisible();
  await expect(guide(page)).toHaveCount(0);
});

test("a demo never sees the guide", async ({ page }) => {
  await fakeApi(page, { demo: true, setupDismissed: false, noTransactions: true });
  await page.goto("/");
  await expect(needsYou(page)).toBeVisible();
  await expect(guide(page)).toHaveCount(0);
});
