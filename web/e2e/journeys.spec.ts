import { expect, type Locator, type Page, test } from "@playwright/test";

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
  await expect(page.getByRole("heading", { name: "Needs you" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe(""); // launch data not left in the URL
  const calls = await page.evaluate(
    () => (window as unknown as { tgCalls: string[] }).tgCalls,
  );
  expect(calls).toEqual(
    expect.arrayContaining(["ready", "expand", "header #f1f4f8"]),
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
  await page.goto("/accounting");
  await expect(page.getByRole("heading", { name: "This month" })).toBeVisible();
  await expect(page.getByLabel("Spent")).toContainText("37.40");
  await expect(page.getByLabel("Spent")).toContainText(
    "Includes USD 33.80, converted",
  );
  await expect(page.getByLabel("Received")).toContainText("4,200.00");
  await expect(
    page.getByRole("list", { name: "Spending by category" }),
  ).toContainText("Dining Out");
  await expect(page.getByText("Ann")).toBeVisible();
  // The latest few, and a line from Nexus offering to set a budget.
  await expect(page.getByRole("region", { name: "Latest" }).getByRole("listitem").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "From Nexus" })).toContainText("Set a monthly budget");
});

test("tap a spending category to see its transactions, then all of them in the ledger", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
  const split = page.getByRole("list", { name: "Spending by category" });
  const dining = split.getByRole("button", { name: /^Dining Out:/ });
  await expect(dining).toHaveAttribute("aria-expanded", "false");
  await dining.click();
  await expect(dining).toHaveAttribute("aria-expanded", "true");
  const list = page.getByRole("list", { name: "Dining Out transactions" });
  await expect(list).toContainText("Maxwell Food Centre");
  await expect(list).not.toContainText("Grab");
  // Uncategorised spending opens the same way.
  await split.getByRole("button", { name: /^Uncategorised:/ }).click();
  await expect(page.getByRole("list", { name: "Uncategorised transactions" })).toContainText("Grab");
  await expect(page.getByRole("list", { name: "Dining Out transactions" })).toHaveCount(0);

  await split.getByRole("button", { name: /^Dining Out:/ }).click();
  await page.getByRole("link", { name: "Open in the ledger" }).click();
  await expect(page).toHaveURL(/\/accounting\/ledger\?.*category=food/);
  const ledger = page.getByRole("region", { name: "Transactions" });
  await expect(ledger.getByText("Category Dining Out")).toBeVisible();
  await expect(ledger.getByRole("button", { name: "Money out" })).toHaveAttribute("aria-pressed", "true");
  await expect(ledger.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toBeVisible();
  await expect(ledger.getByRole("button", { name: "Grab", exact: true })).toHaveCount(0);
  await ledger.getByRole("button", { name: "Show every category, not just Dining Out" }).click();
  await expect(ledger.getByRole("button", { name: "Grab", exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/category=/);
});

test("log an expense from the entry sheet", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
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

test("bulk delete asks first and can be undone", async ({ page }, info) => {
  await fakeApi(page);
  await page.goto("/ledger");
  // On a phone the tick boxes wait for "Select".
  if (info.project.name === "mobile") {
    await expect(page.getByRole("checkbox", { name: /Select Grab/ })).toBeHidden();
    await page.getByRole("button", { name: "Select", exact: true }).click();
  }
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
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Ask Nexus" }).filter({ visible: true }).click();
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

test("the chat opens on the running conversation, from the web and Telegram", async ({ page }) => {
  await fakeApi(page, { chatHistory: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Ask Nexus" }).filter({ visible: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.locator(".msg-user").first()).toHaveText(/kopi 4\.20/);
  await expect(chat.locator(".msg-bot").first()).toContainText("Logged SGD 4.20 at Kopi.");
  await expect(chat.locator(".msg-bot").first()).toContainText("on Telegram");
  await expect(chat.locator(".msg-bot").last()).toHaveText("SGD 12.40 on Dining Out so far.");
  // Older messages are a tap away.
  await chat.getByRole("button", { name: "Earlier messages" }).click();
  await expect(chat.locator(".msg").first()).toHaveText("hello from last week");
  await expect(chat.getByRole("button", { name: "Earlier messages" })).toHaveCount(0);
  // New messages follow on.
  await chat.getByLabel("Message").fill("delete the grab ride");
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(chat.locator(".msg-user").last()).toHaveText("delete the grab ride");
});

test("the app never throws while chatting", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await fakeApi(page);
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Ask Nexus" }).filter({ visible: true }).click();
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
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("set a budget, see how much is used, change and remove it", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  await expect(page.getByRole("heading", { name: "Plan", level: 1 })).toBeVisible();
  const budgets = page.getByRole("region", { name: "Budgets" });
  await expect(budgets.getByText("No budgets yet. Add one below.")).toBeVisible();

  await budgets.getByLabel("Budget for").selectOption({ label: "Dining Out" });
  await budgets.getByLabel("Monthly limit (SGD)").fill("100");
  await budgets.getByRole("button", { name: "Add budget" }).click();
  const meter = budgets.getByRole("meter", { name: "Dining Out budget used" });
  await expect(meter).toHaveAttribute("aria-valuetext", "90% used");
  await expect(budgets.getByText(/90% used · SGD\s?10\.00 left/)).toBeVisible();
  // What went against it this month, under the budget.
  await budgets.getByRole("button", { name: "Transactions" }).click();
  await expect(budgets.getByRole("list", { name: "Dining Out transactions" })).toContainText("Maxwell Food Centre");
  await budgets.getByRole("button", { name: "Hide transactions" }).click();
  await expect(budgets.getByRole("list", { name: "Dining Out transactions" })).toHaveCount(0);

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
  await expect(page.getByText(/^Nothing scheduled yet/)).toBeVisible();
  const form = page.getByRole("form", { name: "Add a scheduled payment" });
  await expect(form.getByLabel("Counts as spending")).toBeChecked();
  await form.getByLabel("Name").fill("Rent");
  await form.getByLabel("Next due").fill("2026-10-01");
  await form.getByLabel(/Amount/).fill("1800");
  await form.getByRole("button", { name: "Add", exact: true }).click();
  const bills = page.getByRole("region", { name: "Scheduled payments" });
  await expect(bills.getByRole("heading", { name: "Rent" })).toBeVisible();
  await expect(bills.getByText(/Due in 3 days, .* · Every month/)).toBeVisible();
  await expect(bills.getByText(/SGD\s?1,800\.00/)).toBeVisible();

  await bills.getByRole("button", { name: "Snooze" }).click();
  await expect(bills.getByText(/reminders snoozed/)).toBeVisible();
  await expect(bills.getByRole("button", { name: "Snooze" })).toBeDisabled();

  await bills.getByRole("button", { name: "Remove" }).click();
  await bills.getByRole("button", { name: "Remove" }).click(); // confirm
  await expect(page.getByText(/^Nothing scheduled yet/)).toBeVisible();
});

test("a regular investment is named freely and marked done without counting as spending", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/plan");
  const form = page.getByRole("form", { name: "Add a scheduled payment" });
  await form.getByLabel("Name").fill("Index fund");
  await form.getByLabel("Next due").fill("2026-10-05");
  await form.getByLabel(/Amount/).fill("500");
  await form.getByLabel("Counts as spending").uncheck();
  await form.getByRole("button", { name: "Add", exact: true }).click();
  await expect.poll(() => state.bills[0]).toMatchObject({ name: "Index fund", spending: false });
  // The form goes back to spending for the next one.
  await expect(form.getByLabel("Counts as spending")).toBeChecked();

  const bills = page.getByRole("region", { name: "Scheduled payments" });
  await expect(bills.getByRole("heading", { name: /Index fund/ })).toContainText("Not spending");
  await expect(bills.getByRole("button", { name: "Mark paid" })).toHaveCount(0);
  await bills.getByRole("button", { name: "Mark done" }).click();
  await expect(bills.getByRole("status")).toContainText("doesn't count as spending, so nothing was logged");
});

test("mark a bill with no set amount paid and log what was paid", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  const form = page.getByRole("form", { name: "Add a scheduled payment" });
  await form.getByLabel("Name").fill("Electricity");
  await form.getByLabel("Next due").fill("2026-10-01");
  await form.getByRole("button", { name: "Add", exact: true }).click();
  const bills = page.getByRole("region", { name: "Scheduled payments" });
  await bills.getByRole("button", { name: "Mark paid" }).click();
  const paid = bills.getByRole("form", { name: "What you paid for Electricity" });
  await paid.getByLabel(/Paid/).fill("120");
  await paid.getByRole("button", { name: "Log and mark paid" }).click();
  await expect(bills.getByRole("status")).toContainText("logged SGD 120 in this month's spending");
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

  await page.goto("/settings");
  const rules = page.getByRole("region", { name: "Category rules" });
  await expect(rules.getByRole("heading", { name: "“grab”" })).toBeVisible();
  await expect(rules.getByText("Added on 28 Sep 2026 when you filed “Grab” under Transport.")).toBeVisible();

  await rules.getByLabel("When it mentions").fill("Maxwell");
  await rules.getByLabel("File under").selectOption({ label: "Dining Out" });
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
  await page.goto("/settings");
  await expect(page.getByRole("region", { name: "Category rules" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Email receipts" })).toHaveCount(0);

  await fakeApi(page, { emailConnected: true });
  await page.goto("/settings");
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

  // One the model couldn't read can still be logged with the amount it states, or skipped.
  const alert = checked.getByRole("listitem").filter({ hasText: "Card transaction alert" });
  await expect(alert.getByText("Couldn't be read: took too long to read")).toBeVisible();
  await expect(alert.getByRole("button", { name: "Log it" })).toBeVisible();
  await alert.getByRole("button", { name: "Skip" }).click();
  await expect(alert.getByText("Skipped: you skipped it")).toBeVisible();
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

test("cash flow shows logged and expected days, with detail on tap", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/cashflow");
  await expect(page.getByRole("heading", { name: "Cash flow", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "September 2026" })).toBeVisible();
  const days = page.getByRole("group", { name: "Days" });
  await expect(days.getByRole("button", { name: /^2026-09-25, net SGD\s4,200\.00/ })).toContainText("+4,200");
  await expect(days.getByRole("button", { name: /^2026-09-12, net -SGD\s42\.10/ })).toContainText("-42.1");
  await days.getByRole("button", { name: "2026-09-30, 1 expected" }).click();
  const detail = page.getByRole("region", { name: /Wednesday, (30 September|September 30)/ });
  await expect(detail.getByRole("listitem").filter({ hasText: "Rent" })).toContainText("Scheduled payment");
  await page.getByRole("button", { name: "Next month" }).click();
  await expect(page.getByRole("heading", { name: "October 2026" })).toBeVisible();
  await expect(days.getByRole("button", { name: "2026-10-12, 1 expected" })).toContainText("-17.98");
});

test("telegram updates default to an end-of-day summary and can be changed", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Telegram updates" });
  const choice = card.getByLabel("Send me my transactions");
  await expect(choice).toHaveValue("daily");
  await expect(card.getByText("You get a summary of your transactions once a day at 9pm.")).toBeVisible();
  await card.getByLabel("Daily summary at").fill("23:59");
  await expect(card.getByText("You get a summary of your transactions once a day at 11:59pm.")).toBeVisible();
  await choice.selectOption("instant");
  await expect(card.getByLabel("Daily summary at")).toBeHidden();
  await expect(card.getByText("You get a message for each transaction as it happens.")).toBeVisible();
  await page.reload();
  await expect(card.getByLabel("Send me my transactions")).toHaveValue("instant");
});

test("nothing spills sideways on a small phone", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await fakeApi(page, { emailConnected: true });
  const pages = ["/", "/accounting", "/ledger", "/plan", "/settings", "/email", "/cashflow", "/investment", "/investment/watchlist", "/investment/stocks/AMD", "/investment/plans", "/investment/plans/p1", "/travel", "/travel/research/rs1"];
  for (const path of [...pages, "/connect/gmail?t=good"]) {
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

test("add, rename and delete a category", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Categories" });
  const yours = card.getByRole("list", { name: "Your categories" });
  await expect(yours.getByRole("heading", { name: "Dining Out" })).toBeVisible();

  const add = card.getByRole("form", { name: "Add a category" });
  await add.getByLabel("New category").fill("Pets");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(yours.getByRole("heading", { name: "Pets" })).toBeVisible();

  await add.getByLabel("New category").fill("pets");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(card.getByRole("alert")).toContainText("already exists");

  const pets = yours.getByRole("listitem").filter({ hasText: "Pets" });
  await pets.getByRole("button", { name: "Rename" }).click();
  const rename = card.getByRole("form", { name: "Rename Pets" });
  await rename.getByRole("textbox").fill("Pet care");
  await rename.getByRole("button", { name: "Save" }).click();
  await expect(yours.getByRole("heading", { name: "Pet care" })).toBeVisible();

  const petCare = yours.getByRole("listitem").filter({ hasText: "Pet care" });
  await petCare.getByRole("button", { name: "Delete" }).click();
  await expect(petCare.getByLabel("Move Pet care expenses to")).toHaveValue("other");
  await petCare.getByRole("button", { name: "Keep" }).click();
  await expect(yours.getByRole("heading", { name: "Pet care" })).toBeVisible();
  await petCare.getByRole("button", { name: "Delete" }).click();
  await petCare.getByRole("button", { name: "Delete" }).click();
  await expect(yours.getByRole("heading", { name: "Pet care" })).toHaveCount(0);
});

test("Other and Income can't be deleted", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const yours = page.getByRole("region", { name: "Categories" }).getByRole("list", { name: "Your categories" });
  for (const name of ["Other", "Income"]) {
    const row = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name, exact: true }) });
    await expect(row.getByRole("button", { name: "Merge into…" })).toBeVisible();
    await expect(row.getByRole("button", { name: "Delete" })).toHaveCount(0);
  }
});

test("delete a category and find its expense under Other", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Categories" });
  const yours = card.getByRole("list", { name: "Your categories" });
  const dining = yours.getByRole("listitem").filter({ hasText: "Dining Out" });
  await dining.getByRole("button", { name: "Delete" }).click();
  await expect(dining.getByText("Delete Dining Out? Its expenses move to")).toBeVisible();
  await expect(dining.getByLabel("Move Dining Out expenses to")).toHaveValue("other");
  await dining.getByRole("button", { name: "Delete" }).click();
  await expect(yours.getByRole("heading", { name: "Dining Out" })).toHaveCount(0);

  await page.goto("/accounting/ledger?category=other");
  const ledger = page.getByRole("region", { name: "Transactions" });
  await expect(ledger.getByText("Category Other")).toBeVisible();
  await expect(ledger.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toBeVisible();
});

test("the cog opens Settings, and Plan keeps only planning", async ({ page }, info) => {
  await fakeApi(page);
  await page.goto("/plan");
  await expect(page.getByRole("region", { name: "Budgets" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Categories" })).toHaveCount(0);
  // On a phone Settings is the cog at the top of Home; on a wide screen, in the rail.
  if (info.project.name === "mobile") await page.getByRole("link", { name: "Home" }).filter({ visible: true }).click();
  await page.getByRole("link", { name: "Settings" }).filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  for (const name of ["Telegram updates", "Categories", "Category rules", "What Nexus remembers"])
    await expect(page.getByRole("region", { name })).toBeVisible();
});

test("import a bank statement: preview, tick, confirm, undo", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/ledger");
  await page.getByRole("link", { name: "Import statement" }).click();
  await expect(page.getByRole("heading", { name: "Import a statement", level: 1 })).toBeVisible();
  await page.getByLabel("Choose a CSV or PDF").setInputFiles({
    name: "sept.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Date,Description,Amount\n28/09/2026,Kopitiam,-4.20\n28/09/2026,Grab,-25.00\nsoon,Mystery,-1\n"),
  });
  const preview = page.getByRole("region", { name: "Check before importing" });
  await expect(preview.getByText("1 new · 1 possible duplicates")).toBeVisible();
  // New rows are ticked, a possible duplicate isn't, an unreadable row can't be.
  await expect(preview.getByRole("checkbox", { name: "Import Kopitiam" })).toBeChecked();
  await expect(preview.getByRole("checkbox", { name: "Import Grab" })).not.toBeChecked();
  await expect(preview.getByRole("checkbox", { name: "Import Mystery" })).toBeDisabled();
  await expect(preview.getByText(/Looks like/)).toBeVisible();
  await preview.getByRole("button", { name: "Import 1 transaction" }).click();
  await expect(page.getByRole("status").getByText("Imported 1 transaction.")).toBeVisible();
  const history = page.getByRole("region", { name: "Past imports" });
  await expect(history.getByText(/sept\.csv · 1 added/)).toBeVisible();
  await page.getByRole("button", { name: "Undo import" }).click();
  await expect(history.getByText("· undone")).toBeVisible();
});

test("import a locked PDF statement", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/import");
  await page.getByLabel("Choose a CSV or PDF").setInputFiles({
    name: "estatement.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 made up"),
  });
  const password = page.getByLabel("This PDF is locked. Its password");
  await password.fill("wrong");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await page.getByLabel("That password didn't open it. Try again").fill("secret");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  const preview = page.getByRole("region", { name: "Check before importing" });
  await expect(preview.getByRole("note")).toHaveText(/add up to the statement's own totals/);
  await expect(preview.getByRole("region", { name: "Columns" })).toHaveCount(0);
  await expect(preview.getByLabel("Name for this layout")).toHaveCount(0);
  await expect(preview.getByRole("checkbox", { name: "Import Beach Cafe" })).toBeChecked();
});

test("import a scanned PDF statement", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/import");
  await page.getByLabel("Choose a CSV or PDF").setInputFiles({
    name: "scanned-statement.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 scanned, made up"),
  });
  const preview = page.getByRole("region", { name: "Check before importing" });
  await expect(preview.getByRole("note")).toHaveText(/Read from a scan.*check each row/);
  await expect(preview.getByRole("checkbox", { name: "Import Night Market" })).toBeChecked();
});

test("see and forget what Nexus remembers", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "What Nexus remembers" });
  await expect(card.getByText("Ann is the user's sister.")).toBeVisible();
  await expect(card.getByText(/27 Sep|Sep 27/)).toBeVisible();
  await card.getByRole("button", { name: "Forget: Ann is the user's sister." }).click();
  await expect(card.getByText("Ann is the user's sister.")).toHaveCount(0);
  await card.getByRole("button", { name: "Forget everything" }).click();
  await card.getByRole("button", { name: "Forget all" }).click();
  await expect(card.getByText(/Nothing yet/)).toBeVisible();
});

