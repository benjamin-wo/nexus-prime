import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// On failure, print what the page did: API calls, console errors and uncaught exceptions.
test.beforeEach(async ({ page }, info) => {
  const log: string[] = [];
  page.on("request", (r) => r.url().includes("/api/") && log.push(`request ${r.method()} ${r.url()}`));
  page.on("response", (r) => r.url().includes("/api/") && log.push(`response ${r.status()} ${r.url()}`));
  page.on("requestfailed", (r) => log.push(`failed ${r.url()} ${r.failure()?.errorText}`));
  page.on("console", (m) => m.type() === "error" && log.push(`console ${m.text()}`));
  page.on("pageerror", (e) => log.push(`pageerror ${e.message}`));
  info.attach("page-log", { body: "", contentType: "text/plain" });
  (info as unknown as { pageLog: string[] }).pageLog = log;
});

test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus) return;
  const log = (info as unknown as { pageLog: string[] }).pageLog ?? [];
  const drawer = await page.locator(".drawer").innerText().catch(() => "(no drawer)");
  console.log(`--- ${info.title} (${info.project.name})\n${log.join("\n")}\n--- drawer text:\n${drawer}`);
});

test("signed-out visitors get the Telegram sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  await page.goto("/ledger");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Sign in with your Telegram account.")).toBeVisible();
  const widget = page.locator('.tg-login script[data-telegram-login="nexus_test_bot"]');
  await expect(widget).toHaveAttribute("data-auth-url", /\/api\/auth\/telegram\/callback$/);
});

test("an invite link carries the invite through sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  await page.goto("/invite/tok123");
  await expect(page.getByText("You've been invited.")).toBeVisible();
  const widget = page.locator(".tg-login script");
  await expect(widget).toHaveAttribute("data-auth-url", /callback\?invite=tok123$/);
});

test("dashboard shows the month, categories and IOUs", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "This month" })).toBeVisible();
  await expect(page.getByLabel("Spent")).toContainText("37.40");
  await expect(page.getByLabel("Received")).toContainText("4,200.00");
  await expect(page.getByRole("list", { name: "Spending by category" })).toContainText("Food & Drink");
  await expect(page.getByText("Ann")).toBeVisible();
});

test("log an expense from the entry sheet", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Log expense" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await expect(sheet.getByLabel("Amount")).toBeFocused();
  await sheet.getByLabel("Amount").fill("4.20");
  await sheet.getByLabel("Paid to").fill("Kopi");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await page.goto("/ledger");
  await expect(page.getByRole("button", { name: "Kopi" })).toBeVisible();
});

test("bulk delete asks first and can be undone", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/ledger");
  await page.getByRole("checkbox", { name: /Select Grab/ }).check();
  await page.getByRole("button", { name: "Delete selected" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Deleted 1 transaction.");
  await expect(page.getByRole("button", { name: "Grab" })).toBeHidden();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("button", { name: "Grab" })).toBeVisible();
});

test("chat asks before deleting and confirms", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Open chat" }).first().click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await chat.getByLabel("Message").fill("delete the grab ride");
  await chat.getByRole("button", { name: "Send" }).click();
  // Asserting on the whole bot message makes a failure print what was shown instead.
  await expect(chat.locator(".msg-bot").first()).toContainText("Delete 2026-09-27");
  await chat.getByRole("button", { name: "Confirm" }).click();
  await expect(chat.getByText("Deleted.")).toBeVisible();
  expect(state.lastPress).toBe("hitl:x:y");
  await expect(chat.getByRole("button", { name: "Confirm" })).toBeHidden();
});

test("export links carry the current filters", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/ledger");
  await page.getByRole("button", { name: "Money in" }).click();
  await expect(page.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
    "href",
    "/api/export.csv?direction=in",
  );
});

test("sign out returns to the sign-in page", async ({ page, isMobile }) => {
  test.skip(isMobile, "sign-out lives in the desktop rail");
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});
