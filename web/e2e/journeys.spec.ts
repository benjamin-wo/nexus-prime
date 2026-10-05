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
  await expect(page.getByRole("heading", { name: "Needs you" })).toBeVisible();
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
  await page.goto("/accounting");
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
  await page.goto("/accounting");
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

test("mark a bill with no set amount paid and log what was paid", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  const form = page.getByRole("form", { name: "Add a bill" });
  await form.getByLabel("Bill").fill("Electricity");
  await form.getByLabel("Next due").fill("2026-10-01");
  await form.getByRole("button", { name: "Add bill" }).click();
  const bills = page.getByRole("region", { name: "Bills" });
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
  await expect(detail.getByRole("listitem").filter({ hasText: "Rent" })).toContainText("Bill");
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

test("add, rename, archive and bring back a category", async ({ page }) => {
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
  await petCare.getByRole("button", { name: "Archive" }).click();
  await petCare.getByRole("button", { name: "Archive" }).click();
  const archived = card.getByRole("list", { name: "Archived categories" });
  await expect(archived.getByRole("heading", { name: "Pet care" })).toBeVisible();
  await archived.getByRole("button", { name: "Bring back" }).click();
  await expect(yours.getByRole("heading", { name: "Pet care" })).toBeVisible();
});

test("the cog opens Settings, and Plan keeps only planning", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  await expect(page.getByRole("region", { name: "Budgets" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Categories" })).toHaveCount(0);
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

test("the chat bubble floats on every page and opens the chat", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/plan");
  await expect(page.getByRole("navigation").getByRole("button", { name: /chat/i })).toHaveCount(0);
  const bubble = page.locator(".chat-fab");
  await expect(bubble).toHaveAccessibleName("Open chat");
  await expect(bubble).toHaveCSS("position", "fixed");
  await bubble.click();
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
  await expect(card.getByRole("list", { name: "Archived categories" }).getByRole("heading", { name: "Transport" })).toBeVisible();
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
  await expect(page.getByRole("link", { name: /^Accounting:/ })).toContainText("This month: SGD");
  await expect(page.getByRole("link", { name: /^Travel:/ })).toContainText("Your trips");
});

test("asking on home opens the chat with the question", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await page.getByRole("textbox", { name: "Ask Nexus" }).fill("how much on grab?");
  await page.getByRole("button", { name: "Ask" }).click();
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
  await expect(page.getByRole("link", { name: /^Investment: / })).toContainText("Portfolio SGD");
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
  expect(state.watching).toEqual([]);
});

test("a research plan is started from a stock and read with its chart and sources", async ({ page }) => {
  const state = await fakeApi(page);
  state.watching = ["AMD"];
  await page.goto("/investment/stocks/AMD");
  const card = page.getByRole("region", { name: "Research plan" });
  await card.getByRole("button", { name: "Make a plan" }).click();
  await expect(card.getByRole("status")).toContainText("Plan for AMD started");
  expect(state.planStarted).toBe(true);

  await page.goto("/investment/plans");
  // The track record counts finished plans; each plan shows how it's going.
  const record = page.getByRole("region", { name: "Track record" });
  await expect(record.getByLabel("Plan results")).toContainText("Hit target1");
  await expect(record).toContainText("Average result+4.6%");
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
  await expect(page.getByRole("img", { name: /AMD daily closes over 60 days/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What could go wrong" })).toBeVisible();
  const cite = page.getByRole("link", { name: "[Wire]" });
  await expect(cite).toHaveAttribute("href", "https://news.example/1");
  await expect(cite).toHaveAttribute("rel", /noopener/);
});

test("a trip is added and shows its spending, set-aside and settle-up", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/travel");
  await expect(page.getByText(/No trips yet/)).toBeVisible();
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  await form.getByLabel("Where").fill("Tokyo");
  await form.getByLabel("From").fill("2026-11-10");
  await form.getByLabel("To").fill("2026-11-19");
  await form.getByLabel("Currency there").fill("jpy");
  await form.getByLabel(/^Budget/).fill("3000");
  await form.getByLabel(/^Set aside each payday/).fill("500");
  await form.getByLabel("Who's going").fill("Ann, Ben");
  await form.getByRole("button", { name: "Add a category" }).click();
  await form.getByLabel("Category").fill("Dining Out");
  await form.getByLabel("Planned amount").fill("600");
  await form.getByRole("button", { name: "Add trip" }).click();

  await expect(page).toHaveURL(/\/travel\/trips\/trip1$/);
  await expect(page.getByRole("heading", { name: "Tokyo", level: 1 })).toBeVisible();
  expect(state.trips[0]).toMatchObject({ currency: "JPY", companions: ["Ann", "Ben"], planned: { "Dining Out": { amount: "600.0000" } } });
  const spending = page.getByRole("region", { name: "Trip spending" });
  await expect(spending).toContainText("SGD 818.00 of SGD 3,000.00");
  await expect(spending).toContainText("SGD 800.00 before the trip");
  await expect(page.getByRole("region", { name: "Setting money aside" })).toContainText("SGD 1,500.00 each payday would cover it");
  await expect(page.getByRole("region", { name: "Settle up" })).toContainText("Ann");
  const itinerary = page.getByRole("region", { name: "Itinerary" });
  await expect(itinerary).toContainText("ZZ12 SIN → NRT");
  await expect(itinerary).toContainText("not logged");
  await expect(spending).toContainText("SGD 820.00 not logged yet");
  const expenses = page.getByRole("region", { name: "Expenses" });
  await expect(expenses.getByText("added by hand")).toBeVisible();
  await expenses.getByRole("button", { name: "Take Air ticket off the trip" }).click();
  await expect(expenses.getByText("Air ticket")).toHaveCount(0);
  expect(state.tripItems).toEqual(["k1"]);

  await page.goto("/");
  await expect(page.getByRole("link", { name: /^Travel:/ })).toContainText("Tokyo: in 43 days");
  await page.goto("/travel");
  await expect(page.getByRole("region", { name: "Coming up" }).getByRole("link", { name: "Tokyo" })).toBeVisible();
  const loose = page.getByRole("region", { name: "Bookings not on a trip" });
  await expect(loose).toContainText("Hotel Sakura, 2 nights");
  await loose.getByLabel("Trip for Hotel Sakura, 2 nights").selectOption("trip1");
  await expect(loose).toHaveCount(0);
  expect(state.movedBookings).toEqual(["bk2:trip1"]);
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
  expect(state.trips[0]).toMatchObject({ destination: "Tokyo", currency: "JPY" });
});

test("plans are added to a trip's itinerary by hand, day by day, and changed", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/travel");
  await page.getByRole("button", { name: "Add a trip" }).click();
  const form = page.getByRole("form", { name: "Add a trip" });
  await form.getByLabel("Where").fill("Tokyo");
  await form.getByLabel("From").fill("2026-11-10");
  await form.getByLabel("To").fill("2026-11-19");
  await form.getByLabel("Currency there").fill("JPY");
  await form.getByLabel("Notes").fill("Pack an adapter");
  await form.getByRole("button", { name: "Add trip" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip1$/);
  expect(state.trips[0]).toMatchObject({ destination: "Tokyo" });

  const itinerary = page.getByRole("region", { name: "Itinerary" });
  await itinerary.getByRole("button", { name: "Add to itinerary" }).click();
  const entry = itinerary.getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Dinner at Sushi Ten");
  await entry.getByLabel("Day", { exact: true }).fill("2026-11-12");
  await entry.getByLabel("Time", { exact: true }).fill("19:00");
  await entry.getByLabel("Where", { exact: true }).fill("1-2-3 Ginza");
  await entry.getByRole("button", { name: "Add" }).click();
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("Dinner at Sushi Ten");
  await expect(itinerary).toContainText("19:00 · 1-2-3 Ginza");
  expect(state.plans[0]).toMatchObject({ name: "Dinner at Sushi Ten", day: "2026-11-12", at: "19:00" });

  await itinerary.getByRole("button", { name: "Edit Dinner at Sushi Ten" }).click();
  const edit = itinerary.getByRole("form", { name: "Change the entry" });
  await edit.getByLabel("Time", { exact: true }).fill("20:00");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(itinerary).toContainText("20:00 · 1-2-3 Ginza");

  page.once("dialog", (d) => void d.accept());
  await itinerary.getByRole("button", { name: "Remove Dinner at Sushi Ten" }).click();
  await expect(itinerary).not.toContainText("Dinner at Sushi Ten");
  expect(state.plans).toEqual([]);

  // A hotel starts on the trip's dates and shows on each night of the stay.
  await itinerary.getByRole("button", { name: "Add to itinerary" }).click();
  await entry.getByLabel("What").selectOption("hotel");
  await expect(entry.getByLabel("Check in")).toHaveValue("2026-11-10");
  await expect(entry.getByLabel("Check out")).toHaveValue("2026-11-19");
  await entry.getByLabel("Hotel", { exact: true }).fill("Hotel Kawa");
  await entry.getByLabel("Check out").fill("2026-11-13");
  await entry.getByRole("button", { name: "Add" }).click();
  await expect(itinerary.getByText("Staying at Hotel Kawa")).toHaveCount(2); // the 11th and 12th
  expect(state.plans[0]).toMatchObject({ check_in: "2026-11-10", check_out: "2026-11-13" });
});