test("Nexus sits in the middle of the bar on a phone, in the rail on a wide screen, and opens the chat", async ({ page }, info) => {
  await fakeApi(page);
  await page.goto("/plan");
  const where = info.project.name === "mobile" ? "Main (mobile)" : "Main";
  const nexus = page.getByRole("navigation", { name: where, exact: true }).getByRole("button", { name: "Ask Nexus" });
  await expect(nexus).toBeVisible();
  if (info.project.name === "mobile") {
    // Two tabs either side of it.
    const bar = page.getByRole("navigation", { name: "Main (mobile)" });
    await expect(bar.locator(":scope > *").nth(2)).toHaveAccessibleName("Ask Nexus");
  }
  await nexus.click();
  await expect(page.getByRole("dialog", { name: "Chat" })).toBeVisible();
});

test("merge one category into another from Settings", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Categories" });
  const yours = card.getByRole("list", { name: "Your categories" });
  await yours.getByRole("listitem").filter({ hasText: "Transport" }).getByRole("button", { name: "Merge into…" }).click();
  const form = card.getByRole("form", { name: "Merge Transport" });
  await expect(form.getByRole("button", { name: "Merge" })).toBeDisabled();
  await form.getByLabel("Move everything in Transport into").selectOption({ label: "Dining Out" });
  await form.getByRole("button", { name: "Merge" }).click();
  await expect(yours.getByRole("heading", { name: "Transport" })).toHaveCount(0);
});

test("mark that someone paid back what they owe", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
  const owed = page.getByRole("region", { name: "Who owes you" });
  await expect(owed.getByText("Ann")).toBeVisible();
  await owed.getByRole("button", { name: /Ann paid back/ }).click();
  await expect(owed.getByText("Nobody owes you anything.")).toBeVisible();
});

test("follow a split bill to its repayment and back", async ({ page }) => {
  await fakeApi(page, { splitBill: true });
  await page.goto("/ledger");
  await expect(page.getByText(/Split · your share SGD\s10\.00/)).toBeVisible();
  await expect(page.getByText(/Ann owes SGD\s10\.00/)).toBeVisible();
  await page.getByRole("button", { name: "Open the bill Wei Ming paid back: Hotpot Place" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByLabel("Paid to")).toHaveValue("Hotpot Place");
  await sheet.getByRole("button", { name: "Open Wei Ming's repayment" }).click();
  await expect(sheet.getByLabel("Received from")).toHaveValue("Wei Ming");
});

test("one payment recorded twice is merged, or kept as two", async ({ page }) => {
  await fakeApi(page, { twins: true });
  await page.goto("/ledger");
  const alert = page.getByRole("row").filter({ hasText: "Card alert" });
  await expect(alert.getByText(/^Possible duplicate of Grab Singapore/)).toBeVisible();
  await alert.getByRole("button", { name: "Merge" }).click();
  await expect(page.getByText(/^Merged into one: Grab Singapore/)).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Grab Singapore" })).toHaveCount(1);
  await expect(page.getByText(/^Possible duplicate/)).toHaveCount(0);
});

test("two payments flagged as one can be marked as two", async ({ page }) => {
  await fakeApi(page, { twins: true });
  await page.goto("/ledger");
  const receipt = page.getByRole("row").filter({ hasText: "Your Grab e-receipt" });
  await receipt.getByRole("button", { name: "Not a duplicate" }).click();
  await expect(page.getByText(/^Possible duplicate/)).toHaveCount(0);
  await expect(page.getByRole("row").filter({ hasText: "23.40" })).toHaveCount(2);
});

test("home is the front desk: what needs you, what's running, and each department", async ({ page }) => {
  const state = await fakeApi(page, { running: true });
  await page.goto("/");
  const needs = page.getByRole("region", { name: "Needs you" });
  await expect(needs.getByRole("link", { name: /2 receipts from email waiting for you/ })).toHaveAttribute(
    "href",
    "/accounting/email",
  );
  await expect(needs.getByRole("link", { name: /Rent \(SGD 1,800\.00\) due tomorrow/ })).toBeVisible();
  const working = page.getByRole("region", { name: "Working on" });
  await expect(working.getByText("Plan for NVDA")).toBeVisible();
  await expect(working.getByText("1/3 · reading the news")).toBeVisible();
  await working.getByRole("button", { name: "Cancel" }).click();
  await expect(working.getByText("Cancelled")).toBeVisible();
  expect(state.cancelled).toEqual(["r1"]);
  // Nexus opens with a brief from the user's own figures, and a few one-tap questions.
  const nexus = page.getByRole("region", { name: "Nexus" });
  await expect(nexus).toContainText("spent this month");
  await expect(nexus).toContainText("than by this time last month.");
  await expect(nexus).toContainText("2 things need you below.");
  // Six months of spending, this month so far last; the tiles compare and explain.
  const months = page.getByRole("list", { name: "Spending by month" });
  await expect(months.getByRole("listitem")).toHaveCount(6);
  await expect(months.getByRole("listitem").last()).toContainText("Sep so far");
  // A usual month, rather than the brief's comparison again.
  await expect(page.locator(".mini-tile").getByText("A usual month")).toBeVisible();
  await expect(page.getByText("Against last month")).toHaveCount(0);
  await expect(page.getByText("Biggest category")).toBeVisible();
  await expect(page.getByRole("region", { name: "Budgets this month" })).toContainText("No budgets yet");
});

test("a suggested question on home opens the chat with it", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Where did my money go this month?" }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.locator(".msg-user").first()).toHaveText("Where did my money go this month?");
});

