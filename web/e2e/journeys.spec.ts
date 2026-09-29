import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// On failure, print what the page did: API calls, console errors and uncaught exceptions.
test.beforeEach(async ({ page }, info) => {
  const log: string[] = [];
  page.on(
    "request",
    (r) =>
      r.url().includes("/api/") && log.push(`request ${r.method()} ${r.url()}`),
  );
  page.on(
    "response",
    (r) =>
      r.url().includes("/api/") &&
      log.push(`response ${r.status()} ${r.url()}`),
  );
  page.on("requestfailed", (r) =>
    log.push(`failed ${r.url()} ${r.failure()?.errorText}`),
  );
  page.on(
    "console",
    (m) => m.type() === "error" && log.push(`console ${m.text()}`),
  );
  page.on("pageerror", (e) => log.push(`pageerror ${e.message}`));
  info.attach("page-log", { body: "", contentType: "text/plain" });
  (info as unknown as { pageLog: string[] }).pageLog = log;
});

test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus) return;
  const log = (info as unknown as { pageLog: string[] }).pageLog ?? [];
  const drawers = page.locator(".drawer");
  const drawer = (await drawers.count())
    ? await drawers.first().innerText()
    : "(no drawer)";
  console.log(
    `--- ${info.title} (${info.project.name})\n${log.join("\n")}\n--- drawer text:\n${drawer}`,
  );
});

test("signed-out visitors get the Telegram sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  await page.goto("/ledger");
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByText("Sign in with your Telegram account."),
  ).toBeVisible();
  const widget = page.locator(
    '.tg-login script[data-telegram-login="nexus_test_bot"]',
  );
  await expect(widget).toHaveAttribute(
    "data-auth-url",
    /\/api\/auth\/telegram\/callback$/,
  );
});

test("an invite link carries the invite through sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  await page.goto("/invite/tok123");
  await expect(page.getByText("You've been invited.")).toBeVisible();
  const widget = page.locator(".tg-login script");
  await expect(widget).toHaveAttribute(
    "data-auth-url",
    /callback\?invite=tok123$/,
  );
});

test("inside Telegram the Mini App signs in by itself", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  const launch = new URLSearchParams({
    tgWebAppData: "user=%7B%22id%22%3A1%7D&hash=ok",
    tgWebAppVersion: "8.0",
  });
  await page.goto(`/#${launch}`);
  await expect(page.getByRole("heading", { name: "This month" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe(""); // launch data not left in the URL
  const calls = await page.evaluate(
    () => (window as unknown as { tgCalls: string[] }).tgCalls,
  );
  expect(calls).toEqual(
    expect.arrayContaining(["ready", "expand", "header #09090b"]),
  );
});

test("a refused Mini App sign-in explains itself instead of showing the widget", async ({
  page,
}) => {
  await fakeApi(page, { signedIn: false });
  await page.goto(
    `/#${new URLSearchParams({ tgWebAppData: "user=%7B%22id%22%3A2%7D&hash=bad" })}`,
  );
  await expect(
    page.getByText("Sign-in failed. Close and reopen the app."),
  ).toBeVisible();
  await expect(page.locator(".tg-login script")).toHaveCount(0);
});

test("dashboard shows the month, categories and IOUs", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "This month" })).toBeVisible();
  await expect(page.getByLabel("Spent")).toContainText("37.40");
  await expect(page.getByLabel("Spent")).toContainText(
    "Includes USD 33.80, converted",
  );
  await expect(page.getByLabel("Received")).toContainText("4,200.00");
  await expect(
    page.getByRole("list", { name: "Spending by category" }),
  ).toContainText("Food & Drink");
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
  await expect(page.getByRole("status")).toContainText(
    "Deleted 1 transaction.",
  );
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
  await expect(chat.locator(".msg-bot").first()).toContainText(
    "Delete 2026-09-27",
  );
  await chat.getByRole("button", { name: "Confirm" }).click();
  await expect(chat.getByText("Deleted.")).toBeVisible();
  expect(state.lastPress).toBe("hitl:x:y");
  await expect(chat.getByRole("button", { name: "Confirm" })).toBeHidden();
});

test("the app never throws while chatting", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Open chat" }).first().click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  for (const message of ["one", "two"]) {
    await chat.getByLabel("Message").fill(message);
    await chat.getByRole("button", { name: "Send" }).click();
  }
  await expect(chat.locator(".msg-bot")).toHaveCount(2);
  expect(errors).toEqual([]);
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

