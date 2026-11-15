import { expect, type Page, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Prime opens domain panels beside the chat (docs/adr/0001-prime-opens-domain-panels.md). On a wide screen with
// panels on, the chat is a fixed column on the left and the main area shows the panel stage; the fake API's
// stream sends the same panel.upsert events the server does. Made-up data only.
test.beforeEach(({}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the docked stage is a desktop layout; a phone keeps the drawer");
});
test.use({ timezoneId: "Asia/Singapore", reducedMotion: "reduce" });

async function open(page: Page, options: Parameters<typeof fakeApi>[1] = { panels: true }) {
  const state = await fakeApi(page, { today: "2026-11-02", ...options });
  state.budgets.push({ id: "b1", category_id: null, limit: 2000, spent: 600 });
  await page.clock.setFixedTime(new Date("2026-11-02T04:00:00Z"));
  await page.goto("/");
  return state;
}

async function ask(page: Page, text: string) {
  const chat = page.getByRole("region", { name: "Chat" });
  const answers = chat.getByText("Here is what I found.");
  const before = await answers.count();
  await chat.getByLabel("Message").fill(text);
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(answers).toHaveCount(before + 1);
}

test("the chat is a column on the left, with no drawer and no close button", async ({ page }) => {
  await open(page);
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Chat" })).toHaveCount(0);
  await expect(chat.getByRole("button", { name: "Close chat" })).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // Nothing takes focus on load.
  await expect(chat.getByLabel("Message")).not.toBeFocused();
});

test("asking about budgets opens the budgets panel beside the chat, with why it opened", async ({ page }) => {
  await open(page);
  await ask(page, "How are my budgets doing?");
  const card = page.getByRole("article", { name: "Budgets" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Opened because you asked about your budgets")).toBeVisible();
  await expect(card.getByText(/Budgets in November 2026 · as of \d/)).toBeVisible();
  await expect(card.getByText("30% used · SGD 1,400.00 under")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Budgets opened" })).toHaveCount(1);
  // Beside the chat, not over it.
  const chatBox = await page.getByRole("region", { name: "Chat" }).boundingBox();
  const cardBox = await card.boundingBox();
  expect(cardBox!.x).toBeGreaterThanOrEqual(chatBox!.x + chatBox!.width - 1);
  await expect(card.getByRole("link", { name: "Open in Money" })).toHaveAttribute("href", "/accounting/budgets?month=2026-11");
  // The stage came forward by itself; nothing took the focus from the message box.
  await expect(page.getByRole("button", { name: "Panels" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("region", { name: "Chat" }).getByLabel("Message")).not.toBeFocused();
});

test("a second question opens the month outlook large and folds budgets to a compact card", async ({ page }) => {
  await open(page);
  await ask(page, "How are my budgets doing?");
  await ask(page, "How does this month end up?");
  const outlook = page.getByRole("article", { name: "Month outlook" });
  await expect(outlook.getByText("Rent")).toBeVisible();
  await expect(outlook.getByText("Left by month end")).toBeVisible();
  const budgets = page.getByRole("article", { name: "Budgets" });
  await expect(budgets).toHaveClass(/panel-compact/);
  await expect(budgets.getByText("30% used", { exact: true })).toBeVisible();
  await expect(budgets.getByRole("link", { name: "Open in Money" })).toHaveCount(0);
});

test("pin keeps a panel large; dismiss moves one to Recently closed and Prime does not bring it back; Reopen does", async ({ page }) => {
  await open(page);
  await ask(page, "How are my budgets doing?");
  await ask(page, "How does this month end up?");

  // Pin the outlook; a third panel then opens beside it, compact.
  await page.getByRole("button", { name: "Pin Month outlook" }).click();
  await expect(page.getByRole("button", { name: "Unpin Month outlook" })).toBeVisible();
  await ask(page, "What did I spend?");
  await expect(page.getByRole("article", { name: "Transactions" })).toHaveClass(/panel-compact/);
  await expect(page.getByRole("article", { name: "Month outlook" })).toHaveClass(/panel-expanded/);

  // Dismiss budgets: it is listed as recently closed, and asking again does not reopen it.
  await page.getByRole("button", { name: "Dismiss Budgets" }).click();
  await expect(page.getByRole("article", { name: "Budgets" })).toHaveCount(0);
  const history = page.getByRole("region", { name: "Recently closed" });
  await expect(history).toContainText("Budgets");
  await ask(page, "And my budgets again?");
  await expect(page.getByRole("article", { name: "Budgets" })).toHaveCount(0);

  await history.getByRole("button", { name: /Reopen Budgets/ }).click();
  await expect(page.getByRole("article", { name: "Budgets" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recently closed" })).toHaveCount(0);
});

test("the page is one click away from the stage, and a link in a panel goes to its tab", async ({ page }) => {
  await open(page);
  await ask(page, "How are my budgets doing?");
  await page.getByRole("article", { name: "Budgets" }).getByRole("link", { name: "Open in Money" }).click();
  await expect(page).toHaveURL(/\/accounting\/budgets\?month=2026-11/);
  await expect(page.getByRole("heading", { name: "Budgets", level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Money" })).toHaveAttribute("aria-pressed", "true");
  // Back to the stage: the panel is still there.
  await page.getByRole("button", { name: "Panels" }).click();
  await expect(page.getByRole("article", { name: "Budgets" })).toBeVisible();
});

test("an empty stage says what it is for", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Panels" }).click();
  await expect(page.getByText("Ask Nexus about your money or a trip and the right view opens here.")).toBeVisible();
});

test("with panels off the chat is a drawer, as before", async ({ page }) => {
  await open(page, { panels: false });
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole("dialog", { name: "Chat" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Panels" })).toHaveCount(0);
});

test("a window narrower than the breakpoint keeps the drawer even with panels on", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  await open(page);
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole("dialog", { name: "Chat" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Panels" })).toHaveCount(0);
});