test("asking on home opens the chat with the question", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("textbox", { name: "Ask Nexus" }).fill("how much on grab?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.locator(".msg-user").first()).toHaveText("how much on grab?");
  await expect(chat.locator(".msg-bot")).toHaveCount(1);
});

test("departments have their own pages, and old links still work", async ({ page, isMobile }) => {
  await fakeApi(page);
  await page.goto("/ledger");
  await expect(page).toHaveURL(/\/accounting\/ledger$/);
  const tabs = page.getByRole("navigation", { name: "Accounting pages" });
  await tabs.getByRole("link", { name: "Plan" }).click();
  await expect(page.getByRole("heading", { name: "Plan", level: 1 })).toBeVisible();
  const nav = page.getByRole("navigation", { name: isMobile ? "Main (mobile)" : "Main", exact: true });
  await nav.getByRole("link", { name: "Travel" }).click();
  await expect(page.getByRole("heading", { name: "Trips", level: 1 })).toBeVisible();
  await expect(page.getByText(/never books anything/)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Accounting pages" })).toHaveCount(0);
  await nav.getByRole("link", { name: "Home" }).click();
  await expect(page.getByRole("heading", { name: "Needs you" })).toBeVisible();
});

test("holdings from a screenshot are checked, saved, edited and removed", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/investment");
  await expect(page.getByText(/No holdings yet/)).toBeVisible();
  await page.getByLabel("Upload screenshot").setInputFiles({
    name: "portfolio.png",
    mimeType: "image/png",
    buffer: Buffer.from("not really a png"),
  });
  const draft = page.getByRole("region", { name: "From your screenshot" });
  await expect(draft.getByRole("list", { name: "Positions read" })).toContainText("NVDA · 10 at USD");
  await draft.getByRole("button", { name: "Save holdings" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved 2 positions.");
  expect(state.screenshots).toBe(1);
  const holdings = page.getByRole("region", { name: "Holdings" });
  await expect(holdings.getByRole("rowheader", { name: "NVDA" })).toBeVisible();
  // Valued at the last close where there's a price; the rest wait for one.
  await expect(holdings.getByRole("row").filter({ hasText: "NVDA" })).toContainText("130.25");
  await expect(holdings.getByLabel("Portfolio totals")).toContainText("SGD");
  await expect(holdings).toContainText("no price yet for AAPL");

  await holdings.getByRole("button", { name: "Edit NVDA" }).click();
  const edit = holdings.getByRole("form", { name: "Edit NVDA" });
  await edit.getByLabel("Shares").fill("12");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(holdings.getByRole("row").filter({ hasText: "NVDA" })).toContainText("12");
  await holdings.getByRole("button", { name: "Remove AAPL" }).click();
  await expect(holdings.getByRole("rowheader", { name: "AAPL" })).toHaveCount(0);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Portfolio" })).toContainText("SGD");
  await expect(page.getByRole("list", { name: "Largest holdings" })).toContainText("NVDA");
});

test("a sale is recorded with what it locked in, and dividends are expected", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/investment");
  await page.getByLabel("Upload screenshot").setInputFiles({ name: "p.png", mimeType: "image/png", buffer: Buffer.from("x") });
  await page.getByRole("region", { name: "From your screenshot" }).getByRole("button", { name: "Save holdings" }).click();

  const dividends = page.getByRole("region", { name: "Dividends" });
  await expect(dividends.getByRole("list", { name: "Expected dividends" })).toContainText("NVDA");
  await expect(dividends).toContainText("4 payments in the last year");

  const trades = page.getByRole("region", { name: "Trades" });
  await expect(trades).toContainText("No trades recorded yet");
  // Kept out of the way until asked for.
  await expect(trades.getByRole("form", { name: "Record a trade" })).toHaveCount(0);
  await trades.getByRole("button", { name: "Record a trade" }).click();
  const form = trades.getByRole("form", { name: "Record a trade" });
  await expect(form.getByLabel("Side")).toBeFocused();
  await form.getByLabel("Side").selectOption("sell");
  await form.getByLabel("Ticker").fill("NVDA");
  await form.getByLabel("Shares").fill("4");
  await form.getByLabel(/^Price/).fill("150");
  await form.getByLabel("Date").fill("2026-09-20");
  await form.getByRole("button", { name: "Record" }).click();
  const history = trades.getByRole("list", { name: "Trade history" });
  await expect(history).toContainText("Sold 4 NVDA");
  await expect(history).toContainText("+USD");
  expect(state.trades[0]).toMatchObject({ side: "sell", traded_on: "2026-09-20" });
  await expect(page.getByLabel("Portfolio totals")).toContainText("Locked in by sales");
  await expect(page.getByLabel("Portfolio totals")).toContainText("Total return");
});

test("a watched stock shows its levels, earnings date and news", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/investment/watchlist");
  await expect(page.getByText(/Nothing on your watchlist yet/)).toBeVisible();
  const form = page.getByRole("form", { name: "Watch a stock" });
  await form.getByLabel("Ticker").fill("amd");
  await form.getByRole("button", { name: "Watch" }).click();
  const list = page.getByRole("list", { name: "Watched stocks" });
  await expect(list).toContainText("AMD · USD 129.50");
  expect(state.watching).toEqual(["AMD"]);

  await list.getByRole("link", { name: "AMD" }).click();
  await expect(page).toHaveURL(/\/investment\/stocks\/AMD$/);
  await expect(page.getByRole("heading", { name: "AMD", level: 1 })).toBeVisible();
  const ladder = page.getByRole("list", { name: "Support and resistance" });
  await expect(ladder.getByRole("listitem")).toHaveText([/Resistance\s*131.00/, /Close\s*129.50/, /Support\s*121.00/, /Support\s*112.40/]);
  await expect(page.getByText("Momentum: stretched after a run up.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Next earnings" })).toContainText("after close");
  const story = page.getByRole("link", { name: "Acme rival opens a plant" });
  await expect(story).toHaveAttribute("rel", /noopener/);
  await expect(story).toHaveAttribute("target", "_blank");

  await page.getByRole("button", { name: "Stop watching" }).click();
  await expect(page.getByRole("button", { name: "Watch" })).toBeVisible();
  // The button flips before the request lands: wait for it.
  await expect.poll(() => state.watching).toEqual([]);
});