test("set a budget, see how much is used, change and remove it", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("link", { name: "View budgets" }).click();
  await expect(page.getByRole("heading", { name: "Plan", level: 1 })).toBeVisible();
  const budgets = page.getByRole("region", { name: "Budgets" });
  await expect(budgets.getByText("No budgets yet. Add one below.")).toBeVisible();

  await budgets.getByLabel("Budget for").selectOption({ label: "Food & Drink" });
  await budgets.getByLabel("Monthly limit (SGD)").fill("100");
  await budgets.getByRole("button", { name: "Add budget" }).click();
  const meter = budgets.getByRole("meter", { name: "Food & Drink budget used" });
  await expect(meter).toHaveAttribute("aria-valuetext", "90% used");
  await expect(budgets.getByText(/90% used · SGD\s?10\.00 left/)).toBeVisible();

  await budgets.getByRole("button", { name: "Change" }).click();
  await budgets.getByLabel("Monthly limit (SGD)").first().fill("80");
  await budgets.getByRole("button", { name: "Save" }).click();
  await expect(budgets.getByText(/112% used · Over by SGD\s?10\.00/)).toBeVisible();

  await budgets.getByRole("button", { name: "Remove" }).click();
  await budgets.getByRole("button", { name: "Remove" }).click(); // confirm
  await expect(budgets.getByText("No budgets yet. Add one below.")).toBeVisible();
});

test("set when you're paid and your usual salary", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  const payday = page.getByRole("region", { name: "Payday" });
  const when = payday.getByRole("form", { name: "When you're paid" });
  await when.getByLabel("I'm paid on").selectOption({ label: "A day of the month" });
  await when.getByLabel("Day", { exact: true }).fill("25");
  await when.getByRole("button", { name: "Save" }).click();
  await expect(payday.getByRole("heading", { name: "Paid on the 25th of each month" })).toBeVisible();
  await expect(payday.getByText(/Next payday: In 25 days/)).toBeVisible();

  const usual = payday.getByRole("form", { name: "Usual salary" });
  await usual.getByLabel(/Usual salary/).fill("5000");
  await usual.getByRole("button", { name: "Save" }).click();
  await expect(payday.getByText(/SGD\s?5,000\.00/)).toBeVisible();

  await payday.getByRole("button", { name: "Remove" }).click();
  await payday.getByRole("button", { name: "Remove" }).click(); // confirm
  await expect(payday.getByRole("form", { name: "When you're paid" })).toBeVisible();
});

test("add a bill, snooze its reminders and stop tracking it", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  await expect(page.getByText("No bills yet. Add one below.")).toBeVisible();
  const form = page.getByRole("form", { name: "Add a bill" });
  await form.getByLabel("Bill").fill("Rent");
  await form.getByLabel("Next due").fill("2026-10-01");
  await form.getByLabel(/Amount/).fill("1800");
  await form.getByRole("button", { name: "Add bill" }).click();
  const bills = page.getByRole("region", { name: "Bills" });
  await expect(bills.getByRole("heading", { name: "Rent" })).toBeVisible();
  await expect(bills.getByText(/Due in 3 days, .* · Every month/)).toBeVisible();
  await expect(bills.getByText(/SGD\s?1,800\.00/)).toBeVisible();

  await bills.getByRole("button", { name: "Snooze" }).click();
  await expect(bills.getByText(/reminders snoozed/)).toBeVisible();
  await expect(bills.getByRole("button", { name: "Snooze" })).toBeDisabled();

  await bills.getByRole("button", { name: "Remove" }).click();
  await bills.getByRole("button", { name: "Remove" }).click(); // confirm
  await expect(page.getByText("No bills yet. Add one below.")).toBeVisible();
});

test("a category correction offers a rule, saved only when accepted", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/ledger");
  await page.getByRole("button", { name: "Grab", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await sheet.getByLabel("Category").selectOption({ label: "Transport" });
  await sheet.getByRole("button", { name: "Save" }).click();

  const offer = page.getByRole("status").filter({ hasText: "Always file “grab” under Transport?" });
  await expect(offer).toBeVisible();
  expect(state.rules).toEqual([]); // nothing until the user accepts
  await offer.getByRole("button", { name: "Save rule" }).click();
  await expect(page.getByText("Saved. New expenses from “grab” will be filed the same way.")).toBeVisible();

  await page.goto("/plan");
  const rules = page.getByRole("region", { name: "Category rules" });
  await expect(rules.getByRole("heading", { name: "“grab”" })).toBeVisible();
  await expect(rules.getByText("Added on 28 Sep 2026 when you filed “Grab” under Transport.")).toBeVisible();

  await rules.getByLabel("When it mentions").fill("Maxwell");
  await rules.getByLabel("File under").selectOption({ label: "Food & Drink" });
  await rules.getByRole("button", { name: "Save rule" }).click();
  await expect(rules.getByRole("heading", { name: "“maxwell”" })).toBeVisible();

  const grab = rules.getByRole("listitem").filter({ hasText: "“grab”" });
  await grab.getByRole("button", { name: "Remove" }).click();
  await grab.getByRole("button", { name: "Remove" }).click(); // confirm
  await expect(rules.getByRole("heading", { name: "“grab”" })).toHaveCount(0);
});

test("a kept receipt opens through the app's own link", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/ledger");
  const link = page.getByRole("link", { name: "Receipt" });
  await expect(link).toHaveCount(1);
  await expect(link).toHaveAttribute("href", "/api/transactions/t1/receipt");
  await page.getByRole("button", { name: "Maxwell Food Centre" }).click();
  await expect(page.getByRole("link", { name: "View receipt" })).toHaveAttribute(
    "href",
    "/api/transactions/t1/receipt",
  );
});