test("a research plan is started from a stock and read with its chart and sources", async ({ page }) => {
  const state = await fakeApi(page);
  state.watching = ["AMD"];
  await page.goto("/investment/stocks/AMD");
  // Likely ranges come from the stock's own volatility, with no view on direction.
  const ranges = page.getByRole("region", { name: "Likely range" });
  await expect(ranges).toContainText("not a forecast");
  const month = ranges.getByRole("row", { name: /1 month/ });
  await expect(month).toContainText("118.90 – 141.05");
  await expect(month).toContainText("112.50 – 149.07");
  // Its last year in numbers, worked out from its closes.
  const past = page.getByRole("region", { name: "Its last year" });
  await expect(past).toContainText("1 month +6.4%");
  await expect(past).toContainText("(about usual)");
  const card = page.getByRole("region", { name: "Research plan" });
  await card.getByRole("button", { name: "Make a plan" }).click();
  await expect(card.getByRole("status")).toContainText("Plan for AMD started");
  expect(state.planStarted).toBe(true);

  await page.goto("/investment/plans");
  // The track record counts finished plans; each plan shows how it's going.
  const record = page.getByRole("region", { name: "Track record" });
  await expect(record.getByLabel("Plan results")).toContainText("Hit target1");
  await expect(record).toContainText("Average result+4.6%");
  await expect(record.getByLabel("Plan results")).toContainText("Odds gave target 141%");
  await expect(record.getByLabel("Plan results")).toContainText("Reached it100%");
  await expect(page.getByRole("link", { name: /MSFT: Keep holding/ })).toContainText("🎯 Hit target +4.6%");
  await expect(page.getByRole("link", { name: /AMD: Wait for a dip to buy/ })).toContainText("⏳ Open, waiting to buy");
  await page.getByRole("link", { name: /AMD: Wait for a dip to buy/ }).click();
  await expect(page).toHaveURL(/\/investment\/plans\/p1$/);
  await expect(page.getByRole("heading", { name: "AMD plan", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Wait for a dip to buy", level: 2 })).toBeVisible();
  const going = page.getByRole("region", { name: "How it's going" });
  await expect(going).toContainText("you'll get a message when it dips into the buy zone");
  await going.getByLabel("Telegram alerts for this plan").uncheck();
  await expect.poll(() => state.planAlerts).toBe(false);
  // The game plan says when to buy, take profit, cut losses and review, with prices.
  const steps = page.getByRole("list", { name: "Game plan" }).getByRole("listitem");
  await expect(steps).toHaveCount(5);
  await expect(steps.nth(0)).toContainText("Buy124.75 to 125.65-3.0%");
  await expect(steps.nth(1)).toContainText("Take profit131.00 / 132.00+1.2%+1.9%");
  await expect(steps.nth(2)).toContainText("Cut losses122.95-5.1%");
  await expect(steps.nth(2)).toContainText("Sell if a day closes below 122.95");
  await expect(steps.nth(4)).toContainText("Earnings are on 08 Oct");
  await expect(page.getByText("What would prove it wrong:")).toBeVisible();
  // The odds replay the last year's moves: target 1, the stop or neither, about 100% together.
  const odds = page.getByRole("region", { name: "Odds" });
  await expect(odds.getByRole("img", { name: "Target 1 first 41%, Stop first 38%, Neither in time 21%" })).toBeVisible();
  const chances = odds.getByRole("list", { name: "Chance of each target" }).getByRole("listitem");
  await expect(chances.nth(0)).toContainText("Target 1 at 131.00 · typically 6 trading days41%");
  await expect(chances.nth(2)).toContainText("Stop at 122.95 before target 138%");
  await expect(odds).toContainText("not a forecast");
  await expect(page.getByRole("img", { name: /AMD daily closes over 60 days/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What could go wrong" })).toBeVisible();
  const cite = page.getByRole("link", { name: "[Wire]" });
  await expect(cite).toHaveAttribute("href", "https://news.example/1");
  await expect(cite).toHaveAttribute("rel", /noopener/);
});

/** Adds a trip from the Travel page with just where and when; the currency is found
 * from the place. ``more`` fills the optional fields. */
async function addTrip(page: Page, where: string, from: string, to: string, more?: (form: Locator) => Promise<void>) {
  await page.goto("/travel");
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  await form.getByLabel("Where").fill(where);
  await form.getByLabel("From").fill(from);
  await form.getByLabel("To").fill(to);
  await expect(form).toContainText("Spending in");
  if (more) {
    await form.getByText(/^Budget, who's going/).click();
    await more(form);
  }
  await form.getByRole("button", { name: "Add trip" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip1$/);
}


test("a trip is added and shows its spending, set-aside and settle-up", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/travel");
  await expect(page.getByText(/No trips yet/)).toBeVisible();
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  // Where and when is all it asks; the currency comes from the place, or is asked for.
  await form.getByLabel("Where").fill("Nowhere");
  await expect(form.getByRole("button", { name: "Add trip" })).toBeDisabled(); // still looking
  await expect(form.getByLabel("Currency there")).toBeVisible();
  await form.getByLabel("Where").fill("Tokyo");
  await expect(form).toContainText("Spending in JPY (Japan)");
  await expect(form.getByLabel("Currency there")).toHaveCount(0);
  await form.getByLabel("From").fill("2026-11-10");
  await form.getByLabel("To").fill("2026-11-19");
  await form.getByText(/^Budget, who's going/).click();
  await form.getByLabel(/^Budget/).fill("3000");
  await form.getByLabel(/^Set aside each payday/).fill("500");
  await form.getByLabel("Who's going").fill("Ann, Ben");
  await form.getByRole("button", { name: "Add a category" }).click();
  await form.getByLabel("Category").fill("Dining Out");
  await form.getByLabel("Planned amount").fill("600");
  await form.getByRole("button", { name: "Add trip" }).click();

  await expect(page).toHaveURL(/\/travel\/trips\/trip1$/);
  await expect(page.getByRole("heading", { name: "Tokyo", level: 1 })).toBeVisible();
  await expect.poll(() => state.trips[0]).toMatchObject({ currency: "JPY", companions: ["Ann", "Ben"], planned: { "Dining Out": { amount: "600.0000" } } });
  await expect(page.getByLabel("With Ann, Ben")).toBeVisible();
  // One tab is no choice, so Travel shows no tab bar.
  await expect(page.getByRole("navigation", { name: "Travel pages" })).toHaveCount(0);
  // The cover photo is credited as its licence asks, linking to its page.
  const credit = page.getByRole("link", { name: /Photo: A\. Photographer, CC BY-SA 4\.0/ });
  await expect(credit).toHaveAttribute("href", "https://commons.wikimedia.org/wiki/File:Example.jpg");
  await expect(credit).toHaveAttribute("rel", /noopener/);
  // Weeks out, the page opens on what's still to sort and the money in one bar.
  await expect(page.getByRole("region", { name: /Still to sort/ })).toContainText("9 nights without a place to stay");
  await expect(page.getByRole("region", { name: "Money" })).toContainText("of SGD 3,000.00");
  await expect(page.getByRole("region", { name: "Itinerary" })).toContainText("ZZ12 SIN → NRT");
  await expect(page.getByRole("region", { name: "Itinerary" })).toContainText("08:25 → 16:05");

  // The details of the money fold away until they're wanted.
  await page.getByRole("region", { name: "Money" }).getByRole("button", { name: "Details" }).click();
  const spending = page.getByRole("region", { name: "Trip spending" });
  await expect(spending).toContainText("SGD 818.00 of SGD 3,000.00");
  await expect(spending).toContainText("SGD 800.00 before the trip");
  // A category opens to the trip expenses behind it.
  await spending.getByRole("button", { name: /^Dining Out:/ }).click();
  await expect(spending.getByRole("list", { name: "Dining Out expenses" })).toContainText("Ichiran");
  await expect(spending.getByRole("list", { name: "Dining Out expenses" })).not.toContainText("Air ticket");
  await expect(page.getByRole("region", { name: "Setting money aside" })).toContainText("SGD 1,500.00 each payday would cover it");
  await expect(page.getByRole("region", { name: "Settle up" })).toContainText("Ann");
  await expect(spending).toContainText("SGD 820.00 not logged yet");
  const expenses = page.getByRole("region", { name: "Expenses" });
  await expect(expenses.getByText("added by hand")).toBeVisible();
  await expenses.getByRole("button", { name: "Take Air ticket off the trip" }).click();
  await expect(expenses.getByText("Air ticket")).toHaveCount(0);
  await expect.poll(() => state.tripItems).toEqual(["k1"]);

  await page.goto("/");
  const trip = page.getByRole("region", { name: "Tokyo" });
  await expect(trip).toContainText("In 43 days");
  await expect(page.getByRole("region", { name: "Nexus" })).toContainText("Tokyo trip is in 43 days");
  await page.goto("/travel");
  const coming = page.getByRole("region", { name: "Coming up" });
  await expect(coming.getByRole("link", { name: "Tokyo" })).toBeVisible();
  await expect(coming).toContainText("In 43 days");
  const loose = page.getByRole("region", { name: "Bookings not on a trip" });
  await expect(loose).toContainText("Hotel Sakura, 2 nights");
  await loose.getByLabel("Trip for Hotel Sakura, 2 nights").selectOption("trip1");
  await expect(loose).toHaveCount(0);
  await expect.poll(() => state.movedBookings).toEqual(["bk2:trip1"]);
});

test("trip research shows sourced prices and a budget, and becomes a trip", async ({ page }) => {
  const state = await fakeApi(page, { research: true });
  await page.goto("/travel");
  await page.getByRole("region", { name: "Research" }).getByRole("link", { name: "Research: Tokyo" }).click();
  await expect(page.getByRole("heading", { name: "Tokyo", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Budget" })).toContainText("About 4,602 to 6,760 SGD for 2");
  await expect(page.getByRole("region", { name: "Budget" })).toContainText("It fits your cash flow");
  const costs = page.getByRole("region", { name: "Costs" });
  await expect(costs).toContainText("about 72–135 SGD");
  await expect(costs.getByRole("link", { name: "[2]" })).toHaveAttribute("href", "https://flights.example.com/s");
  await expect(page.getByRole("region", { name: "Sources" }).getByRole("link", { name: "Tokyo guide" })).toHaveAttribute("rel", /noopener/);
  await page.getByRole("button", { name: "Make it a trip" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip9$/);
  await expect.poll(() => state.trips[0]).toMatchObject({ destination: "Tokyo", currency: "JPY" });
});

test("plans are added to a trip's itinerary by hand, day by day, and changed", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-19", (form) => form.getByLabel("Notes").fill("Pack an adapter"));
  await expect.poll(() => state.trips[0]).toMatchObject({ destination: "Tokyo", notes: "Pack an adapter" });

  // One + button, one sheet: here, the form for a plan on a day.
  await page.getByRole("button", { name: "Add to the trip" }).click();
  const sheet = page.getByRole("dialog", { name: "Add to Tokyo" });
  await sheet.getByRole("button", { name: /Fill in a form/ }).click();
  await page.getByRole("dialog", { name: "Fill in a form" }).getByRole("button", { name: "🗓️ Plan on a day" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const entry = page.getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Dinner at Sushi Ten");
  await entry.getByLabel("Day", { exact: true }).fill("2026-11-12");
  await entry.getByLabel("Time", { exact: true }).fill("19:00");
  await entry.getByLabel("Where", { exact: true }).fill("1-2-3 Ginza");
  await entry.getByRole("button", { name: "Add" }).click();
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("Dinner at Sushi Ten");
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("19:00");
  await expect(itinerary).toContainText("1-2-3 Ginza");
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Dinner at Sushi Ten", day: "2026-11-12", at: "19:00" });

  // Edit and Remove wait behind a small button, so the timeline reads cleanly.
  await expect(itinerary.getByRole("button", { name: "Edit Dinner at Sushi Ten" })).toHaveCount(0);
  await itinerary.getByRole("button", { name: "Change Dinner at Sushi Ten" }).click();
  await itinerary.getByRole("button", { name: "Edit Dinner at Sushi Ten" }).click();
  const edit = itinerary.getByRole("form", { name: "Change the entry" });
  await edit.getByLabel("Time", { exact: true }).fill("20:00");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("20:00");

  page.once("dialog", (d) => void d.accept());
  await itinerary.getByRole("button", { name: "Change Dinner at Sushi Ten" }).click();
  await itinerary.getByRole("button", { name: "Remove Dinner at Sushi Ten" }).click();
  await expect(itinerary).not.toContainText("Dinner at Sushi Ten");
  await expect.poll(() => state.plans).toEqual([]);

  // A night without a place to stay shows on its day, and Add there starts the stay.
  await itinerary.getByRole("button", { name: /^Add a place to stay on/ }).first().click();
  await page.getByRole("dialog", { name: "Type it" }).getByRole("button", { name: /Or fill in a form/ }).click();
  await expect(entry.getByLabel("Check in")).toHaveValue("2026-11-10");
  await entry.getByLabel("Hotel", { exact: true }).fill("Hotel Kawa");
  await entry.getByLabel("Check out").fill("2026-11-13");
  await entry.getByRole("button", { name: "Add" }).click();
  await expect(itinerary.getByText("Staying at Hotel Kawa")).toHaveCount(2); // the 11th and 12th
  await expect(itinerary.getByRole("list", { name: /^Day 4/ })).toContainText("Check out");
  await expect.poll(() => state.plans[0]).toMatchObject({ check_in: "2026-11-10", check_out: "2026-11-13" });
});

test("a booking is added by typing it, and Nexus asks before saving", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-15");
  await page.getByRole("region", { name: /Still to sort/ }).getByRole("button", { name: /^Add: .*nights without a place to stay/ }).click();
  const typeIt = page.getByRole("dialog", { name: "Type it" });
  const box = typeIt.getByLabel("Tell Nexus about a booking");
  await expect(box).toHaveAttribute("placeholder", /Hotel Ume 13 to 15 Nov/);
  await box.fill("Hotel Ume 13 to 15 Nov, ref 8812, booked on Agoda");
  await typeIt.getByRole("button", { name: "Send" }).click();
  // The trip goes with it, so "13 to 15 Nov" means this trip's.
  await expect.poll(() => state.chatSent.at(-1)).toMatch(/^For my Tokyo trip \(.+\), add this: Hotel Ume 13 to 15 Nov/);
  await expect(typeIt).toContainText("Add Hotel Ume, 2 nights");
  await typeIt.getByRole("button", { name: "Confirm" }).click();
  await expect(typeIt).toContainText("Added Hotel Ume to your Tokyo trip.");
  await expect.poll(() => state.lastPress).toBe("hitl:t:y");
  await page.keyboard.press("Escape");
  await expect(typeIt).toHaveCount(0);
});

test("a booking screenshot goes on the itinerary with its reference", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-19");
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  await expect(itinerary).toContainText("Booked on Acme Air · Ref ZK4P7Q"); // from email
  await page.getByRole("button", { name: "Add to the trip" }).click();
  await page.getByRole("dialog", { name: "Add to Tokyo" }).getByLabel("Screenshot or photo").setInputFiles({
    name: "booking.png",
    mimeType: "image/png",
    buffer: Buffer.from("made-up image bytes"),
  });
  const imported = page.getByRole("status", { name: "Imported from a screenshot" });
  await expect(imported).toContainText("Added to your Tokyo trip");
  await expect(imported).toContainText("Does everything look right?");
  await expect(itinerary).toContainText("Booked on Agoda · Ref 9876543210");
  await expect(itinerary.getByRole("button", { name: "Copy reference 9876543210" })).toBeVisible();
  await imported.getByRole("button", { name: "👍 Looks right" }).click();
  await expect(imported).toHaveCount(0);
  await expect.poll(() => state.plans[0]).toMatchObject({ hotel: "Hotel Kumo", reference: "9876543210" });
});

test("the trip overview: getting ready, places to visit, and labelled days", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  await expect.poll(() => state.trips[0]).toMatchObject({ currency: "KRW" });

  // Every field of the trip form fits inside it, dates included (iOS once pushed the
  // date pickers past the card's edge). Edit lives in the trip's menu.
  await page.getByRole("button", { name: "Trip options" }).click();
  await page.getByRole("menuitem", { name: "Edit trip" }).click();
  const edit = page.getByRole("form", { name: "Change the trip" });
  const overflow = await edit.evaluate((form) => {
    const edge = form.getBoundingClientRect().right + 0.5;
    return [...form.querySelectorAll("input, select, textarea")]
      .filter((el) => el.getBoundingClientRect().right > edge)
      .map((el) => el.getAttribute("type") ?? el.tagName);
  });
  expect(overflow).toEqual([]);
  await edit.getByRole("button", { name: "Cancel" }).click();

  const toSort = page.getByRole("region", { name: /Still to sort/ });
  await expect(toSort).toContainText("Still to sort · 2");
  await expect(toSort).toContainText("3 nights without a place to stay");
  await expect(toSort).toContainText("No budget yet");
  // Set opens the trip to add a budget.
  await toSort.getByRole("button", { name: "Set: No budget yet" }).click();
  await expect(page.getByRole("form", { name: "Change the trip" })).toBeVisible();
  await page.getByRole("form", { name: "Change the trip" }).getByRole("button", { name: "Cancel" }).click();

  // A place to visit, from the add sheet's form, kept without a day.
  await page.getByRole("button", { name: "Add to the trip" }).click();
  await page.getByRole("dialog", { name: "Add to Seoul" }).getByRole("button", { name: /Fill in a form/ }).click();
  await page.getByRole("button", { name: "📍 Place to visit" }).click();
  const entry = page.getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Namdaemun Market");
  await entry.getByLabel("Kind").fill("Shopping");
  await entry.getByRole("button", { name: "Add" }).click();
  const places = page.getByRole("list", { name: "Places to visit" });
  await expect(places).toContainText("Namdaemun Market");
  await expect(places).toContainText("Shopping");
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Namdaemun Market", day: null, category: "Shopping" });

  // Then given a day, it moves onto the itinerary.
  await places.getByRole("button", { name: "Plan a day for Namdaemun Market" }).click();
  const pick = places.getByRole("form", { name: "Change the entry" });
  await pick.getByLabel(/^Day/).fill("2026-11-11");
  await pick.getByRole("button", { name: "Save" }).click();
  await expect(places).not.toContainText("Namdaemun Market");
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  await expect(itinerary.getByRole("list", { name: /^Day 2/ })).toContainText("Namdaemun Market");

  // Days get a label, like the city.
  await expect(itinerary.getByRole("navigation", { name: "Days" }).getByRole("button")).toHaveCount(4);
  await itinerary.getByRole("button", { name: /Add a label for/ }).first().click();
  await itinerary.getByPlaceholder("City or plan, e.g. Busan").fill("Myeongdong");
  await itinerary.getByRole("button", { name: "Save" }).click();
  await expect(itinerary.getByRole("button", { name: "Change the label Myeongdong" })).toBeVisible();
  await expect.poll(() => state.trips[0]).toMatchObject({ day_labels: { "2026-11-10": "Myeongdong" } });
});

test("places from Google Maps: saved, linked, rated, and flagged when usually closed", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");

  // Found on Google Maps and saved as a place to visit, with its place kept.
  await page.getByRole("button", { name: "🔎 Find places or ideas" }).click();
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Google Maps results" });
  await expect(results).toContainText("Hanok Noodle Bar ★ 4.6 (2,310)");
  await expect.poll(() => state.placeSearches).toEqual(["noodles"]);
  // One word reads as a name: only Google Maps is asked; ideas are a tap away.
  await expect(page.getByRole("button", { name: /Ideas from guides and articles/ })).toBeVisible();
  expect(state.ideaSearches).toEqual([]);
  await results.getByRole("button", { name: "Save: Hanok Noodle Bar" }).click();
  const places = page.getByRole("list", { name: "Places to visit" });
  await expect(places).toContainText("Hanok Noodle Bar");
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Hanok Noodle Bar", category: "Noodle shop", place_id: "fakePlaceNoodle01" });
  await expect(places.getByLabel("Rated 4.6 out of 5 from 2310 ratings")).toBeVisible();

  // Its details: a summary, reviews credited to their authors, and Google Maps.
  await places.getByRole("button", { name: "Show details for Hanok Noodle Bar" }).click();
  const reviews = places.getByRole("list", { name: "Reviews of Hanok Noodle Bar" });
  await expect(reviews).toContainText("The broth is worth the queue.");
  await expect(reviews.getByRole("link", { name: "A. Reviewer" })).toHaveAttribute("rel", /noopener/);
  await expect(places).toContainText("From Google Maps");

  // Planned for a Thursday, when it's usually shut: the itinerary says so.
  await places.getByRole("button", { name: "Plan a day for Hanok Noodle Bar" }).click();
  const pick = places.getByRole("form", { name: "Change the entry" });
  await pick.getByLabel(/^Day/).fill("2026-11-12");
  await pick.getByRole("button", { name: "Save" }).click();
  await expect(places).not.toContainText("Hanok Noodle Bar");
  await expect.poll(() => state.plans[0]).toMatchObject({ day: "2026-11-12", place_id: "fakePlaceNoodle01" });
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  await expect(itinerary.getByRole("note")).toHaveText("⚠️ Usually closed on Thursdays");

  // A place added by hand is linked to Google Maps from its entry.
  await page.getByRole("button", { name: "Add to the trip" }).click();
  await page.getByRole("dialog", { name: "Add to Seoul" }).getByRole("button", { name: /Fill in a form/ }).click();
  await page.getByRole("button", { name: "📍 Place to visit" }).click();
  const entry = page.getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Namdaemun Market");
  await entry.getByRole("button", { name: "Add" }).click();
  await places.getByRole("button", { name: "Find Namdaemun Market on Google Maps" }).click();
  await expect(page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for")).toHaveValue("Namdaemun Market");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Link: Namdaemun Market" }).click();
  await expect(places.getByLabel("Rated 4.3 out of 5 from 18000 ratings")).toBeVisible();
  await expect.poll(() => state.plans[1]).toMatchObject({ name: "Namdaemun Market", place_id: "fakePlaceMarket01" });
});

test("where to next hands a place and a time to Nexus to research", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/travel");
  const where = page.getByRole("region", { name: "Where to next?" });
  await where.getByLabel("Where and when").fill("Hokkaido in February");
  await where.getByRole("button", { name: "Research it" }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.locator(".msg-user").last()).toHaveText("I'm thinking of a trip: Hokkaido in February. Can you research it?");
});

test("a trip's weather, packing list, cover photo and stop photos", async ({ page }) => {
  const state = await fakeApi(page);
  // Four days out: getting ready comes first.
  await addTrip(page, "Seoul", "2026-10-02", "2026-10-05");

  // Weather for the dates, credited to its source.
  const weather = page.getByRole("region", { name: "Weather in Seoul, Exampleland" });
  await expect(weather).toContainText("Typical for these dates, last 3 years");
  await expect(weather.getByRole("img", { name: "Light rain" })).toBeVisible();
  await expect(weather.getByRole("link", { name: "Weather data by Open-Meteo.com" })).toHaveAttribute("rel", /noopener/);

  // Packing: suggested, then ticked off and added to.
  const packing = page.getByRole("region", { name: "Packing list" });
  await packing.getByRole("button", { name: "✨ Suggest" }).click();
  await expect(packing.getByRole("list", { name: "Things to pack" })).toContainText("Umbrella or rain jacket");
  await packing.getByRole("checkbox", { name: "Passport" }).check();
  await expect(packing).toContainText("1 of 3 packed");
  await packing.getByLabel("Thing to pack").fill("Swimsuit");
  await packing.getByRole("button", { name: "Add", exact: true }).click();
  await expect(packing).toContainText("1 of 4 packed");
  await expect.poll(() => state.trips[0].packing).toEqual([
    { text: "Passport", done: true },
    { text: "Travel adapter", done: false },
    { text: "Umbrella or rain jacket", done: false },
    { text: "Swimsuit", done: false },
  ]);
  await packing.getByRole("button", { name: "Remove Swimsuit" }).click();
  await expect(packing).toContainText("1 of 3 packed");

  // The cover photo, from the trip's menu: none other to switch to yet, but it can be hidden.
  await page.getByRole("button", { name: "Trip options" }).click();
  await page.getByRole("menuitem", { name: "Another photo" }).click();
  await expect(page.getByRole("menu", { name: "Trip options" })).toContainText("no other photo of this place yet");
  await page.getByRole("menuitem", { name: "No photo" }).click();
  await expect.poll(() => state.photoChoices).toEqual(["next", "off"]);

  // A place found on Google Maps from the add sheet shows its photo, credited, on the itinerary.
  await page.getByRole("button", { name: "Add to the trip" }).click();
  await page.getByRole("dialog", { name: "Add to Seoul" }).getByRole("button", { name: /Find a place/ }).click();
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("list", { name: "Google Maps results" }).getByRole("button", { name: "Save: Hanok Noodle Bar" }).click();
  await page.keyboard.press("Escape");
  const places = page.getByRole("list", { name: "Places to visit" });
  await places.getByRole("button", { name: "Plan a day for Hanok Noodle Bar" }).click();
  const pick = places.getByRole("form", { name: "Change the entry" });
  await pick.getByLabel(/^Day/).fill("2026-10-03");
  await pick.getByRole("button", { name: "Save" }).click();
  // The timeline is folded in the last week; it opens on a tap. The photo stays
  // folded too, until the plan's details are opened.
  await page.getByText(/^Itinerary · 4 days/).click();
  const fold = page.locator(".itinerary-fold");
  await expect(fold.getByRole("img", { name: "Hanok Noodle Bar" })).toHaveCount(0);
  await fold.getByRole("button", { name: "Show details for Hanok Noodle Bar" }).click();
  await expect(fold.getByRole("img", { name: "Hanok Noodle Bar" })).toBeVisible();
  await expect(page.locator(".itinerary-fold").getByRole("link", { name: "Photo by A. Photographer, Google Maps" })).toHaveAttribute("href", "https://maps.example/u/2");
});

test("the entry sheet suggests where you usually pay, and fills the usual", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Log expense" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  // The most frequent places are a tap away before anything is typed.
  await expect(sheet.getByRole("group", { name: "Frequent" }).getByRole("button", { name: /^Maxwell Food Centre/ })).toBeVisible();
  // Typing part of a name suggests it, with the usual amount and category.
  await sheet.getByLabel("Paid to").fill("maxw");
  const list = sheet.getByRole("listbox", { name: "Past merchants" });
  await expect(list.getByRole("option")).toHaveCount(1);
  await expect(list).toContainText("SGD 12.40 · Dining Out");
  await sheet.getByLabel("Paid to").press("ArrowDown");
  await sheet.getByLabel("Paid to").press("Enter");
  await expect(list).toBeHidden();
  await expect(sheet.getByLabel("Paid to")).toHaveValue("Maxwell Food Centre");
  await expect(sheet.getByLabel("Amount")).toHaveValue("12.4");
  await expect(sheet.getByLabel("Category")).toHaveValue("food");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await expect.poll(() => state.txs[0]).toMatchObject({ counterparty: "Maxwell Food Centre", category_id: "food", amount: { amount: "12.4000" } });

  // A typed amount is never replaced; Escape closes the list, not the sheet.
  await page.getByRole("button", { name: "Log expense" }).click();
  await sheet.getByLabel("Amount").fill("9");
  await sheet.getByLabel("Paid to").fill("gra");
  await sheet.getByRole("option", { name: /^Grab/ }).click();
  await expect(sheet.getByLabel("Amount")).toHaveValue("9");
  await sheet.getByLabel("Paid to").fill("gr");
  await expect(sheet.getByRole("listbox", { name: "Past merchants" })).toBeVisible();
  await sheet.getByLabel("Paid to").press("Escape");
  await expect(sheet.getByRole("listbox", { name: "Past merchants" })).toBeHidden();
  await expect(sheet).toBeVisible();
});

test("a trip's day on one screen: tonight's stay, the day's plans, addresses and references", async ({ page }) => {
  const state = await fakeApi(page);
  // On now (the made-up today is 28 Sep): the page opens on today.
  await addTrip(page, "Tokyo", "2026-09-25", "2026-09-28");
  const entry = { trip_id: "trip1", provider: null, segments: [], name: null, day: null, at: null, note: null, cost: null, booked_via: null, category: null, place_id: null, scheduled: true, logged: false, manual: true };
  state.plans.push(
    { ...entry, id: "pl1", kind: "hotel", title: "Hotel Kumo", hotel: "Hotel Kumo", starts: "2026-09-25", ends: "2026-09-28", check_in: "2026-09-25", check_out: "2026-09-28", address: "1-2-3 Example-cho, Tokyo", reference: "HK55821", booked_via: "Agoda" },
    { ...entry, id: "pl2", kind: "activity", title: "Fish market breakfast", name: "Fish market breakfast", starts: "2026-09-26", ends: "2026-09-26", day: "2026-09-26", at: "07:30", address: "4-5 Market St, Tokyo", hotel: null, check_in: null, check_out: null, reference: null, note: "Go early" },
  );
  await page.reload();

  // Spending first, then the day. No tabs.
  await expect(page.getByRole("tablist")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Spent so far" })).toContainText("Log what you spend on Telegram");
  const view = page.getByRole("region", { name: /September 25/ });
  await expect(view).toContainText("Day 1 of 4");
  const plans = view.getByRole("list", { name: /Plans for/ });
  await expect(plans).toContainText("Check in");
  await expect(view).toContainText("Tonight");
  await expect(view.getByRole("button", { name: "Copy booking reference HK55821" }).first()).toBeVisible();
  await expect(view).toContainText("Tomorrow first: Fish market breakfast at 07:30");
  await expect(view.getByRole("button", { name: "Day before" })).toBeDisabled();

  // The next day: the plan with its address and a link to directions.
  await view.getByRole("button", { name: "Day after" }).click();
  const day2 = page.getByRole("region", { name: /September 26/ });
  await expect(day2).toContainText("Day 2 of 4");
  await expect(day2).toContainText("Go early");
  await expect(day2.getByRole("link", { name: "Open Fish market breakfast in Maps" })).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=Fish%20market%20breakfast%2C%204-5%20Market%20St%2C%20Tokyo",
  );
  await expect(day2.getByRole("button", { name: "Copy the address of Hotel Kumo" })).toBeVisible();

  // The last day: checking out, nowhere to sleep needed.
  await day2.getByRole("button", { name: "Day after" }).click();
  await page.getByRole("region", { name: /September 27/ }).getByRole("button", { name: "Day after" }).click();
  const last = page.getByRole("region", { name: /September 28/ });
  await expect(last.getByRole("list", { name: /Plans for/ })).toContainText("Check out");
  await expect(last).toContainText("Last day of the trip.");

  // The rest of the trip is one tap away.
  await expect(page.getByText("The whole trip, day by day")).toBeVisible();
});

test("a trip's plan is shared by a read-only link that shows no money, references or notes", async ({ page }) => {
  const state = await fakeApi(page);
  page.on("dialog", (d) => void d.accept());
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  const entry = { trip_id: "trip1", provider: null, segments: [], name: null, day: null, at: null, category: null, place_id: null, scheduled: true, logged: false, manual: true };
  state.plans.push(
    { ...entry, id: "pl1", kind: "hotel", title: "Hotel Kumo", hotel: "Hotel Kumo", starts: "2026-11-10", ends: "2026-11-12", check_in: "2026-11-10", check_out: "2026-11-12", address: "1-2-3 Example-cho, Tokyo", reference: "HK55821", booked_via: "Agoda", note: null, cost: { amount: "64500.0000", currency: "JPY" } },
    { ...entry, id: "pl2", kind: "activity", title: "Fish market breakfast", name: "Fish market breakfast", starts: "2026-11-11", ends: "2026-11-11", day: "2026-11-11", at: "07:30", address: "4-5 Market St, Tokyo", hotel: null, check_in: null, check_out: null, reference: null, booked_via: null, note: "Somewhere secret", cost: null },
  );
  state.trips[0] = { ...state.trips[0], day_labels: { "2026-11-11": "Tsukiji" } };
  await page.reload();

  // The sheet says what's shown and what isn't, and makes the link only when asked.
  await page.getByRole("button", { name: "Share the plan" }).click();
  const sheet = page.getByRole("dialog", { name: "Share the plan" });
  await expect(sheet.getByRole("list", { name: "Kept private" })).toContainText("Booking references");
  await expect(sheet.getByLabel("The trip's link")).toHaveCount(0);
  await sheet.getByRole("button", { name: "Create a link" }).click();
  const link = sheet.getByLabel("The trip's link");
  await expect(link).toHaveValue(/\/shared\/fakeShare0001x+$/);

  // A new link replaces the old one; stopping turns it off.
  await sheet.getByRole("button", { name: "Make a new link" }).click();
  await expect(link).toHaveValue(/\/shared\/fakeShare0002x+$/);
  await sheet.getByRole("button", { name: "Stop sharing" }).click();
  await expect(sheet.getByRole("button", { name: "Create a link" })).toBeVisible();
  await expect.poll(() => Object.keys(state.shares).length).toBe(0);
  await sheet.getByRole("button", { name: "Create a link" }).click();
  await expect(link).toHaveValue(/fakeShare0003x+$/);
  const shared = new URL(await link.inputValue()).pathname;
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);

  // Opened by someone who isn't signed in.
  await page.evaluate(() => fetch("/api/auth/logout", { method: "POST", headers: { "X-CSRF-Token": "csrf-1" } }));
  await page.goto(`/shared/${"fakeShare0001".padEnd(43, "x")}`);
  await expect(page.getByRole("alert")).toContainText("This link doesn't work any more");

  await page.goto(shared);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tokyo");
  await expect(page.getByText("Shared with you · read only")).toBeVisible();
  const plan = page.getByRole("region", { name: "The plan" });
  await expect(plan.getByRole("heading", { name: /^Day 2/ })).toBeVisible();
  await expect(plan).toContainText("Tsukiji");
  await expect(plan).toContainText("ZZ12 SIN → NRT");
  await expect(plan).toContainText("08:25 → 16:05");
  await expect(plan).toContainText("Staying at Hotel Kumo");
  await expect(plan.getByRole("link", { name: "Open Fish market breakfast in Google Maps" })).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=Fish%20market%20breakfast%2C%204-5%20Market%20St%2C%20Tokyo",
  );
  const text = await page.locator("main").innerText();
  for (const secret of ["HK55821", "ZK4P7Q", "Agoda", "Somewhere secret", "SGD", "JPY", "820"]) expect(text).not.toContain(secret);
  // Nothing can be changed, and it never asked anyone to sign in.
  await expect(page.getByRole("button")).toHaveCount(0);
  await expect(page).toHaveURL(shared);
});

test("ideas from guides and articles: asked for in words, credited, saved to the trip", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  await page.getByRole("button", { name: "Add to the trip" }).click();
  const sheet = page.getByRole("dialog", { name: "Add to Seoul" });
  await expect(sheet.getByRole("button", { name: /Find a place/ })).toContainText("best ramen");
  await sheet.getByRole("button", { name: /Find a place/ }).click();

  // Asking for ideas: Google Maps answers first, then guides and articles below.
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("best noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("list", { name: "Google Maps results" })).toContainText("Hanok Noodle Bar");
  const ideas = page.getByRole("list", { name: "Ideas from guides and articles" });
  await expect(ideas).toContainText("“Hand-pulled noodles worth the queue.”");
  await expect.poll(() => state.ideaSearches).toEqual(["best noodles"]);
  // Each is credited to its page, opened safely in a new tab.
  const source = ideas.getByRole("link", { name: "Seoul's best noodles" });
  await expect(source).toHaveAttribute("href", "https://food.example.com/seoul-noodles");
  await expect(source).toHaveAttribute("rel", /noopener/);
  await expect(ideas.getByLabel("Rated 4.6 out of 5 from 2310 ratings")).toBeVisible();
  await expect(ideas).toContainText("Nightlife · Euljiro");

  // Saving one without a Google Maps match keeps its name, kind and area.
  await ideas.getByRole("button", { name: "Save: Lantern Alley" }).click();
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Lantern Alley", category: "Nightlife", list_name: "Nightlife", address: "Euljiro", place_id: null });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("list", { name: "Places to visit" })).toContainText("Lantern Alley");
});

test("the trip on a map, coloured by day, with travel times between stops", async ({ page }, info) => {
  const state = await fakeApi(page);
  state.mapKey = "test-browser-key";
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  // Two plans on day 3, each linked to a made-up Google Maps place, 20 minutes apart.
  const plan = (id: string, name: string, at: string, place: string) => ({
    id, trip_id: "trip1", kind: "activity", title: name, provider: null, starts: "2026-11-12", ends: "2026-11-12",
    segments: [], hotel: null, address: null, check_in: null, check_out: null, name, day: "2026-11-12", at, note: null,
    cost: null, logged: false, manual: true, reference: null, booked_via: null, category: null, place_id: place, scheduled: true,
  });
  state.plans.push(plan("pl1", "Hanok Noodle Bar", "12:00", "fakePlaceNoodle01"), plan("pl2", "Namdaemun Market", "12:20", "fakePlaceMarket01"));
  await page.reload();

  // Both on the map, numbered as on the itinerary and in day 3's colour.
  const map = page.getByRole("region", { name: "Map" });
  await expect(map.getByRole("list", { name: "On the map" }).getByRole("listitem")).toHaveText(["1. Hanok Noodle Bar", "2. Namdaemun Market"]);
  const pins = () => page.evaluate(() => (window as unknown as { __map: { markers: { o: { title: string; label?: { text: string }; icon: { fillColor: string } } }[] } }).__map.markers.map((m) => [m.o.title, m.o.label?.text, m.o.icon.fillColor]));
  await expect.poll(pins).toEqual([
    ["Hanok Noodle Bar", "1", "#059669"],
    ["Namdaemun Market", "2", "#059669"],
  ]);
  expect(await page.evaluate(() => (window as unknown as { __map: { key: string } }).__map.key)).toBe("test-browser-key");
  // Picking the day draws its route; a day with nothing planned says so.
  await map.getByRole("button", { name: "Day 3" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __map: { lines: number } }).__map.lines)).toBe(1);
  await map.getByRole("button", { name: "Day 1" }).click();
  await expect(map).toContainText("Nothing on the map that day.");
  await map.getByRole("button", { name: "All" }).click();

  // Between the two on the itinerary: how long it takes (asked for once the day comes
  // into view), and a way to change it.
  await page.getByRole("heading", { name: /^Day 3 ·/ }).scrollIntoViewIfNeeded();
  const hop = page.getByRole("listitem", { name: "From Hanok Noodle Bar to Namdaemun Market" });
  await expect(hop).toContainText("14 min walk · 940 m");
  // The plans keep their numbers (as on the map) once the times arrive.
  await expect(page.locator("#entry-pl1 .stop-number")).toHaveText("1");
  await expect(page.locator("#entry-pl2 .stop-number")).toHaveText("2");
  await expect(hop.getByRole("link", { name: "Directions" })).toHaveAttribute("href", /destination_place_id=fakePlaceMarket01/);
  await hop.getByLabel("How to get to Namdaemun Market").selectOption("transit");
  await expect(hop).toContainText("25 min by public transport");
  await expect(hop).toContainText("Tight");
  expect(state.hopModes).toEqual(["transit"]);
  // Directions can open in another maps app, remembered on this device; it gets only the
  // entries' own names, never Google's place ids.
  await page.getByLabel("Directions open in").selectOption("apple");
  await expect(hop.getByRole("link", { name: "Directions" })).toHaveAttribute("href", "https://maps.apple.com/?saddr=Hanok+Noodle+Bar&daddr=Namdaemun+Market&dirflg=r");
  await page.reload();
  await page.getByRole("heading", { name: /^Day 3 ·/ }).scrollIntoViewIfNeeded();
  await expect(page.getByLabel("Directions open in")).toHaveValue("apple");
  await page.getByLabel("Directions open in").selectOption("google");

  // Tapping a pin finds its plan on the itinerary.
  await page.evaluate(() => (window as unknown as { __map: { markers: { click: () => void }[] } }).__map.markers[1].click());
  await expect(page.locator("#entry-pl2")).toHaveClass(/entry-flash/);

  // On a phone the map opens full screen; on a wide screen it sits beside the itinerary.
  if (info.project.name === "mobile") {
    await map.getByRole("button", { name: "Full screen" }).click();
    await expect(map).toHaveClass(/trip-map-full/);
    await map.getByRole("button", { name: "Close map" }).click();
    await expect(map).not.toHaveClass(/trip-map-full/);
  } else {
    await expect(map.getByRole("button", { name: "Full screen" })).toBeHidden();
  }
});

test("the itinerary goes a day at a time: swipe, pick a day, drop a plan on another day", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push({
    id: "pl1", trip_id: "trip1", kind: "activity", title: "Old Temple", provider: null, starts: "2026-11-11", ends: "2026-11-11", segments: [], hotel: null,
    address: null, check_in: null, check_out: null, name: "Old Temple", day: "2026-11-11", at: "10:00", ends_at: null, note: null, cost: null, logged: false,
    manual: true, reference: null, booked_via: null, category: null, place_id: null, link: null, list_name: null, order: null, scheduled: true,
  });
  await page.reload();
  const days = page.getByRole("region", { name: "Days of the trip" });
  const pills = page.getByRole("navigation", { name: "Days" });
  await expect(days).toContainText(/Day 1 · .*, 1 of 4/);
  await expect(days.getByRole("button", { name: "Previous day" })).toBeDisabled();

  // A swipe moves the track; the heading and pills follow it.
  await page.locator(".day-track").evaluate((el) => el.scrollTo({ left: el.clientWidth * 2 }));
  await expect(days).toContainText("3 of 4");
  await expect(pills.getByRole("button", { name: /12/ })).toHaveAttribute("aria-current", "true");

  // A pill opens its day.
  await pills.getByRole("button", { name: /11/ }).click();
  await expect(days).toContainText("2 of 4");
  const track = page.locator(".day-track");
  await expect.poll(() => track.evaluate((el) => el.scrollLeft / el.clientWidth)).toBe(1); // settled

  // Dragged onto day 4's pill and held there: that day opens, and the plan goes onto it.
  // (On a phone the strip scrolls: day 4's pill is brought into view first.)
  const pill4 = pills.getByRole("button", { name: /13/ });
  await pill4.evaluate((el) => el.parentElement!.scrollTo({ left: (el as HTMLElement).offsetLeft }));
  const grip = page.getByRole("button", { name: "Drag Old Temple" });
  // Mid-screen, clear of the bottom navigation (the day strip stays pinned above).
  await grip.evaluate((el) => el.scrollIntoView({ block: "center" }));
  // Both still, and both on screen.
  let last = "";
  await expect.poll(async () => {
    const now = JSON.stringify([await grip.boundingBox(), await pill4.boundingBox()]);
    const still = now === last;
    last = now;
    return still;
  }).toBe(true);
  const from = (await grip.boundingBox())!;
  const day4 = (await pill4.boundingBox())!;
  const screen = page.viewportSize()!;
  expect(day4.x + day4.width / 2).toBeLessThan(screen.width);
  expect(from.y + from.height).toBeLessThan(screen.height);
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2 - 10, { steps: 3 });
  await page.mouse.move(day4.x + day4.width / 2, day4.y + day4.height / 2, { steps: 8 });
  await expect(days).toContainText("4 of 4");
  await page.mouse.up();
  await expect.poll(() => state.moves).toEqual(["pl1>2026-11-13@first"]);
});

test("a day rearranged: dragged, moved by keyboard or menu, with what to watch out for", async ({ page }, info) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  // Made-up plans: two on day 2 that overlap, and two places to visit in two lists.
  const entry = (id: string, name: string, more: Record<string, unknown>) => ({
    id, trip_id: "trip1", kind: "activity", title: name, provider: null, starts: "2026-09-28", ends: null, segments: [], hotel: null,
    address: null, check_in: null, check_out: null, name, day: null, at: null, ends_at: null, note: null, cost: null, logged: false,
    manual: true, reference: null, booked_via: null, category: null, place_id: null, link: null, list_name: null, order: null,
    scheduled: false, ...more,
  });
  const onDay2 = { day: "2026-11-11", starts: "2026-11-11", ends: "2026-11-11", scheduled: true };
  state.plans.push(
    entry("pl1", "Old Temple", { ...onDay2, at: "13:00", ends_at: "15:00" }),
    entry("pl2", "Tea house", { ...onDay2, at: "14:00" }),
    entry("pl3", "Lantern Alley", { list_name: "Nightlife" }),
    entry("pl4", "Namdaemun Market", { list_name: "Shopping" }),
  );
  await page.reload();
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  const day2 = itinerary.getByRole("list", { name: /^Day 2/ });
  const day3 = itinerary.getByRole("list", { name: /^Day 3/ });

  // What's worth a look on the day, worked out on the server.
  const notes = itinerary.getByRole("list", { name: "Worth a look" });
  await expect(notes.getByRole("listitem")).toHaveText([/Old Temple \(13:00 to 15:00\) runs into Tea house at 14:00/, /Free 09:00 to 13:00/]);
  await expect(page.locator("#entry-pl1 .time-pill")).toHaveText("13:00–15:00");

  // Places to visit filter by list.
  const places = page.getByRole("list", { name: "Places to visit" });
  const lists = page.getByRole("group", { name: "Lists" });
  await lists.getByRole("button", { name: /Shopping/ }).click();
  await expect(places.getByRole("listitem")).toHaveCount(1);
  await expect(places).toContainText("Namdaemun Market");
  await lists.getByRole("button", { name: "All" }).click();
  await expect(places.getByRole("listitem")).toHaveCount(2);

  // One day at a time: it opens on day 1; the next day is a swipe or a tap away.
  const days = page.getByRole("region", { name: "Days of the trip" });
  await expect(days).toContainText("1 of 4");
  await days.getByRole("button", { name: "Next day" }).click();
  await expect(days).toContainText(/Day 2 · .*, 2 of 4/);
  await expect(page.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /11/ })).toHaveAttribute("aria-current", "true");

  // Dragged by its grip to above the temple: one call, and the day follows it.
  const grip = page.getByRole("button", { name: "Drag Tea house" });
  await grip.scrollIntoViewIfNeeded();
  await expect.poll(async () => (await grip.boundingBox())?.x ?? -1).toBeGreaterThan(0);
  const from = (await grip.boundingBox())!;
  const onto = (await page.locator("#entry-pl1").boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2 - 10, { steps: 3 });
  await page.mouse.move(onto.x + 40, onto.y + 4, { steps: 8 });
  await expect(page.locator("#entry-pl1")).toHaveClass(/drop-before/);
  await page.mouse.up();
  await expect.poll(() => state.moves).toEqual(["pl2>2026-11-11@first"]);
  await expect(day2.locator(".timeline-stop strong")).toHaveText(["Tea house", "Old Temple"]);

  // With the keyboard: picked up, taken up to the empty day 3, and dropped.
  const keys = page.getByRole("button", { name: "Drag Lantern Alley" });
  await keys.focus();
  await page.keyboard.press("Space");
  const said = page.getByRole("status", { name: "Moving a plan" });
  await expect(said).toContainText("Picked up Lantern Alley");
  // Up from first in places to visit: first on day 4, then first on day 3.
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await expect(said).toContainText(/Lantern Alley: first, Thu.*12/);
  await expect(day3.locator("..")).toHaveClass(/drop-over/);
  // The carousel follows the plan to day 3.
  await expect(days).toContainText("3 of 4");
  await page.keyboard.press("Space");
  await expect.poll(() => state.moves).toEqual(["pl2>2026-11-11@first", "pl3>2026-11-12@first"]);
  await expect(day3).toContainText("Lantern Alley");
  await expect(places).not.toContainText("Lantern Alley");
  await expect(page.getByRole("button", { name: "Drag Lantern Alley" })).toBeFocused();

  // Or from the entry's menu, without dragging: the temple after it on day 3.
  await page.getByRole("button", { name: "Change Old Temple" }).click();
  await page.getByRole("button", { name: "Move Old Temple to another day or place" }).click();
  const move = page.getByRole("form", { name: "Move Old Temple" });
  await move.getByLabel("To").selectOption({ label: new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date("2026-11-12")) });
  await move.getByLabel("Where").selectOption({ label: "After Lantern Alley" });
  await move.getByRole("button", { name: "Move" }).click();
  await expect.poll(() => state.moves.at(-1)).toBe("pl1>2026-11-12@pl3");
  await expect(day3.locator(".timeline-stop strong")).toHaveText(["Lantern Alley", "Old Temple"]);

  // Free time left on day 2 offers something to fill it, saved onto that day.
  await expect(notes.first()).toContainText("Free 09:00 to 14:00");
  await notes.first().getByRole("button", { name: "Find something to do" }).click();
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("list", { name: "Google Maps results" }).getByRole("button", { name: "Add: Hanok Noodle Bar" }).click();
  await expect.poll(() => state.plans.at(-1)).toMatchObject({ name: "Hanok Noodle Bar", day: "2026-11-11", at: "09:00", place_id: "fakePlaceNoodle01" });
  await page.keyboard.press("Escape");
  await expect(day2).toContainText("Hanok Noodle Bar");

  // An end time and a link, from the entry's editor.
  await page.getByRole("button", { name: "Change Tea house" }).click();
  await page.getByRole("button", { name: "Edit Tea house" }).click();
  const edit = page.getByRole("form", { name: "Change the entry" });
  await edit.getByLabel("Until").fill("15:30");
  await edit.getByLabel("Link").fill("https://tea.example.com/book");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => state.plans.find((p) => p.id === "pl2")).toMatchObject({ ends_at: "15:30", link: "https://tea.example.com/book" });
  await expect(page.locator("#entry-pl2 .time-pill")).toHaveText("14:00–15:30");
  const link = page.getByRole("link", { name: "Open the link for Tea house" });
  await expect(link).toHaveAttribute("href", "https://tea.example.com/book");
  await expect(link).toHaveAttribute("rel", /noopener/);

  // On a phone: a long press on the grip, then a drag, to above the noodle bar.
  if (info.project.name === "mobile") {
    await expect(day2.locator(".timeline-stop strong")).toHaveText(["Hanok Noodle Bar", "Tea house"]);
    const touch = await page.context().newCDPSession(page);
    await page.locator("#entry-pl5").evaluate((e) => e.scrollIntoView({ block: "center" }));
    await page.waitForLoadState("networkidle");
    const start = (await page.getByRole("button", { name: "Drag Tea house" }).boundingBox())!;
    const noodles = (await page.locator("#entry-pl5").boundingBox())!;
    const at = (x: number, y: number) => [{ x: Math.round(x), y: Math.round(y) }];
    const [x0, y0, y1] = [start.x + start.width / 2, start.y + start.height / 2, noodles.y + 6];
    await touch.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: at(x0, y0) });
    await page.waitForTimeout(400);
    for (let i = 1; i <= 10; i += 1) {
      await touch.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: at(x0, y0 + ((y1 - y0) * i) / 10) });
    }
    await expect(page.locator("#entry-pl5")).toHaveClass(/drop-before/);
    await touch.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect.poll(() => state.moves.at(-1)).toBe("pl2>2026-11-11@first");
  }
});