test("a Connect Gmail link explains Google's warning before sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false });
  await page.goto("/connect/gmail?t=good");
  await expect(page.getByRole("heading", { name: "Connect Gmail" })).toBeVisible();
  await expect(page.getByText("Telegram user …9165")).toBeVisible();
  await expect(page.getByText("Google hasn't verified this app")).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue to Google" })).toHaveAttribute(
    "href",
    "/api/email/gmail/start?t=good",
  );
  await page.goto("/connect/gmail?t=old");
  await expect(page.getByText("This link has expired or was already used.")).toBeVisible();
  await page.goto("/connect/gmail/done?ok=1");
  await expect(page.getByRole("heading", { name: "Gmail connected" })).toBeVisible();
});

test("email is out of sight until connected, then shows what happened to each email", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  await expect(page.getByRole("region", { name: "Category rules" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Email receipts" })).toHaveCount(0);

  await fakeApi(page, { emailConnected: true });
  await page.goto("/plan");
  const card = page.getByRole("region", { name: "Email receipts" });
  await expect(card.getByText("ann@gmail.com · 1 waiting for you")).toBeVisible();
  await card.getByRole("link", { name: "Open" }).click();

  const checked = page.getByRole("region", { name: "Checked emails" });
  const grab = checked.getByRole("listitem").filter({ hasText: "Grab" });
  await expect(grab.getByText("Waiting for you")).toBeVisible();
  await expect(checked.getByText("Not a receipt: promotion")).toBeVisible();
  await grab.getByRole("button", { name: "Log it" }).click();
  await expect(grab.getByText("Logged")).toBeVisible();
  await expect(grab.getByRole("link", { name: "In your ledger" })).toBeVisible();
});

test("a forwarding address shows as one, with a way to copy it", async ({ page }) => {
  await fakeApi(page, { forwarding: true });
  await page.goto("/email");
  const mailboxes = page.getByRole("region", { name: "Connected" });
  const row = mailboxes.getByRole("listitem").filter({ hasText: "nexus-3f9a2c7e1b04@agentmail.to" });
  await expect(row.getByText("Your forwarding address: forward receipts here.")).toBeVisible();
  await expect(row.getByText(/^Last email received/)).toBeVisible();
  await expect(row.getByRole("button", { name: "Copy address" })).toBeVisible();
  await row.getByRole("button", { name: "Disconnect" }).click();
  await expect(row.getByText("Stop using this address?")).toBeVisible();
});

test("subscriptions: a proposal is tracked on request, and a price change shows", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  const card = page.getByRole("region", { name: "Subscriptions" });
  await expect(card.getByText(/^About SGD\s17\.98 a month$/)).toBeVisible();
  const netflix = card.getByRole("list", { name: "Tracked subscriptions" }).getByRole("listitem");
  await expect(netflix.getByText(/^Was SGD\s15\.98 until/)).toBeVisible();
  const proposed = card.getByRole("list", { name: "Proposed subscriptions" });
  await proposed.getByRole("button", { name: "Track it" }).click();
  await expect(card.getByRole("list", { name: "Proposed subscriptions" })).toHaveCount(0);
  await expect(card.getByText(/^About SGD\s28\.96 a month$/)).toBeVisible();
});

test("telegram updates default to an end-of-day summary and can be changed", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  const card = page.getByRole("region", { name: "Telegram updates" });
  const choice = card.getByLabel("Send me my transactions");
  await expect(choice).toHaveValue("daily");
  await expect(card.getByText("You get a summary of your transactions once a day at 9pm.")).toBeVisible();
  await choice.selectOption("instant");
  await expect(card.getByText("You get a message for each transaction as it happens.")).toBeVisible();
  await page.reload();
  await expect(card.getByLabel("Send me my transactions")).toHaveValue("instant");
});

test("nothing spills sideways on a small phone", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await fakeApi(page, { emailConnected: true });
  for (const path of ["/", "/ledger", "/plan", "/email", "/connect/gmail?t=good"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const offenders = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      return [...document.querySelectorAll("body *")]
        .filter((el) => el.getBoundingClientRect().right > width + 1)
        .map(
          (el) =>
            `${el.tagName.toLowerCase()}.${(el as HTMLElement).className}`,
        );
    });
    expect(offenders, path).toEqual([]);
  }
});