test("a day out from the hotel checked into that morning ends with the way back, at the end", async ({ page }) => {
  const state = await fakeApi(page);
  state.backToHotel = true;
  state.mapKey = "test-browser-key";
  await addTrip(page, "Seoul", "2026-10-21", "2026-10-24");
  state.plans.push(
    {
      id: "pl2", trip_id: "trip1", kind: "hotel", title: "Hill Lodge, 3 nights", provider: null, starts: "2026-10-21", ends: "2026-10-24",
      segments: [], hotel: "Hill Lodge", address: "3 Example Cove", check_in: "2026-10-21", check_out: "2026-10-24", name: null, day: null,
      at: null, note: null, cost: null, logged: false, manual: true, reference: null, booked_via: null, category: null,
      place_id: "fakePlaceLodge001", scheduled: true,
    },
    {
      id: "pl3", trip_id: "trip1", kind: "activity", title: "Car return", provider: null, starts: "2026-10-21", ends: "2026-10-21", segments: [],
      hotel: null, address: null, check_in: null, check_out: null, name: "Car return", day: "2026-10-21", at: "17:00", ends_at: null, note: null,
      cost: null, logged: false, manual: true, reference: null, booked_via: null, category: null, place_id: "fakePlaceCarDesk1", link: null,
      list_name: null, order: null, scheduled: true,
    },
  );
  await page.reload();
  const day1 = page.getByRole("region", { name: "Itinerary" }).getByRole("list", { name: /^Day 1/ });
  const rows = day1.locator(":scope > li");
  // Check in, the way to the car return, the return, then the way back to the hotel:
  // last, and named, not above the check-in.
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("Hill Lodge");
  await expect(rows.nth(1)).toHaveAccessibleName("From Hill Lodge to Car return");
  await expect(rows.nth(2)).toContainText("Car return");
  await expect(rows.nth(3)).toHaveAccessibleName("From Car return to Hill Lodge");
  await expect(rows.nth(3)).toContainText("Back to Hill Lodge · 20 min by public transport");
});

test("a travel day: the overnight flight lands, then the way to the hotel", async ({ page }) => {
  const state = await fakeApi(page);
  state.mapKey = "test-browser-key";
  await addTrip(page, "Seoul", "2026-10-21", "2026-10-24");
  // A made-up overnight flight landing on day 1, its airport found on Google Maps, and
  // the hotel checked into that day.
  state.plans.push(
    {
      id: "pl1", trip_id: "trip1", kind: "flight", title: "ZZ378 SIN → BCN", provider: "Acme Air", starts: "2026-10-20", ends: "2026-10-21",
      segments: [{ number: "ZZ378", origin: "SIN", destination: "BCN", departs: "2026-10-20T23:30", arrives: "2026-10-21T09:15" }],
      hotel: null, address: null, check_in: null, check_out: null, name: null, day: null, at: null, note: null, cost: null, logged: false,
      manual: true, reference: null, booked_via: null, category: null, place_id: null, scheduled: true, stations: { "BCN airport": "fakePlaceAirport1" },
    },
    {
      id: "pl2", trip_id: "trip1", kind: "hotel", title: "Hill Lodge, 3 nights", provider: null, starts: "2026-10-21", ends: "2026-10-24",
      segments: [], hotel: "Hill Lodge", address: "3 Example Cove", check_in: "2026-10-21", check_out: "2026-10-24", name: null, day: null,
      at: null, note: null, cost: null, logged: false, manual: true, reference: null, booked_via: null, category: null,
      place_id: "fakePlaceLodge001", scheduled: true,
    },
  );
  await page.reload();
  const itinerary = page.getByRole("region", { name: "Itinerary" });

  // The day before: the flight leaves. Day 1: it lands, then the hotel.
  const before = itinerary.locator("#day-2026-10-20").getByRole("list");
  await expect(before).toContainText("ZZ378 SIN → BCN");
  const day1 = itinerary.getByRole("list", { name: /^Day 1/ });
  await day1.scrollIntoViewIfNeeded();
  await expect(day1.locator(":scope > li").first()).toContainText("Land BCN 09:15");
  await expect(day1.locator("#land-pl1")).toContainText("ZZ378 · Acme Air from SIN");
  // The hotel's name sits on its own line above its dates.
  expect(await page.locator("#entry-pl2 .wrap").innerText()).toMatch(/^Hill Lodge\n/);

  // From the airport to the hotel, by public transport to start with; the wait for
  // check-in counts it.
  const hop = page.getByRole("listitem", { name: "From BCN airport to Hill Lodge" });
  await expect(hop).toContainText("2 h 20 min by public transport");
  const notes = itinerary.getByRole("list", { name: "Worth a look" });
  await expect(notes).toContainText("Arrive around 11:35 (land 09:15, then 2 h 20 min) · check-in from 15:00 · about 3 h 30 min to fill");

  // With a hire car the longer hops drive.
  await page.getByLabel("Getting around").selectOption("car");
  await expect.poll(() => state.trips[0].getting_around).toBe("car");
  await expect(hop).toContainText("1 h 30 min drive");
  await expect(notes).toContainText("Arrive around 10:45 (land 09:15, then 1 h 30 min) · check-in from 15:00 · about 4 h 15 min to fill");

  // The airport is on the map, and day 1's route runs from it to the hotel.
  const markers = () => page.evaluate(() => (window as unknown as { __map: { markers: { o: { title: string } }[] } }).__map.markers.map((m) => m.o.title));
  await expect.poll(markers).toEqual(expect.arrayContaining(["BCN airport", "Hill Lodge"]));
  await page.getByRole("region", { name: "Map" }).getByRole("button", { name: "Day 1" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __map: { lines: number } }).__map.lines)).toBe(1);
});

test("without a map key the trip page has no map", async ({ page }) => {
  await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  await expect(page.getByRole("region", { name: "Itinerary" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Map" })).toHaveCount(0);
});

test("trip forms don't jump when a field is tapped", async ({ page }, info) => {
  await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  const phone = info.project.name === "mobile";
  const fields = "input:not([type=checkbox]):not([type=file]):not([type=radio]), select, textarea";
  // Phones zoom into a field under 16px when it's tapped, which jumps the page.
  const smallest = (scope: Locator) =>
    scope.locator(fields).evaluateAll((els) => Math.min(...els.map((el) => parseFloat(getComputedStyle(el).fontSize))));
  const viewport = page.locator(".main-viewport");

  // The add sheet: the page behind it stays put; typing waits for a tap on a phone.
  await page.getByRole("button", { name: "Add to the trip" }).click();
  // The sheet is named for the view it shows ("Type it", "Find a place").
  const sheet = page.getByRole("dialog");
  await expect(sheet).toHaveAccessibleName("Add to Seoul");
  await expect(viewport).toHaveCSS("overflow-y", "hidden");
  await sheet.getByRole("button", { name: /Type it/ }).click();
  if (phone) await expect(sheet.getByLabel("Tell Nexus about a booking")).not.toBeFocused();
  else await expect(sheet.getByLabel("Tell Nexus about a booking")).toBeFocused();
  await sheet.getByRole("button", { name: "Back to the ways to add" }).click();
  await sheet.getByRole("button", { name: /Find a place/ }).click();
  if (phone) expect(await smallest(sheet)).toBeGreaterThanOrEqual(16);
  await page.keyboard.press("Escape");
  await expect(viewport).toHaveCSS("overflow-y", "auto");

  // A form the user opens shows as it is, without fading in, and its fields don't zoom.
  await page.getByRole("button", { name: "Add to the trip" }).click();
  await sheet.getByRole("button", { name: /Fill in a form/ }).click();
  await sheet.getByRole("button", { name: "🏨 Place to stay" }).click();
  const adding = page.locator("#trip-adding");
  await expect(adding).toBeVisible();
  await expect(adding).not.toHaveAttribute("data-reveal", /.*/);
  if (phone) expect(await smallest(adding)).toBeGreaterThanOrEqual(16);

  await page.getByRole("button", { name: "Trip options" }).click();
  await page.getByRole("menuitem", { name: "Edit trip" }).click();
  const edit = page.getByRole("region", { name: "Change the trip" });
  await expect(edit).not.toHaveAttribute("data-reveal", /.*/);
  if (phone) expect(await smallest(edit)).toBeGreaterThanOrEqual(16);
});

test("the keyboard opening leaves the background still and the tab bar out of the way", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "a phone's keyboard");
  await fakeApi(page);
  await page.goto("/travel");
  const bar = page.getByRole("navigation", { name: "Main (mobile)" });
  await expect(bar).toBeVisible();

  // Typing: the bar (and Nexus in it) steps aside.
  await page.getByRole("button", { name: "Add a trip" }).click();
  const where = page.getByRole("form", { name: "Add a trip" }).getByLabel("Where");
  await where.focus();
  await expect(page.locator("html")).toHaveClass(/keyboard/);
  await expect(bar).toBeHidden();
  // The keyboard shrinks the screen.
  const size = page.viewportSize()!;
  await page.setViewportSize({ width: size.width, height: Math.round(size.height * 0.55) });
  // Tabbing to the next field doesn't flash the bar back.
  await page.getByRole("form", { name: "Add a trip" }).getByLabel("From").focus();
  await expect(bar).toBeHidden();

  // Done typing: everything comes back.
  await page.setViewportSize(size);
  await page.getByRole("form", { name: "Add a trip" }).getByLabel("From").blur();
  await expect(page.locator("html")).not.toHaveClass(/keyboard/);
  await expect(bar).toBeVisible();
});

test("after a trip: settling up comes first, then what it cost", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Osaka", "2026-11-10", "2026-11-12");
  state.trips[0] = { ...state.trips[0], status: "finished" };
  await page.reload();
  const settle = page.getByRole("region", { name: "Settle up" });
  await expect(settle).toContainText("Ann");
  await expect(page.getByRole("region", { name: "The trip in numbers" })).toContainText("SGD 818.00");
  await expect(page.getByRole("button", { name: "Add to the trip" })).toHaveCount(0);
  await expect(page.getByText("All expenses")).toBeVisible();
});

test("cards rise into view and figures count up, unless less motion is asked for", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  const hero = page.getByRole("region", { name: "Nexus" });
  await expect(hero).toHaveAttribute("data-reveal", "in");
  await expect(hero.locator(".hero-value")).toHaveText("SGD 37.40");
  await expect(page.getByRole("heading", { level: 1 }).locator("em.accent-serif")).toHaveText(/morning|afternoon|evening/);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(hero.locator(".hero-value")).toHaveText("SGD 37.40");
  await expect(hero).not.toHaveAttribute("data-reveal", /.*/);
});

test("each section is its own rounded card, its title above it, with room either side", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  const budgets = page.getByRole("region", { name: "Budgets this month" });
  const card = budgets.locator(".card");
  await expect(card).toBeVisible();
  // The title sits above the card, not inside it.
  const title = (await budgets.getByRole("heading", { name: "Budgets this month" }).boundingBox())!;
  const box = (await card.boundingBox())!;
  expect(title.y + title.height).toBeLessThanOrEqual(box.y);
  expect(box.x).toBeGreaterThan(0);
  expect(box.x + box.width).toBeLessThan(page.viewportSize()!.width);
  expect(await card.evaluate((el) => getComputedStyle(el).borderTopLeftRadius)).not.toBe("0px");
});

test("in Telegram, a trip's page shows Telegram's back button, and it goes back to the trips", async ({ page }) => {
  await page.addInitScript(() => {
    const back = { shown: false, go: null as null | (() => void) };
    (window as unknown as { back: typeof back }).back = back;
    (window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: {
        ready() {},
        expand() {},
        BackButton: {
          show: () => (back.shown = true),
          hide: () => (back.shown = false),
          onClick: (cb: () => void) => (back.go = cb),
          offClick: () => (back.go = null),
        },
      },
    };
  });
  await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-13");
  const shown = () => page.evaluate(() => (window as unknown as { back: { shown: boolean } }).back.shown);
  await expect.poll(shown).toBe(true);
  await page.evaluate(() => (window as unknown as { back: { go: () => void } }).back.go());
  await expect(page).toHaveURL(/\/travel$/);
  await expect.poll(shown).toBe(false);
});
