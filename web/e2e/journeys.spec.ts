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
  await page.goto("/accounting/ledger");
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

test("the overview shows what was put away and its share of income, once there is a wallet to put it in", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
  const tile = page.getByLabel("Put away");
  await expect(tile).toContainText(/SGD.800\.00/);
  await expect(tile).toContainText("19% of income");
  // Spent, Received, Net and Put away sit two by two, with no tile alone on a row.
  // Layout positions, not the on-screen box: the tiles fade in with a staggered slide.
  const boxes = await page
    .locator(".tiles > .tile")
    .evaluateAll((els) => els.map((e) => ({ top: (e as HTMLElement).offsetTop, width: (e as HTMLElement).offsetWidth })));
  expect(boxes).toHaveLength(4);
  const width = page.viewportSize()!.width;
  if (width <= 720) {
    expect(boxes[0].top).toBe(boxes[1].top);
    expect(boxes[2].top).toBe(boxes[3].top);
    expect(boxes[3].width).toBeLessThan(width / 2);
  }
});

test("a user with only Spending sees no Put away tile", async ({ page }) => {
  await fakeApi(page, { spendingOnly: true });
  const wallets = page.waitForResponse((r) => r.url().includes("/api/wallets"));
  await page.goto("/accounting");
  await wallets;
  await expect(page.getByLabel("Received")).toContainText("4,200.00");
  await expect(page.getByLabel("Put away")).toHaveCount(0);
});

test("a move between wallets shows neutrally and is not counted as spending or income", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
  // The dashboard's totals leave it out ...
  await expect(page.getByLabel("Spent")).toContainText("37.40");
  await expect(page.getByLabel("Received")).toContainText("4,200.00");
  // ... but the latest few show where it went, with no + or − on the amount.
  const latest = page.getByRole("region", { name: "Latest" }).getByRole("listitem").filter({ hasText: "→ Investments" });
  await expect(latest).toContainText(/SGD.800\.00/);
  await expect(latest).not.toContainText(/[+−-]/);

  await page.goto("/accounting/ledger");
  const row = page.getByRole("row").filter({ hasText: "→ Investments" });
  await expect(row.getByRole("button", { name: "→ Investments", exact: true })).toBeVisible();
  await expect(row.locator("td.amount")).toContainText(/SGD.800\.00/);
  await expect(row.locator("td.amount")).not.toContainText(/[+−-]/);
  await expect(row.locator("td.amount")).toHaveClass(/amount-move/);
  await expect(row.locator(".badge-move")).toHaveText("Move");

  // Editing it keeps it a move: no direction toggle, no category.
  await row.getByRole("button", { name: "→ Investments", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Edit move" });
  await expect(sheet.getByText("→ Investments · not counted as spending or income")).toBeVisible();
  await expect(sheet.getByRole("group", { name: "Direction" })).toHaveCount(0);
  await expect(sheet.getByLabel("Category")).toHaveCount(0);
  await sheet.getByRole("button", { name: "Cancel" }).click();

  // It is neither money out nor money in.
  await page.getByRole("button", { name: "Money out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "→ Investments", exact: true })).toHaveCount(0);
});

test("add, edit and delete a wallet from Settings", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Wallets" });
  const yours = card.getByRole("list", { name: "Your wallets" });
  // Folded: a count and the names, until Manage opens the list.
  await expect(card.getByText("4 wallets")).toBeVisible();
  await expect(card.getByRole("list", { name: "Wallet names" }).getByText("Investments")).toBeVisible();
  await expect(yours).not.toBeVisible();
  await card.getByText("Manage", { exact: true }).click();
  await expect(card.getByRole("list", { name: "Wallet names" })).not.toBeVisible();
  const investments = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Investments" }) });
  await expect(investments.getByText("Investment", { exact: true })).toBeVisible();

  // Add one: Savings is the default kind, match words are optional.
  const add = card.getByRole("form", { name: "Add a wallet" });
  await expect(add.getByLabel("Kind")).toHaveValue("savings");
  await add.getByLabel("New wallet").fill("Emergency fund");
  await add.getByLabel("Match words (optional)").fill("efund");
  await add.getByRole("button", { name: "Add" }).click();
  const fund = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Emergency fund" }) });
  await expect(fund.getByText("Savings", { exact: true })).toBeVisible();
  await expect(fund.getByRole("list", { name: "Match words for Emergency fund" }).getByText("efund")).toBeVisible();

  await add.getByLabel("New wallet").fill("emergency fund");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(card.getByRole("alert")).toContainText("already exists");

  // Edit it: the name, the kind and the match words.
  await fund.getByRole("button", { name: "Edit" }).click();
  const edit = card.getByRole("form", { name: "Edit Emergency fund" });
  await edit.getByLabel("Name").fill("Rainy day fund");
  await edit.getByLabel("Kind").selectOption({ label: "Other" });
  await edit.getByLabel("Match words").fill("efund, rainy ,, ");
  await edit.getByRole("button", { name: "Save" }).click();
  const renamed = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Rainy day fund" }) });
  await expect(renamed.getByText("Other", { exact: true })).toBeVisible();
  const words = renamed.getByRole("list", { name: "Match words for Rainy day fund" });
  await expect(words.getByRole("listitem")).toHaveText(["efund", "rainy"]);

  // Deleting asks where its moves go, and says what that does to them.
  await renamed.getByRole("button", { name: "Delete" }).click();
  await expect(renamed.getByText("Delete Rainy day fund? Its moves go to")).toBeVisible();
  await expect(renamed.getByText("It has no moves.")).toBeVisible();
  await renamed.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(yours.getByRole("heading", { name: "Rainy day fund" })).toHaveCount(0);

  await investments.getByRole("button", { name: "Delete" }).click();
  await expect(investments.getByLabel("Move Investments moves to")).toHaveValue("w-savings");
  await expect(investments.getByText("1 move goes to Savings.")).toBeVisible();
  await investments.getByLabel("Move Investments moves to").selectOption({ label: "Spending" });
  await expect(investments.getByText("No moves go to Spending; 1 move between the two will be removed.")).toBeVisible();
  await investments.getByRole("button", { name: "Keep" }).click();
  await expect(yours.getByRole("heading", { name: "Investments" })).toBeVisible();
});

test("deleting a wallet re-points its moves at the one picked", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Wallets" });
  await card.getByText("Manage", { exact: true }).click();
  const yours = card.getByRole("list", { name: "Your wallets" });
  const investments = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Investments" }) });
  await investments.getByRole("button", { name: "Delete" }).click();
  await expect(investments.getByText("1 move goes to Savings.")).toBeVisible();
  await investments.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(yours.getByRole("heading", { name: "Investments" })).toHaveCount(0);

  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Moves", exact: true }).click();
  await expect(page.getByRole("button", { name: "→ Savings", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "→ Investments", exact: true })).toHaveCount(0);
});

test("Spending can be renamed but not deleted or given another kind", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Wallets" });
  await card.getByText("Manage", { exact: true }).click();
  const spending = card
    .getByRole("list", { name: "Your wallets" })
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: "Spending", exact: true }) });
  await expect(spending.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(spending.getByRole("button", { name: "Delete" })).toHaveCount(0);
  await spending.getByRole("button", { name: "Edit" }).click();
  const edit = card.getByRole("form", { name: "Edit Spending" });
  await expect(edit.getByLabel("Name")).toHaveValue("Spending");
  await expect(edit.getByLabel("Kind")).toHaveCount(0);
});

test("a move is added from the add sheet and shows under Moves, not in spending", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  await page.getByRole("dialog", { name: "Log money out" }).getByRole("button", { name: "Move", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Log a move" });
  await expect(sheet).toBeVisible();
  // No merchant or category on a move; it starts from Spending and can't go to itself.
  await expect(sheet.getByLabel("Paid to")).toHaveCount(0);
  await expect(sheet.getByLabel("Category")).toHaveCount(0);
  await expect(sheet.getByLabel("From")).toHaveValue("w-spending");
  await expect(sheet.getByLabel("To").locator("option")).toHaveText(["Pick a wallet", "Investments", "Savings", "Card"]);
  await sheet.getByLabel("Amount").fill("500");
  await sheet.getByLabel("To").selectOption({ label: "Savings" });
  await sheet.getByLabel("Notes").fill("September top-up");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();

  // Under Moves, with no + or − on the amount.
  await page.getByRole("button", { name: "Moves", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: "→ Savings" });
  await expect(row.locator("td.amount")).toContainText(/SGD.500\.00/);
  await expect(row.locator("td.amount")).not.toContainText(/[+−-]/);
  await expect(row).toContainText("September top-up");
  await expect(page.getByRole("button", { name: "→ Investments", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toHaveCount(0);

  // What was spent and received hasn't changed.
  await page.goto("/accounting");
  await expect(page.getByLabel("Spent")).toContainText("37.40");
  await expect(page.getByLabel("Received")).toContainText("4,200.00");
});

test("a move needs a second wallet, and the sheet says where to add one", async ({ page }) => {
  await fakeApi(page, { spendingOnly: true });
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  await page.getByRole("dialog", { name: "Log money out" }).getByRole("button", { name: "Move", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Log a move" });
  await expect(sheet.getByRole("link", { name: "Add a wallet in Settings first" })).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Save" })).toBeDisabled();
  await sheet.getByRole("link", { name: "Add a wallet in Settings first" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(sheet).toBeHidden();
});

test("an expense is turned into a move to a wallet, and leaves Money out", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Maxwell Food Centre", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await sheet.getByRole("button", { name: "This was a move to…" }).click();
  const ask = sheet.getByRole("group", { name: "Turn into a move" });
  // Spending itself isn't offered: a move goes to or from another wallet.
  await expect(ask.getByLabel("Wallet").locator("option")).toHaveText(["Investments", "Savings", "Card"]);
  await ask.getByLabel("Wallet").selectOption({ label: "Investments" });
  await expect(
    ask.getByText("Turn this into a move from Spending to Investments? It will stop counting as spending and lose its category."),
  ).toBeVisible();
  await ask.getByRole("button", { name: "Turn into a move" }).click();
  await expect(sheet).toBeHidden();

  await page.getByRole("button", { name: "Money out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Grab", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Moves", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: "Maxwell Food Centre" });
  await expect(row).toContainText("→ Investments");
  await expect(row.locator("td.amount")).not.toContainText(/[+−-]/);
  await expect(row.locator(".badge-move")).toHaveText("Move");
});

test("money in can be turned into a move from a wallet, and a split bill refuses", async ({ page }) => {
  await fakeApi(page, { splitBill: true });
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Employer", exact: true }).click();
  let sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await sheet.getByRole("button", { name: "This was a move to…" }).click();
  await sheet.getByLabel("Wallet").selectOption({ label: "Savings" });
  await expect(sheet.getByText("Turn this into a move from Savings to Spending? It will stop counting as income.")).toBeVisible();
  await sheet.getByRole("button", { name: "Keep as is" }).click();
  await expect(sheet.getByRole("button", { name: "This was a move to…" })).toBeVisible();
  await sheet.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Hotpot Place", exact: true }).click();
  sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await sheet.getByRole("button", { name: "This was a move to…" }).click();
  await sheet.getByRole("button", { name: "Turn into a move" }).click();
  await expect(sheet.getByRole("alert")).toContainText("split with others");
  await expect(sheet).toBeVisible();
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
  await page.goto("/accounting/ledger");
  await expect(page.getByRole("button", { name: "Kopi" })).toBeVisible();
});

test("bulk delete asks first and can be undone", async ({ page }, info) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
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
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
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
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
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
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
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
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Money in" }).click();
  await page.getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("menuitem", { name: "Export CSV" })).toHaveAttribute(
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
  await page.goto("/accounting/budgets");
  await expect(page.getByRole("heading", { name: "Budgets", level: 1 })).toBeVisible();
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

test("the budgets card shows total out and left to spend, with the lower of that and budget left marked", async ({ page }) => {
  const state = await fakeApi(page);
  state.budgets.push({ id: "b1", category_id: null, limit: 2000, spent: 600 });
  await page.goto("/accounting/budgets");
  const budgets = page.getByRole("region", { name: "Budgets" });
  const total = budgets.getByRole("group", { name: "Total out of Spending" });
  await expect(total).toContainText(/SGD.2,600\.00/);
  await expect(total).toContainText("spending plus moves to your wallets");
  const left = budgets.getByRole("group", { name: "Left to spend" });
  await expect(left).toContainText(/SGD.1,100\.00/);
  await expect(left).toContainText(/after what's still due this month \(SGD.1,300\.00\)/);
  await expect(left.getByText("Watch this")).toBeVisible();
  const budgetLeft = budgets.getByRole("group", { name: "Budget left" });
  await expect(budgetLeft).toContainText(/SGD.1,400\.00/);
  await expect(budgetLeft.getByText("Watch this")).toHaveCount(0);
  await expect(budgets.getByRole("note")).toHaveCount(0);
  // They sit under the overall budget, ahead of the form.
  const order = await budgets.locator(".budgets > li").evaluateAll((els) => els.map((e) => e.className));
  expect(order).toEqual(["budget", "budget-month"]);
});

test("without an overall budget the card still shows total out and left to spend, and a plan that outgrows income is flagged", async ({ page }) => {
  await fakeApi(page, { planWarning: true });
  await page.goto("/accounting/budgets");
  const budgets = page.getByRole("region", { name: "Budgets" });
  await expect(budgets.getByRole("group", { name: "Total out of Spending" })).toContainText(/SGD.2,600\.00/);
  await expect(budgets.getByRole("group", { name: "Left to spend" })).toContainText(/SGD.1,100\.00/);
  await expect(budgets.getByRole("group", { name: "Budget left" })).toHaveCount(0);
  await expect(budgets.getByText("Watch this")).toHaveCount(0);
  await expect(budgets.getByRole("note")).toContainText("add up to more than you usually bring in");
});

test("home says when less is left to spend than the budget shows", async ({ page }) => {
  const state = await fakeApi(page);
  state.budgets.push({ id: "b1", category_id: null, limit: 2000, spent: 600 });
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Nexus" })).toContainText(
    /Left to spend is SGD.1,100\.00 after what's still due — less than your SGD.1,400\.00 budget left\./,
  );
});

test("set when you're paid and your usual salary", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/budgets");
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
  await page.goto("/accounting/budgets");
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
  await page.goto("/accounting/budgets");
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
  await page.goto("/accounting/budgets");
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
  await page.goto("/accounting/ledger");
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
  await page.goto("/accounting/ledger");
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

test("Receipts by email is a Settings card before it is connected, then shows what happened to each email", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  await expect(page.getByRole("region", { name: "Category rules" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Receipts by email" }).getByText(/Not connected/)).toBeVisible();

  await fakeApi(page, { emailConnected: true });
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Receipts by email" });
  await expect(card.getByText("ann@gmail.com · 1 waiting for you")).toBeVisible();
  await card.getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/settings\/email$/);
  await expect(page.getByRole("heading", { name: "Receipts by email", level: 1 })).toBeVisible();

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
  await page.goto("/settings/email");
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
  await page.goto("/accounting/budgets");
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
  await page.goto("/accounting/cashflow");
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
  const pages = ["/", "/accounting", "/accounting/ledger", "/accounting/budgets", "/settings", "/settings/email", "/settings/import", "/settings/notifications", "/accounting/cashflow", "/investment", "/investment/watchlist", "/investment/stocks/AMD", "/investment/plans", "/investment/plans/p1", "/travel", "/travel/research/rs1"];
  for (const path of [...pages, "/connect/gmail?t=good"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const offenders = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      // A row that scrolls on purpose (the "Where to next" chips) keeps its overflow inside itself.
      const inScroller = (el: Element) => {
        for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
          if (["auto", "scroll"].includes(getComputedStyle(p).overflowX) && p.getBoundingClientRect().right <= width + 1) return true;
        }
        return false;
      };
      return [...document.querySelectorAll("body *")]
        .filter((el) => el.getBoundingClientRect().right > width + 1 && !inScroller(el))
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
  // The card starts folded: just the names, until Manage opens the list.
  await expect(card.getByRole("list", { name: "Category names" }).getByText("Dining Out")).toBeVisible();
  await expect(yours).not.toBeVisible();
  await card.getByText("Manage", { exact: true }).click();
  await expect(card.getByRole("list", { name: "Category names" })).not.toBeVisible();
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
  const card = page.getByRole("region", { name: "Categories" });
  await card.getByText("Manage", { exact: true }).click();
  const yours = card.getByRole("list", { name: "Your categories" });
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
  await card.getByText("Manage", { exact: true }).click();
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

test("the cog opens Settings, which is grouped, and Budgets keeps only budgeting", async ({ page }, info) => {
  await fakeApi(page);
  await page.goto("/accounting/budgets");
  await expect(page.getByRole("region", { name: "Budgets" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Categories" })).toHaveCount(0);
  // On a phone Settings is the cog at the top of Home; on a wide screen, in the rail.
  if (info.project.name === "mobile") await page.getByRole("link", { name: "Home" }).filter({ visible: true }).click();
  await page.getByRole("link", { name: "Settings" }).filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expect(page.locator("h2.section-title")).toHaveText(["Notifications", "Connections", "Your data"]);
  for (const name of ["Telegram updates", "Shared trips", "Receipts by email", "Import a statement", "Categories", "Wallets", "Category rules", "What Nexus remembers"])
    await expect(page.getByRole("region", { name })).toBeVisible();
});

test("import a bank statement: preview, tick, confirm, undo", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: "Import statement" }).click();
  await expect(page).toHaveURL(/\/settings\/import$/);
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
  await page.goto("/settings/import");
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
  await page.goto("/settings/import");
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
  await page.goto("/accounting/budgets");
  const where = info.project.name === "mobile" ? "Main (mobile)" : "Main";
  const nexus = page.getByRole("navigation", { name: where, exact: true }).getByRole("button", { name: "Ask Nexus", exact: true });
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
  await card.getByText("Manage", { exact: true }).click();
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
  await page.goto("/accounting/ledger");
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
  await page.goto("/accounting/ledger");
  const alert = page.getByRole("row").filter({ hasText: "Card alert" });
  await expect(alert.getByText(/^Possible duplicate of Grab Singapore/)).toBeVisible();
  await alert.getByRole("button", { name: "Merge" }).click();
  await expect(page.getByText(/^Merged into one: Grab Singapore/)).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Grab Singapore" })).toHaveCount(1);
  await expect(page.getByText(/^Possible duplicate/)).toHaveCount(0);
});

test("two payments flagged as one can be marked as two", async ({ page }) => {
  await fakeApi(page, { twins: true });
  await page.goto("/accounting/ledger");
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
    "/settings/email",
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
  // The chart and the budgets list are no longer on Home; the month, the portfolio and the next trip are at a glance.
  await expect(page.getByRole("list", { name: "Spending by month" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Budgets this month" })).toHaveCount(0);
  const money = page.getByRole("region", { name: "Money this month" });
  await expect(money).toContainText("SGD 37.40");
  await expect(money).toContainText("Last month by now:");
  await expect(money.getByRole("link", { name: "Details" })).toHaveAttribute("href", "/accounting");
  await expect(page.getByRole("region", { name: "Portfolio today" })).toContainText("No holdings yet");
  await expect(page.getByRole("region", { name: "Next trip" })).toContainText("No trip coming up");
});

test("the spending by month chart is on the Accounting overview", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
  const card = page.getByRole("region", { name: "Spending by month" });
  // Six months of spending, this month so far last; the tiles compare and explain.
  const months = card.getByRole("list", { name: "Spending by month" });
  await expect(months.getByRole("listitem")).toHaveCount(6);
  await expect(months.getByRole("listitem").last()).toContainText("Sep so far");
  // A usual month, rather than a comparison again; "Where it went" already names the biggest category.
  await expect(card.locator(".mini-tile").getByText("A usual month")).toBeVisible();
  await expect(card.getByText("Biggest category")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Where it went" })).toBeVisible();
  // Home no longer has it.
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Spending by month" })).toHaveCount(0);
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
  await page.getByRole("textbox", { name: "Ask Nexus", exact: true }).fill("how much on grab?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.locator(".msg-user").first()).toHaveText("how much on grab?");
  await expect(chat.locator(".msg-bot")).toHaveCount(1);
});

test("departments have their own pages, and old links still work", async ({ page, isMobile }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  await expect(page).toHaveURL(/\/accounting\/ledger$/);
  const tabs = page.getByRole("navigation", { name: "Accounting pages" });
  await expect(tabs.getByRole("link")).toHaveText(["Overview", "Ledger", "Budgets", "Cash flow"]);
  await tabs.getByRole("link", { name: "Budgets" }).click();
  await expect(page).toHaveURL(/\/accounting\/budgets$/);
  await expect(page.getByRole("heading", { name: "Budgets", level: 1 })).toBeVisible();
  const nav = page.getByRole("navigation", { name: isMobile ? "Main (mobile)" : "Main", exact: true });
  await nav.getByRole("link", { name: "Travel" }).click();
  await expect(page.getByRole("heading", { name: "Your trips", level: 1 })).toBeVisible();
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
  const glance = page.getByRole("region", { name: "Portfolio today" });
  await expect(glance).toContainText("SGD");
  await expect(glance.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/investment");
  await expect(page.getByRole("list", { name: "Largest holdings" })).toHaveCount(0);
});

test.describe("prices by market state", () => {
  // The labels show times in the browser's timezone: 14:41 UTC is 10:41pm in Singapore.
  test.use({ locale: "en-US", timezoneId: "Asia/Singapore" });

  const usd = (amount: string) => ({ amount, currency: "USD" });
  const nvda = [{ symbol: "NVDA", quantity: "10", average_cost: usd("118.4000"), cost: usd("1184.0000"), updated_at: "2026-09-28T03:00:00Z" }];

  test("prices are live while the market is open, provisional after the close, else the close", async ({ page, isMobile }) => {
    const state = await fakeApi(page);
    state.holdings = nvda;
    state.watching = ["AMD"];
    const holdings = page.getByRole("region", { name: "Holdings" });
    const watched = page.getByRole("list", { name: "Watched stocks" });
    const price = page.getByRole("region", { name: "Price", exact: true });
    const levels = price.getByRole("list", { name: "Price against its levels" });

    // Shut: the daily closes, with the day each is from.
    await page.goto("/investment");
    await expect(holdings.getByRole("row").filter({ hasText: "NVDA" })).toContainText("130.25");
    await expect(holdings).toContainText("Close of Fri, Sep 25");
    await expect(holdings).not.toContainText("Live");
    await expect(holdings).not.toContainText("provisional");
    // The table's caption says it once; on a phone each holding's card says it too, so a close is never taken for the price now.
    const nvdaPrice = holdings.getByRole("row").filter({ hasText: "NVDA" }).locator("td[data-label='Price'] .price-when");
    if (isMobile) await expect(nvdaPrice).toBeVisible();
    else await expect(nvdaPrice).toBeHidden();
    await expect(nvdaPrice).toContainText("Close of Fri, Sep 25");
    await page.goto("/investment/watchlist");
    await expect(watched).toContainText("AMD · USD 129.50");
    await expect(watched).toContainText("Close of Fri, Sep 25");
    await page.goto("/investment/stocks/AMD");
    await expect(price).toContainText("USD 129.50");
    await expect(price).toContainText("Close of Fri, Sep 25");
    await expect(levels).toContainText("1.2% below resistance at 131.00");
    await expect(levels).toContainText("10.4% above its 50-day average");

    // Open: the live quote and its time, with the day's change against the quote's own previous close.
    state.market = "open";
    await page.goto("/investment");
    await expect(holdings.getByRole("row").filter({ hasText: "NVDA" })).toContainText("131.50");
    await expect(holdings).toContainText("Live · 10:41pm");
    // The table's caption, and on a phone the holding's own card.
    await expect(holdings.locator(".live-dot:visible")).toHaveCount(isMobile ? 2 : 1);
    await page.goto("/investment/watchlist");
    await expect(watched).toContainText("AMD · USD 131.75");
    await expect(watched).toContainText("Live · 10:41pm");
    await page.goto("/investment/stocks/AMD");
    await expect(price).toContainText("USD 131.75");
    await expect(price).toContainText("Live · 10:41pm");
    await expect(levels).toContainText("0.6% above resistance at 131.00");

    // After the close, before the official bar: the last price, marked provisional.
    state.market = "after_close";
    await page.goto("/investment");
    await expect(holdings).toContainText("Close (provisional) · 10:41pm");
    await expect(holdings).not.toContainText("Live");
    await expect(holdings.locator(".live-dot")).toHaveCount(0);
    await expect(holdings.getByRole("row").filter({ hasText: "NVDA" })).toContainText("Close (provisional) · 10:41pm");
    await page.goto("/investment/watchlist");
    await expect(watched).toContainText("Close (provisional) · 10:41pm");
    await page.goto("/investment/stocks/AMD");
    await expect(price).toContainText("Close (provisional) · 10:41pm");

    // A later quote shows its own time and moves the facts.
    state.market = "open";
    state.quotes.AMD = { price: "129.00", prev_close: "129.50", quoted_at: "2026-09-28T15:30:00Z" };
    await page.goto("/investment/stocks/AMD");
    await expect(price).toContainText("Live · 11:30pm");
    await expect(levels).toContainText("1.6% below resistance at 131.00");
  });

  test("the Home portfolio card says when its total is from", async ({ page }) => {
    const state = await fakeApi(page);
    state.holdings = nvda;
    const card = page.getByRole("region", { name: "Portfolio today" });
    await page.goto("/");
    await expect(card).toContainText("Close of Fri, Sep 25");
    state.market = "open";
    await page.reload();
    await expect(card).toContainText("Live · 10:41pm");
    state.market = "after_close";
    await page.reload();
    await expect(card).toContainText("Close (provisional) · 10:41pm");
  });

  test("live prices refresh every minute and stop when the market is shut", async ({ page }) => {
    const state = await fakeApi(page);
    state.holdings = nvda;
    state.market = "open";
    let fetches = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/investments") fetches += 1;
    });
    await page.clock.install();
    await page.goto("/investment");
    const holdings = page.getByRole("region", { name: "Holdings" });
    await expect(holdings).toContainText("Live · 10:41pm");
    expect(fetches).toBe(1);

    // A newer quote arrives on the next minute without a reload.
    state.quotes.NVDA = { price: "132.10", prev_close: "130.25", quoted_at: "2026-09-28T14:42:00Z" };
    await page.clock.runFor(60_000);
    await expect(holdings).toContainText("132.10");
    await expect(holdings).toContainText("Live · 10:42pm");
    expect(fetches).toBe(2);

    // The market shuts: the next refresh shows the close, then nothing more is asked.
    state.market = "closed";
    await page.clock.runFor(60_000);
    await expect(holdings).toContainText("Close of Fri, Sep 25");
    const settled = fetches;
    await page.clock.runFor(5 * 60_000);
    expect(fetches).toBe(settled);
  });
});

test.describe("what moved today", () => {
  test.use({ locale: "en-US", timezoneId: "Asia/Singapore" });

  const usd = (amount: string) => ({ amount, currency: "USD" });
  const held = [
    { symbol: "NVDA", quantity: "10", average_cost: usd("118.4000"), cost: usd("1184.0000"), updated_at: "2026-09-28T03:00:00Z" },
    { symbol: "AMD", quantity: "25", average_cost: usd("110.0000"), cost: usd("2750.0000"), updated_at: "2026-09-28T03:00:00Z" },
  ];

  test("the Today card shows the session on Portfolio, live and after the close", async ({ page }) => {
    const state = await fakeApi(page);
    state.holdings = held;
    state.market = "open";
    await page.goto("/investment");
    const card = page.getByRole("region", { name: "Today", exact: true });
    await expect(card).toContainText("Live · 10:41pm");
    await expect(card.locator(".live-dot")).toHaveCount(1);
    await expect(card.locator(".today-change.up")).toContainText(/\+SGD\s89\.3[78]\s\+1\.51%/);
    const rows = card.getByRole("list", { name: "Biggest movers" }).getByRole("listitem");
    await expect(rows).toHaveCount(2);
    // The biggest move first, with its price, and a stock link.
    await expect(rows.nth(0)).toContainText("AMD");
    await expect(rows.nth(0)).toContainText("+1.74%");
    await expect(rows.nth(0)).toContainText("USD 131.75");
    await expect(rows.nth(0).getByRole("link", { name: "AMD" })).toHaveAttribute("href", "/investment/stocks/AMD");
    await expect(rows.nth(1)).toContainText("+0.96%");
    const headline = rows.nth(1).getByRole("link", { name: "Nvidia wins a big order" });
    await expect(headline).toHaveAttribute("href", "https://news.example/nvda/1");

    // After the close, before the official bar.
    state.market = "after_close";
    await page.reload();
    const closed = page.getByRole("region", { name: "Today's session" });
    await expect(closed).toContainText("Close (provisional) · 10:41pm");
    await expect(closed.locator(".live-dot")).toHaveCount(0);
    await expect(closed.getByRole("listitem")).toHaveCount(2);

    // Before the next open: only the last session's closes.
    state.market = "closed";
    await page.goto("/investment");
    const last = page.getByRole("region", { name: "Last session" });
    await expect(last).toContainText("Close of Fri, Sep 25");
    await expect(last.getByRole("listitem")).toHaveCount(1);
    await expect(last).toContainText("NVDA");
    await expect(last).toContainText("+1.76%");
  });

  test("Why did it move? answers in place, and says to wait after a 429", async ({ page }) => {
    const state = await fakeApi(page);
    state.holdings = held;
    state.market = "open";
    let limited = true;
    await page.route("**/api/investments/today/AMD/why", async (route) => {
      if (!limited) return route.fallback();
      limited = false;
      return route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "Too many requests" }) });
    });
    await page.goto("/investment");
    const card = page.getByRole("region", { name: "Today", exact: true });
    const nvda = card.getByRole("listitem").filter({ hasText: "NVDA" });
    await nvda.getByRole("button", { name: "Why did it move?" }).click();
    await expect(nvda).toContainText("Nvidia won a big order, which may explain the rise.");
    await expect(nvda).toContainText("From today's headlines");
    await expect(nvda.getByRole("button")).toHaveCount(0);
    expect(state.whyAsked).toEqual({ NVDA: 1 });

    const amd = card.getByRole("listitem").filter({ hasText: "AMD" });
    await amd.getByRole("button", { name: "Why did it move?" }).click();
    await expect(amd.getByRole("alert")).toHaveText("Try again in a minute");
    await amd.getByRole("button", { name: "Why did it move?" }).click();
    await expect(amd).toContainText("No headlines from today explain the move in AMD.");
    // The other row kept its answer.
    await expect(nvda).toContainText("Nvidia won a big order");
  });

  test("the Today card is hidden when nothing is held or watched", async ({ page }) => {
    const state = await fakeApi(page);
    state.market = "open";
    await page.goto("/investment");
    await expect(page.getByRole("heading", { name: "Portfolio", level: 1 })).toBeVisible();
    await expect(page.getByRole("region", { name: "Holdings" })).toBeVisible();
    await expect(page.getByRole("region", { name: /Today|Last session/ })).toHaveCount(0);
    await page.goto("/");
    await expect(page.getByRole("region", { name: "Portfolio today" })).toBeVisible();
    await expect(page.getByRole("region", { name: /Today|Last session/ })).toHaveCount(0);
  });

  test("Home has no Today card; the Portfolio page keeps it", async ({ page }) => {
    const state = await fakeApi(page);
    state.holdings = held;
    state.market = "open";
    await page.goto("/");
    await expect(page.getByRole("region", { name: "Portfolio today" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Biggest movers" })).toHaveCount(0);
    await page.goto("/investment");
    await expect(page.getByRole("list", { name: "Biggest movers" })).toBeVisible();
  });
});

test("big move alerts, quiet hours and the morning summary are saved one field at a time", async ({ page }) => {
  await fakeApi(page);
  const puts: unknown[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" && new URL(request.url()).pathname === "/api/notifications") puts.push(request.postDataJSON());
  });
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Telegram updates" });
  await expect(card.getByLabel("From", { exact: true })).toHaveValue("23:00");
  await expect(card.getByLabel("To", { exact: true })).toHaveValue("08:00");
  await expect(card.getByLabel("Big move alerts (%)")).toHaveValue("5");
  await expect(card.getByRole("switch", { name: "Morning investment summary" })).toBeChecked();
  await expect(card.getByText("Nexus holds its messages in these hours. A broken stop on a stock you hold still comes through.")).toBeVisible();
  await expect(card.getByText("At 8am after each US trading day.")).toBeVisible();

  await card.getByLabel("From", { exact: true }).fill("22:30");
  await expect.poll(() => puts).toEqual([{ quiet_start: "22:30" }]);
  await card.getByLabel("To", { exact: true }).fill("07:15");
  await expect.poll(() => puts).toEqual([{ quiet_start: "22:30" }, { quiet_end: "07:15" }]);

  const move = card.getByLabel("Big move alerts (%)");
  await move.fill("8");
  await move.press("Enter");
  await expect.poll(() => puts.length).toBe(3);
  expect(puts[2]).toEqual({ move_alert_percent: 8 });

  await card.getByRole("switch", { name: "Morning investment summary" }).click();
  await expect(card.getByRole("switch", { name: "Morning investment summary" })).not.toBeChecked();
  await expect.poll(() => puts.length).toBe(4);
  expect(puts[3]).toEqual({ market_summary: false });

  // All of it is still there after a reload.
  await page.reload();
  await expect(card.getByLabel("From", { exact: true })).toHaveValue("22:30");
  await expect(card.getByLabel("To", { exact: true })).toHaveValue("07:15");
  await expect(card.getByLabel("Big move alerts (%)")).toHaveValue("8");
  await expect(card.getByRole("switch", { name: "Morning investment summary" })).not.toBeChecked();

  // A threshold the server refuses is shown and not kept.
  await move.fill("40");
  await move.press("Enter");
  await expect(card.getByRole("alert")).toContainText("a big move can be 1.0% to 20.0% in a day");
  await expect(move).toHaveValue("8");
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

test("a plan can be kept fresh from its page, and the list tags it", async ({ page }) => {
  const state = await fakeApi(page);
  state.planStarted = true;
  await page.goto("/investment/plans/p1");
  // The price the plan was written with, and when it was from.
  await expect(page.getByText("Price 129.50", { exact: true })).toBeVisible();
  await expect(page.locator(".plan-price")).toContainText("Close of");
  const fresh = page.getByRole("region", { name: "Keep this plan fresh" });
  await expect(fresh).toContainText("Nexus re-runs it when the price moves a lot, after earnings, or once a week.");
  const toggle = fresh.getByRole("checkbox", { name: "Keep this plan fresh" });
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await expect.poll(() => state.planKeepFresh).toBe(true);
  await expect(toggle).toBeChecked();
  await page.locator(".page-head").getByRole("link", { name: "Trade plans", exact: true }).click();
  await expect(page.getByRole("link", { name: /AMD: Wait for a dip to buy/ })).toContainText("Fresh");
  // The finished plan is never tagged.
  await expect(page.getByRole("link", { name: /MSFT: Keep holding/ })).not.toContainText("Fresh");
  // Off again: the tag goes.
  await page.getByRole("link", { name: /AMD: Wait for a dip to buy/ }).click();
  await page.getByRole("checkbox", { name: "Keep this plan fresh" }).uncheck();
  await expect.poll(() => state.planKeepFresh).toBe(false);
  await page.locator(".page-head").getByRole("link", { name: "Trade plans", exact: true }).click();
  await expect(page.getByRole("link", { name: /AMD: Wait for a dip to buy/ })).not.toContainText("Fresh");
});

test("a refreshed plan links back to the one it replaced, and the old one to the new", async ({ page }) => {
  const state = await fakeApi(page);
  state.planStarted = true;
  state.planRefreshed = true;
  await page.goto("/investment/plans/p1");
  await page.getByRole("link", { name: /^Refreshed from the plan of/ }).click();
  await expect(page).toHaveURL(/\/investment\/plans\/p2$/);
  // The old plan says it was refreshed, can't be kept fresh, and points forward.
  await expect(page.getByRole("region", { name: "How it's going" })).toContainText("Refreshed");
  await expect(page.getByRole("checkbox", { name: "Keep this plan fresh" })).toHaveCount(0);
  await page.getByRole("link", { name: "A newer plan replaced this one" }).click();
  await expect(page).toHaveURL(/\/investment\/plans\/p1$/);
  // In the list the old plan is labelled, not scored.
  await page.locator(".page-head").getByRole("link", { name: "Trade plans", exact: true }).click();
  const list = page.getByRole("list", { name: "Trade plans" });
  await expect(list.getByRole("link", { name: /AMD: Wait for a pullback/ })).toContainText("Refreshed");
  await expect(page.getByRole("region", { name: "Track record" }).getByLabel("Plan results")).toContainText("Hit target1");
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
  await expect(page).toHaveURL(/\/travel\/trips\/trip1(\?.*)?$/);
}

type TripTab = "Plan" | "Ideas" | "Money" | "Prep";

/** Opens one of the trip page's four tabs and checks it is the one showing. */
async function openTab(page: Page, name: TripTab) {
  const tab = page.getByRole("navigation", { name: "Trip sections" }).getByRole("button", { name, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-current", "page");
}

/** Opens one section of the Money tab's Details (one is open at a time) and returns it. */
async function openSection(page: Page, name: string) {
  const header = page.getByRole("button", { name: new RegExp(`^${name}`) });
  if ((await header.getAttribute("aria-expanded")) !== "true") await header.click();
  await expect(header).toHaveAttribute("aria-expanded", "true");
  return page.getByRole("region", { name, exact: true });
}

/** The trip page's + for the open tab: a floating button on a phone, a button in the header beside Share on a wide screen. */
const tripAdd = (page: Page) => page.locator(".trip-fab-button, .trip-add-desktop").filter({ visible: true });

/** The Itinerary card on the Plan tab. */
const itineraryOf = (page: Page) => page.getByRole("region", { name: "Itinerary" });

/** A tap on a plan row opens it (a tap while the days are still sliding is ignored, so it is
 * retried until the row is open); Change in the open row opens the editor. */
async function openEntry(page: Page, title: string) {
  const itinerary = itineraryOf(page);
  const row = itinerary.getByRole("button", { name: `Open ${title}`, exact: true });
  await expect(async () => {
    if ((await row.getAttribute("aria-expanded", { timeout: 1000 })) !== "true") await row.click({ timeout: 1000 });
    await expect(row).toHaveAttribute("aria-expanded", "true", { timeout: 1000 });
  }).toPass();
}

async function editEntry(page: Page, title: string) {
  await openEntry(page, title);
  await itineraryOf(page).getByRole("button", { name: `Change ${title}`, exact: true }).click();
}

/** The trip's add sheet, opened from the open tab's +. */
async function openAddSheet(page: Page, trip: string) {
  await tripAdd(page).click();
  const sheet = page.getByRole("dialog", { name: `Add to ${trip}` });
  await expect(sheet).toBeVisible();
  return sheet;
}


test("a trip is added and shows its spending, set-aside and settle-up", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/travel");
  // With no trips the page leads with "Where to next?", not a second card saying the same.
  await expect(page.getByRole("heading", { name: "Where to next?" })).toBeVisible();
  await expect(page.getByText(/No trips yet/)).toHaveCount(0);
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
  // Names typed and left behind (no Enter) still join the list when the field is left.
  await form.getByLabel("Add a traveller").fill("Ann, Ben");
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
  // The cover photo is credited as its licence asks, linking to its page: an info button shows the credit.
  await page.getByRole("button", { name: "Photo credit" }).click();
  const credit = page.getByRole("link", { name: /Photo: A\. Photographer, CC BY-SA 4\.0/ });
  await expect(credit).toHaveAttribute("href", "https://commons.wikimedia.org/wiki/File:Example.jpg");
  await expect(credit).toHaveAttribute("rel", /noopener/);
  // Weeks out, the page opens on Plan, with the one thing to sort next in the strip under the cover.
  const nav = page.getByRole("navigation", { name: "Trip sections" });
  await expect(nav.getByRole("button", { name: "Plan", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "Next up" })).toContainText("9 nights without a place to stay");
  await expect(itineraryOf(page)).toContainText("ZZ12 SIN → NRT");
  await expect(itineraryOf(page)).toContainText("08:25 → 16:05");
  // Prep keeps everything still to sort (in Getting ready), and Money the money in one card.
  await openTab(page, "Prep");
  await expect(page.getByRole("region", { name: "Getting ready" })).toContainText("9 nights without a place to stay");
  await openTab(page, "Money");
  const summary = page.getByRole("region", { name: "Spent and booked", exact: true });
  await expect(summary).toContainText("SGD 1,638.00");
  await expect(summary).toContainText("of SGD 3,000.00");
  await expect(summary).toContainText("Spent SGD 818.00 · Booked SGD 820.00 · Planned SGD 582.00");
  await expect(summary).toContainText("Left after planned costs SGD 780.00");
  // What needs doing with the people going comes next.
  await expect(page.getByRole("region", { name: "To do" })).toContainText("Ann owes you");

  // The rest is in Details, one section open at a time.
  const spending = await openSection(page, "Where it goes");
  await expect(spending).toContainText("SGD 800.00 was spent before the trip");
  // A category opens to the trip expenses behind it.
  await spending.getByRole("button", { name: /^Dining Out:/ }).click();
  await expect(spending.getByRole("list", { name: "Dining Out expenses" })).toContainText("Ichiran");
  await expect(spending.getByRole("list", { name: "Dining Out expenses" })).not.toContainText("Air ticket");
  await openSection(page, "Planned costs");
  await expect(page.getByRole("list", { name: "Planned costs" })).toContainText("Dining Out");
  await expect(spending).toHaveCount(0); // opening another section closes this one
  await expect(await openSection(page, "Setting money aside")).toContainText("SGD 1,500.00 each payday would cover it");
  await expect(await openSection(page, "Bookings paid")).toContainText("SGD 820.00 not logged as an expense yet");
  const expenses = await openSection(page, "Expenses");
  await expect(expenses.getByText("added by hand")).toBeVisible();
  await expenses.getByRole("button", { name: "Take Air ticket off the trip" }).click();
  await expect(expenses.getByText("Air ticket")).toHaveCount(0);
  await expect.poll(() => state.tripItems).toEqual(["k1"]);

  await page.goto("/");
  const trip = page.getByRole("region", { name: "Next trip" });
  await expect(trip).toContainText("Tokyo in 43 days");
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
  const estimate = page.getByRole("region", { name: "Estimated cost" });
  await expect(estimate).toContainText("SGD 4,602–6,760");
  await expect(estimate).toContainText("for 7 nights, 2 travellers");
  await expect(estimate).toContainText("Fits your budget of SGD 6,800");
  await expect(estimate).toContainText("It fits your cash flow");
  const costs = page.getByRole("region", { name: "Costs" });
  await expect(costs).toContainText("JPY 8,000–15,000 · SGD 72–135");
  await expect(costs.getByRole("link", { name: "[2]" })).toHaveAttribute("href", "https://flights.example.com/s");
  // The sources are folded away until asked for.
  const sources = page.getByRole("region", { name: /^Sources/ });
  await expect(sources.getByRole("link", { name: "Tokyo guide" })).toBeHidden();
  await sources.getByRole("button", { name: "Sources · 2" }).click();
  await expect(sources.getByRole("link", { name: "Tokyo guide" })).toHaveAttribute("rel", /noopener/);
  await page.getByRole("button", { name: "Make it a trip" }).click();
  // The trip is made; the areas' ideas are asked about before leaving, and "Not now" goes on.
  await expect(page.getByRole("heading", { name: "Add the ideas from these areas to the trip too?" })).toBeVisible();
  await page.getByRole("button", { name: "Not now" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip9$/);
  await expect.poll(() => state.trips[0]).toMatchObject({ destination: "Tokyo", currency: "JPY" });
  expect(state.researchIdeaPosts).toEqual([]);
});

test("plans are added to a trip's itinerary by hand, day by day, and changed", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-19", (form) => form.getByLabel("Notes").fill("Pack an adapter"));
  await expect.poll(() => state.trips[0]).toMatchObject({ destination: "Tokyo", notes: "Pack an adapter" });

  // One + button, one sheet: here, the short form for a plan on a day.
  const sheet = await openAddSheet(page, "Tokyo");
  await sheet.getByRole("button", { name: /A plan/ }).click();
  const entry = page.getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Dinner at Sushi Ten");
  await entry.getByLabel(/^Day/).selectOption("2026-11-12");
  await entry.getByLabel("Time", { exact: true }).fill("19:00");
  // The rest of the details wait under "More details".
  await expect(entry.getByLabel("Where", { exact: true })).toBeHidden();
  await entry.getByText("More details").click();
  await entry.getByLabel("Where", { exact: true }).fill("1-2-3 Ginza");
  await entry.getByRole("button", { name: "Add" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const itinerary = itineraryOf(page);
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("Dinner at Sushi Ten");
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("19:00");
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Dinner at Sushi Ten", day: "2026-11-12", at: "19:00", address: "1-2-3 Ginza" });

  // Tap the entry to change it, in place: no separate Edit button or menu, so the timeline reads cleanly.
  await itinerary.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ }).click();
  await expect(itinerary.getByRole("button", { name: "Edit Dinner at Sushi Ten" })).toHaveCount(0);
  // A tap opens the row (address, Change) without the editor; a second tap folds it.
  const dinner = itinerary.getByRole("button", { name: "Open Dinner at Sushi Ten", exact: true });
  await expect(itinerary.getByRole("button", { name: "Change Dinner at Sushi Ten" })).toHaveCount(0);
  await openEntry(page, "Dinner at Sushi Ten");
  await expect(dinner).toHaveAttribute("aria-expanded", "true");
  await expect(itinerary.getByRole("form", { name: "Change the entry" })).toHaveCount(0);
  await expect(itinerary.getByRole("button", { name: "Change Dinner at Sushi Ten" })).toBeVisible();
  await expect(itinerary).toContainText("1-2-3 Ginza");
  await dinner.click({ position: { x: 6, y: 3 } }); // the open part below takes its own taps
  await expect(dinner).toHaveAttribute("aria-expanded", "false");
  await expect(itinerary.getByRole("button", { name: "Change Dinner at Sushi Ten" })).toHaveCount(0);
  await editEntry(page, "Dinner at Sushi Ten");
  const edit = itinerary.getByRole("form", { name: "Change the entry" });
  await edit.getByLabel("Time", { exact: true }).fill("20:00");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(itinerary.getByRole("list", { name: /^Day 3/ })).toContainText("20:00");

  page.once("dialog", (d) => void d.accept());
  await editEntry(page, "Dinner at Sushi Ten");
  await itinerary.getByRole("form", { name: "Change the entry" }).getByRole("button", { name: "Remove" }).click();
  await expect(itinerary).not.toContainText("Dinner at Sushi Ten");
  await expect.poll(() => state.plans).toEqual([]);

  // A night without a place to stay shows on its day, and Add there starts the stay.
  await itinerary.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /10/ }).click();
  await itinerary.getByRole("button", { name: /^Add a place to stay on/ }).first().click();
  await expect(entry.getByLabel("Check in")).toHaveValue("2026-11-10");
  await entry.getByLabel("Name", { exact: true }).fill("Hotel Kawa");
  await entry.getByLabel("Check out").fill("2026-11-13");
  await entry.getByRole("button", { name: "Add" }).click();
  await expect(itinerary.locator(".day-stay").filter({ hasText: "Hotel Kawa" })).toHaveCount(3); // the nights of the 10th, 11th and 12th
  await expect(itinerary.getByRole("list", { name: /^Day 4/ })).toContainText("Check out");
  await expect.poll(() => state.plans[0]).toMatchObject({ check_in: "2026-11-10", check_out: "2026-11-13" });
});

test("a booking is added by typing it, and Nexus asks before saving", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-15");
  // The strip under the cover starts the stay as a booking; typing it is one of the quick ways.
  await page.getByRole("region", { name: "Next up" }).getByRole("button", { name: /^Add: .*nights without a place to stay/ }).click();
  await page.getByRole("dialog", { name: "Add a booking" }).getByRole("button", { name: "Back to the ways to add" }).click();
  await page.getByRole("dialog", { name: "Add to Tokyo" }).getByRole("button", { name: "Type it" }).click();
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
  const itinerary = itineraryOf(page);
  const sheet = await openAddSheet(page, "Tokyo");
  await sheet.getByLabel("Screenshot or photo").setInputFiles({
    name: "booking.png",
    mimeType: "image/png",
    buffer: Buffer.from("made-up image bytes"),
  });
  const imported = page.getByRole("status", { name: "Imported from a screenshot" });
  await expect(imported).toContainText("Added to your Tokyo trip");
  await expect(imported).toContainText("Does everything look right?");
  await openEntry(page, "Hotel Kumo, 3 nights");
  await expect(itinerary).toContainText("Booked on Agoda · Ref 9876543210");
  await expect(itinerary.getByRole("button", { name: "Copy reference 9876543210" })).toBeVisible();
  await imported.getByRole("button", { name: "Looks right" }).click();
  await expect(imported).toHaveCount(0);
  await expect.poll(() => state.plans[0]).toMatchObject({ hotel: "Hotel Kumo", reference: "9876543210" });
  // The flight's own booking (from an email) is there when its row is opened.
  await openEntry(page, "ZZ12 SIN → NRT");
  await expect(itinerary).toContainText("Booked on Acme Air · Ref ZK4P7Q");
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

  // What's still to sort waits on Prep, and the strip under the cover says the first thing.
  await expect(page.getByRole("region", { name: "Next up" })).toContainText("3 nights without a place to stay");
  await openTab(page, "Prep");
  const toSort = page.getByRole("region", { name: "Getting ready" });
  await expect(toSort).toContainText("3 nights without a place to stay");
  await expect(toSort).toContainText("No budget yet");
  // Set opens the trip to add a budget.
  await toSort.getByRole("button", { name: "Set: No budget yet" }).click();
  await expect(page.getByRole("form", { name: "Change the trip" })).toBeVisible();
  await page.getByRole("form", { name: "Change the trip" }).getByRole("button", { name: "Cancel" }).click();

  // An idea, a place to visit, from the Ideas tab's +, kept without a day.
  await openTab(page, "Ideas");
  await tripAdd(page).click();
  const sheet = page.getByRole("dialog", { name: "Add an idea" });
  const entry = sheet.getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Namdaemun Market");
  await entry.getByLabel("Kind").fill("Shopping");
  await entry.getByRole("button", { name: "Add" }).click();
  const places = page.getByRole("list", { name: "Ideas" });
  await expect(places).toContainText("Namdaemun Market");
  await expect(places).toContainText("Shopping");
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Namdaemun Market", day: null, category: "Shopping" });

  // Then given a day, it moves onto the itinerary.
  await places.getByRole("button", { name: "Put Namdaemun Market on a day" }).click();
  const pick = page.getByRole("dialog", { name: "Put on a day" });
  await pick.getByRole("region", { name: "All days" }).getByRole("button", { name: /^Day 2 ·/ }).click();
  await expect(page.getByRole("list", { name: "Ideas" })).toHaveCount(0);
  await expect.poll(() => state.moves).toEqual(["pl1>2026-11-11@first"]);
  await openTab(page, "Plan");
  const itinerary = itineraryOf(page);
  await expect(itinerary.getByRole("list", { name: /^Day 2/ })).toContainText("Namdaemun Market");

  // Days get a label, like the city.
  await expect(itinerary.getByRole("navigation", { name: "Days" }).getByRole("button")).toHaveCount(4);
  await itinerary.getByRole("button", { name: "Name this day" }).first().click();
  await itinerary.getByPlaceholder("City or plan, e.g. Busan").fill("Myeongdong");
  await itinerary.getByRole("button", { name: "Save" }).click();
  await expect(itinerary.getByRole("heading", { name: /^Day 1/ })).toContainText("Myeongdong");
  await expect.poll(() => state.trips[0]).toMatchObject({ day_labels: { "2026-11-10": "Myeongdong" } });
});

test("places from Google Maps: saved, linked, rated, and flagged when usually closed", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");

  // Found on Google Maps and saved as an idea, with its place kept. Finding is the Find ideas button at the top of Ideas, in a sheet.
  await openTab(page, "Ideas");
  await page.getByRole("button", { name: "Find ideas", exact: true }).click();
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Results" });
  await expect(results).toContainText("Hanok Noodle Bar");
  await expect(results).toContainText("Rated 4.6 (2,310)");
  await expect.poll(() => state.placeSearches).toEqual(["noodles"]);
  // One word reads as a name: only Google Maps is asked; ideas are a tap away.
  await expect(page.getByRole("button", { name: /Ideas from guides and articles/ })).toBeVisible();
  expect(state.ideaSearches).toEqual([]);
  await results.getByRole("button", { name: "Save: Hanok Noodle Bar" }).click();
  // The sheet stays open, with the result marked saved, so several can be kept.
  await expect(results.getByRole("button", { name: "Hanok Noodle Bar is saved" })).toBeDisabled();
  await page.keyboard.press("Escape");
  const places = page.getByRole("list", { name: "Ideas" });
  await expect(places).toContainText("Hanok Noodle Bar");
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Hanok Noodle Bar", category: "Noodle shop", place_id: "fakePlaceNoodle01" });
  // Its row opens to show the rating and details.
  await places.getByRole("button", { name: /^Hanok Noodle Bar/ }).click();
  await expect(places.getByLabel("Rated 4.6 out of 5 from 2310 ratings")).toBeVisible();

  // Its details: a summary, reviews credited to their authors, and Google Maps.
  await places.getByRole("button", { name: "Show details for Hanok Noodle Bar" }).click();
  const reviews = places.getByRole("list", { name: "Reviews of Hanok Noodle Bar" });
  await expect(reviews).toContainText("The broth is worth the queue.");
  await expect(reviews.getByRole("link", { name: "A. Reviewer" })).toHaveAttribute("rel", /noopener/);
  await expect(places).toContainText("From Google Maps");

  // Put on a Thursday, when it's usually shut: the itinerary says so.
  await places.getByRole("button", { name: "Put Hanok Noodle Bar on a day" }).click();
  await page.getByRole("dialog", { name: "Put on a day" }).getByRole("region", { name: "All days" }).getByRole("button", { name: /^Day 3 ·/ }).click();
  await expect(page.getByRole("list", { name: "Ideas" })).toHaveCount(0);
  await expect.poll(() => state.plans[0]).toMatchObject({ day: "2026-11-12", place_id: "fakePlaceNoodle01" });
  await openTab(page, "Plan");
  // Seen on the folded plan, and once (with the place's details) when it's opened.
  await expect(itineraryOf(page).getByRole("note")).toHaveText("Usually closed on Thursdays");
  await openEntry(page, "Hanok Noodle Bar");
  await expect(itineraryOf(page).getByRole("note")).toHaveText("Usually closed on Thursdays");

  // A place added by hand is linked to Google Maps from its row.
  await openTab(page, "Ideas");
  await tripAdd(page).click();
  const entry = page.getByRole("dialog", { name: "Add an idea" }).getByRole("form", { name: "Add to the itinerary" });
  await entry.getByLabel("Name", { exact: true }).fill("Namdaemun Market");
  await entry.getByRole("button", { name: "Add" }).click();
  await places.getByRole("button", { name: /^Namdaemun Market/ }).click();
  await places.getByRole("button", { name: "Find Namdaemun Market on Google Maps" }).click();
  await expect(page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for")).toHaveValue("Namdaemun Market");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Link: Namdaemun Market" }).click();
  await expect(places.getByLabel("Rated 4.3 out of 5 from 18000 ratings")).toBeVisible();
  await expect.poll(() => state.plans[1]).toMatchObject({ name: "Namdaemun Market", place_id: "fakePlaceMarket01" });
});

test("a plan with no place says there is no travel time, and linking one brings it", async ({ page }) => {
  const state = await fakeApi(page);
  state.mapKey = "test-browser-key";
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  const plan = (id: string, name: string, at: string, place: string | null) => ({
    id, trip_id: "trip1", kind: "activity", title: name, provider: null, starts: "2026-11-12", ends: "2026-11-12",
    segments: [], hotel: null, address: null, check_in: null, check_out: null, name, day: "2026-11-12", at, note: null,
    cost: null, logged: false, manual: true, reference: null, booked_via: null, category: null, place_id: place, scheduled: true,
  });
  // Day 3: two linked plans, then one with no place (the last, so the caption goes before it).
  state.plans.push(plan("pl1", "Hanok Noodle Bar", "12:00", "fakePlaceNoodle01"), plan("pl2", "Namdaemun Market", "14:00", null));
  await page.reload();
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ }).click();
  await page.getByRole("heading", { name: /^Day 3 of \d+ ·/ }).scrollIntoViewIfNeeded();

  // No travel time next to it, and a way to link a place; the linked plan has no such line.
  const quiet = itineraryOf(page).getByRole("listitem", { name: "Travel time for Namdaemun Market" });
  await expect(quiet).toContainText(/No travel time: Namdaemun Market isn’t on the map ·\s+link a place/);
  await expect(itineraryOf(page).getByText("No travel time")).toHaveCount(1);
  await expect(itineraryOf(page).getByRole("listitem", { name: /^From / })).toHaveCount(0);

  // The place finder opens for that plan; linking a place brings the travel time in its place.
  await quiet.getByRole("button", { name: "Link a place for Namdaemun Market" }).click();
  await expect(page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for")).toHaveValue("Namdaemun Market");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Link: Namdaemun Market" }).click();
  await expect.poll(() => state.plans[1]).toMatchObject({ place_id: "fakePlaceMarket01" });
  await expect(itineraryOf(page).getByRole("listitem", { name: "From Hanok Noodle Bar to Namdaemun Market" })).toContainText("14 min walk");
  await expect(itineraryOf(page).getByText("No travel time")).toHaveCount(0);
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

  // Weather for the dates, credited to its source. Getting ready lives on Prep.
  await openTab(page, "Prep");
  const weather = page.getByRole("region", { name: "Weather in Seoul, Exampleland" });
  await expect(weather).toContainText("Typical for these dates, last 3 years");
  await expect(weather.getByRole("img", { name: "Light rain" })).toBeVisible();
  await expect(weather.getByRole("link", { name: "Weather data by Open-Meteo.com" })).toHaveAttribute("rel", /noopener/);

  // Packing: suggested, then ticked off and added to.
  const packing = page.getByRole("region", { name: "Packing list" });
  await packing.getByRole("button", { name: "Suggest", exact: true }).click();
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

  // A place found on Google Maps from the add sheet is kept as an idea; on a day, it shows its photo, credited, on the itinerary.
  await openTab(page, "Plan");
  const sheet = await openAddSheet(page, "Seoul");
  await sheet.getByRole("button", { name: /Find a place/ }).click();
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("list", { name: "Results" }).getByRole("button", { name: "Save: Hanok Noodle Bar" }).click();
  await page.keyboard.press("Escape");
  await openTab(page, "Ideas");
  await page.getByRole("list", { name: "Ideas" }).getByRole("button", { name: "Put Hanok Noodle Bar on a day" }).click();
  await page.getByRole("dialog", { name: "Put on a day" }).getByRole("region", { name: "All days" }).getByRole("button", { name: /^Day 2 ·/ }).click();
  await openTab(page, "Plan");
  const itinerary = itineraryOf(page);
  await itinerary.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /3/ }).click();
  // The photo stays folded until the plan's details are opened.
  await expect(itinerary.getByRole("img", { name: "Hanok Noodle Bar" })).toHaveCount(0);
  await openEntry(page, "Hanok Noodle Bar");
  await itinerary.getByRole("button", { name: "Show details for Hanok Noodle Bar" }).click();
  await expect(itinerary.getByRole("img", { name: "Hanok Noodle Bar" })).toBeVisible();
  await expect(itinerary.getByRole("link", { name: "Photo by A. Photographer, Google Maps" })).toHaveAttribute("href", "https://maps.example/u/2");
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

test("a trip's day is one panel: its weather, tonight's stay, and the plans to edit", async ({ page }) => {
  const state = await fakeApi(page);
  // On now: the page opens on today (the made-up first day).
  await addTrip(page, "Tokyo", "2026-09-25", "2026-09-28");
  const entry = { trip_id: "trip1", provider: null, segments: [], name: null, day: null, at: null, note: null, cost: null, booked_via: null, category: null, place_id: null, scheduled: true, logged: false, manual: true };
  state.plans.push(
    { ...entry, id: "pl1", kind: "hotel", title: "Hotel Kumo", hotel: "Hotel Kumo", starts: "2026-09-25", ends: "2026-09-28", check_in: "2026-09-25", check_out: "2026-09-28", address: "1-2-3 Example-cho, Tokyo", reference: "HK55821", booked_via: "Agoda" },
    { ...entry, id: "pl2", kind: "activity", title: "Fish market breakfast", name: "Fish market breakfast", starts: "2026-09-26", ends: "2026-09-26", day: "2026-09-26", at: "07:30", address: "4-5 Market St, Tokyo", hotel: null, check_in: null, check_out: null, reference: null, note: "Go early" },
  );
  await page.reload();

  // While the trip is on, Plan opens on the day, and the spending is a tab away.
  await expect(page.getByRole("navigation", { name: "Trip sections" }).getByRole("button", { name: "Plan", exact: true })).toHaveAttribute("aria-current", "page");
  const day1 = page.getByRole("group", { name: /^Day 1 · .*, 1 of \d+$/ });
  await expect(day1.getByRole("heading", { name: /^(Today · )?Day 1 of 4 · / })).toContainText("25");
  // The weather on a line, and the night's stay as a strip with Maps and Copy; the rest folded.
  await expect(day1.locator(".day-weather")).toContainText("rain");
  const stay = day1.locator(".day-stay");
  await expect(stay).toContainText("Hotel Kumo");
  await expect(stay.getByRole("link", { name: "Open Hotel Kumo in Maps" })).toBeVisible();
  await expect(stay.getByRole("button", { name: "Copy the address of Hotel Kumo" })).toBeVisible();
  await expect(stay.getByRole("button", { name: "Copy booking reference HK55821" })).toBeHidden();
  await stay.getByText("Address and booking").click();
  await expect(stay.getByRole("button", { name: "Copy booking reference HK55821" })).toBeVisible();
  await expect(stay).toContainText("Check out");
  await expect(stay).toContainText("Agoda");
  // The day is shown once: its plans are the itinerary's own list, there is no second card for it.
  await expect(page.getByRole("list", { name: /Plans for/ })).toHaveCount(0);
  await expect(day1.getByRole("list", { name: /^Day 1 · / })).toContainText("Check in");
  await expect(page.getByRole("button", { name: "Previous day" })).toBeDisabled();

  // The next day: the plan, opened, with its address, a link to directions and a note.
  await page.getByRole("button", { name: "Next day" }).click();
  const day2 = page.getByRole("group", { name: /^Day 2 · .*, 2 of \d+$/ });
  await expect(day2.getByRole("heading", { name: /^Day 2 of 4 · / })).toBeVisible();
  await expect(day2.getByRole("button", { name: "Copy the address of Hotel Kumo" })).toBeVisible();
  await expect(day2.getByRole("link", { name: "Open Fish market breakfast in Maps" })).toBeHidden();
  await openEntry(page, "Fish market breakfast");
  await expect(day2).toContainText("Go early");
  await expect(day2.getByRole("link", { name: "Open Fish market breakfast in Maps" })).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=Fish%20market%20breakfast%2C%204-5%20Market%20St%2C%20Tokyo",
  );

  // The last day: checking out, and nowhere to sleep that night.
  await page.getByRole("button", { name: "Next day" }).click();
  await page.getByRole("button", { name: "Next day" }).click();
  const last = page.getByRole("group", { name: /^Day 4 · .*, 4 of \d+$/ });
  await expect(last.getByRole("list", { name: /^Day 4 · / })).toContainText("Check out");
  await expect(last.locator(".day-stay")).toHaveCount(0);

  // The rest of the trip is on the same page, day by day.
  const pills = itineraryOf(page).getByRole("navigation", { name: "Days" });
  for (const d of [25, 26, 27, 28]) await expect(pills.getByRole("button", { name: new RegExp(`\\b${d}\\b`) })).toBeVisible();

  // And the spending has its own tab.
  await openTab(page, "Money");
  await expect(page.getByRole("region", { name: "Spent so far" })).toContainText("Log what you spend on Telegram");
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
  await expect(sheet).toContainText("Shows the days, plans and ideas. Never money, booking references, notes or who's going.");
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
  // The hotel's address is a line of its own under how long the stay runs.
  await expect(plan.locator(".shared-row").filter({ hasText: "Check in" }).locator(".caption")).toHaveText([/^Until /, "1-2-3 Example-cho, Tokyo"]);
  await expect(plan.getByRole("link", { name: "Open Fish market breakfast in Google Maps" })).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=Fish%20market%20breakfast%2C%204-5%20Market%20St%2C%20Tokyo",
  );
  const text = await page.locator("main").innerText();
  for (const secret of ["HK55821", "ZK4P7Q", "Agoda", "Somewhere secret", "SGD", "JPY", "820"]) expect(text).not.toContain(secret);
  // Nothing can be changed, and it never asked anyone to sign in. The only button is the cover's photo credit.
  await expect(page.getByRole("button", { name: "Photo credit" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /^(?!Photo credit$)/ })).toHaveCount(0);
  await expect(page).toHaveURL(shared);
});

test("ideas from guides and articles: asked for in words, credited, saved to the trip", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  const sheet = await openAddSheet(page, "Seoul");
  await sheet.getByRole("button", { name: "Find a place" }).click();
  // The search field says ideas can be asked for in words.
  await expect(page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for")).toHaveAttribute("placeholder", /Best ramen, a rainy day/);

  // Asking for ideas: Google Maps answers first, and the guides' ideas join the same list when they're in.
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("best noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Results" });
  await expect(results).toContainText("Hanok Noodle Bar");
  await expect(results).toContainText("“Hand-pulled noodles worth the queue.”");
  await expect.poll(() => state.ideaSearches).toEqual(["best noodles"]);
  await expect(page.getByRole("list", { name: "Ideas from guides and articles" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Google Maps results" })).toHaveCount(0);
  // Each is credited to its page, opened safely in a new tab.
  const source = results.getByRole("link", { name: "Seoul's best noodles" });
  await expect(source).toHaveAttribute("href", "https://food.example.com/seoul-noodles");
  await expect(source).toHaveAttribute("rel", /noopener/);
  await expect(results.getByLabel("Rated 4.6 out of 5 from 2310 ratings")).toBeVisible();
  await expect(results).toContainText("From a guide");

  // Saving one without a Google Maps match keeps its name, kind and area.
  await results.getByRole("button", { name: "Save: Lantern Alley" }).click();
  await expect.poll(() => state.plans[0]).toMatchObject({ name: "Lantern Alley", category: "Nightlife", list_name: "Nightlife", address: "Euljiro", place_id: null });
  await page.keyboard.press("Escape");
  await openTab(page, "Ideas");
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Lantern Alley");
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

  // The page opens on day 1, which has nothing on it: the map follows the day and says so.
  const map = page.getByRole("region", { name: "Map" });
  const pills = itineraryOf(page).getByRole("navigation", { name: "Days" });
  await expect(map).toContainText("Nothing on the map that day.");
  // All days shows both, numbered as on the itinerary and in day 3's colour.
  await map.getByRole("button", { name: "All days" }).click();
  await expect(map.getByRole("list", { name: "On the map" }).getByRole("listitem")).toHaveText(["1. Hanok Noodle Bar", "2. Namdaemun Market"]);
  const pins = () => page.evaluate(() => (window as unknown as { __map: { markers: { o: { title: string; label?: { text: string }; icon: { fillColor: string } } }[] } }).__map.markers.map((m) => [m.o.title, m.o.label?.text, m.o.icon.fillColor]));
  await expect.poll(pins).toEqual([
    ["Hanok Noodle Bar", "1", "#059669"],
    ["Namdaemun Market", "2", "#059669"],
  ]);
  expect(await page.evaluate(() => (window as unknown as { __map: { key: string } }).__map.key)).toBe("test-browser-key");
  // Picking the day draws its route; a day with nothing planned says so.
  await pills.getByRole("button", { name: /12/ }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __map: { lines: number } }).__map.lines)).toBe(1);
  await pills.getByRole("button", { name: /10/ }).click();
  await expect(map).toContainText("Nothing on the map that day.");
  await map.getByRole("button", { name: "All days" }).click();
  await pills.getByRole("button", { name: /12/ }).click();

  // Between the two on the itinerary: how long it takes (asked for once the day comes
  // into view), and a way to change it.
  await page.getByRole("heading", { name: /^Day 3 of \d+ ·/ }).scrollIntoViewIfNeeded();
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
  await (await openWays(page)).getByLabel("Directions open in").selectOption("apple");
  await page.keyboard.press("Escape");
  await expect(hop.getByRole("link", { name: "Directions" })).toHaveAttribute("href", "https://maps.apple.com/?saddr=Hanok+Noodle+Bar&daddr=Namdaemun+Market&dirflg=r");
  await page.reload();
  await page.getByRole("heading", { name: /^Day 3 of \d+ ·/ }).scrollIntoViewIfNeeded();
  await expect((await openWays(page)).getByLabel("Directions open in")).toHaveValue("apple");
  await page.getByRole("dialog", { name: "Getting around and directions" }).getByLabel("Directions open in").selectOption("google");
  await page.keyboard.press("Escape");

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

/** The owner's way to the getting-around and directions pickers: the trip's ⋯ menu, then its sheet. */
async function openWays(page: Page) {
  // The ⋯ is on the cover, and on the slim bar once the cover's photo has scrolled away: when that
  // happens the cover's goes hidden, so a click that began on it is tried again on the bar's.
  await expect(async () => {
    await page.getByRole("button", { name: "Trip options" }).click({ timeout: 1_000 });
  }).toPass();
  await page.getByRole("menuitem", { name: "Getting around and directions" }).click();
  return page.getByRole("dialog", { name: "Getting around and directions" });
}

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
  // A long journey: on a busy machine it needs more than the usual 30 seconds.
  test.slow();
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
  const itinerary = itineraryOf(page);
  const day2 = itinerary.getByRole("list", { name: /^Day 2/ });
  const day3 = itinerary.getByRole("list", { name: /^Day 3/ });

  // What's worth a look on the day, worked out on the server.
  const notes = itinerary.getByRole("list", { name: "Worth a look" });
  await expect(notes.getByRole("listitem")).toHaveText([/Old Temple \(13:00 to 15:00\) runs into Tea house at 14:00/, /Free 09:00 to 13:00/]);
  await expect(page.locator("#entry-pl1 .time-pill")).toHaveText("13:00–15:00");

  // One day at a time: it opens on day 1; the next day is a swipe or a tap away.
  const days = page.getByRole("region", { name: "Days of the trip" });
  await expect(days).toContainText("1 of 4");
  await days.getByRole("button", { name: "Next day" }).click();
  await expect(days).toContainText(/Day 2 · .*, 2 of 4/);
  await expect(page.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /11/ })).toHaveAttribute("aria-current", "true");

  // Dragged by its grip to above the temple: one call, and the day follows it.
  const grip = page.getByRole("button", { name: "Drag Tea house" });
  // Mid-screen, clear of the bars that stick at the top (a phone has three of them).
  await grip.evaluate((el) => el.scrollIntoView({ block: "center" }));
  // The days slide sideways and the page may still be scrolling: wait until day 2 is fully in
  // the card and the grip has stopped moving.
  let last = "";
  await expect
    .poll(async () => {
      const [g, card] = [await grip.boundingBox(), await itinerary.boundingBox()];
      const now = JSON.stringify(g);
      const still = now === last;
      last = now;
      return Boolean(still && g && card && g.x > card.x && g.x + g.width < card.x + card.width);
    }, { intervals: [150] })
    .toBe(true);
  const from = (await grip.boundingBox())!;
  const onto = (await page.locator("#entry-pl1").boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2 - 10, { steps: 3 });
  // Well inside the top half of the temple, so it lands above it.
  await page.mouse.move(onto.x + 40, onto.y + Math.min(12, onto.height / 4), { steps: 8 });
  await expect(page.locator("#entry-pl1")).toHaveClass(/drop-before/);
  await page.mouse.up();
  await expect.poll(() => state.moves).toEqual(["pl2>2026-11-11@first"]);
  await expect(day2.locator(".timeline-stop strong")).toHaveText(["Tea house", "Old Temple"]);

  // With the keyboard on a day's plan: picked up, taken down to the empty day 3 (the day picker follows it), and left there.
  const carry = page.getByRole("button", { name: "Drag Tea house" });
  await carry.focus();
  await page.keyboard.press("Space");
  const said = page.getByRole("status", { name: "Moving a plan" });
  await expect(said).toContainText("Picked up Tea house");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(said).toContainText(/Tea house: first, Thu.*12/);
  await expect(day3.locator("..")).toHaveClass(/drop-over/);
  await expect(days).toContainText("3 of 4");
  await page.keyboard.press("Escape");
  await expect(said).toContainText("Tea house stays where it was");
  await days.getByRole("button", { name: "Previous day" }).click();
  await expect(days).toContainText("2 of 4");

  // An idea is lifted with the keyboard from the Ideas tab, up to the empty day 3, and dropped.
  await openTab(page, "Ideas");
  // Ideas filter by list.
  const places = page.getByRole("list", { name: "Ideas" });
  const lists = page.getByRole("group", { name: "Lists" });
  await lists.getByRole("button", { name: /Shopping/ }).click();
  await expect(places.getByRole("listitem")).toHaveCount(1);
  await expect(places).toContainText("Namdaemun Market");
  await lists.getByRole("button", { name: "All" }).click();
  await expect(places.getByRole("listitem")).toHaveCount(2);
  // Grips show only while arranging.
  await expect(page.getByRole("button", { name: "Drag Lantern Alley" })).toHaveCount(0);
  await page.getByRole("button", { name: "Arrange", exact: true }).click();
  const keys = page.getByRole("button", { name: "Drag Lantern Alley" });
  await keys.focus();
  await page.keyboard.press("Space");
  await expect(said).toContainText("Picked up Lantern Alley");
  // Up from first in Ideas: first on day 4, then first on day 3.
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await expect(said).toContainText(/Lantern Alley: first, Thu.*12/);
  await page.keyboard.press("Space");
  await expect.poll(() => state.moves).toEqual(["pl2>2026-11-11@first", "pl3>2026-11-12@first"]);
  await expect(places).not.toContainText("Lantern Alley");
  await openTab(page, "Plan");
  await itinerary.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ }).click();
  await expect(day3).toContainText("Lantern Alley");

  // Or from the entry's editor, without dragging: the temple after it on day 3.
  await itinerary.getByRole("navigation", { name: "Days" }).getByRole("button", { name: /11/ }).click();
  await editEntry(page, "Old Temple");
  await page.getByRole("button", { name: "Move to…" }).click();
  await page.getByRole("dialog", { name: "Put on a day" }).getByRole("region", { name: "All days" }).getByRole("button", { name: /^Day 3 ·/ }).click();
  await expect.poll(() => state.moves.at(-1)).toBe("pl1>2026-11-12@pl3");
  await expect(day3.locator(".timeline-stop strong")).toHaveText(["Lantern Alley", "Old Temple"]);

  // Free time left on day 2 offers something to fill it, saved onto that day.
  await expect(notes.first()).toContainText("Free 09:00 to 14:00");
  await notes.first().getByRole("button", { name: "Find something to do" }).click();
  await page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for").fill("noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  // Searching from a free slot looks near that day, and "Add" is already for it: no second button for the same thing.
  await expect(page.getByRole("list", { name: "Results" }).getByRole("button", { name: /^Add to Day/ })).toHaveCount(0);
  await expect.poll(() => state.placeScopes.at(-1)).toMatchObject({ q: "noodles", day: "2026-11-11" });
  await page.getByRole("list", { name: "Results" }).getByRole("button", { name: "Add: Hanok Noodle Bar" }).click();
  await expect.poll(() => state.plans.at(-1)).toMatchObject({ name: "Hanok Noodle Bar", day: "2026-11-11", at: "09:00", place_id: "fakePlaceNoodle01" });
  await page.keyboard.press("Escape");
  await expect(day2).toContainText("Hanok Noodle Bar");

  // An end time and a link, from the entry's editor.
  // Tap the row once the day has made room for the noodle bar (rows move down as it eases to its height).
  const changeTea = page.getByRole("button", { name: "Open Tea house" });
  let was = "";
  await expect
    .poll(async () => {
      const now = JSON.stringify(await changeTea.boundingBox());
      const still = now === was;
      was = now;
      return still;
    }, { intervals: [150] })
    .toBe(true);
  await editEntry(page, "Tea house");
  const edit = page.getByRole("form", { name: "Change the entry" });
  await expect(edit.getByLabel("Name")).toHaveValue("Tea house");
  await edit.getByLabel("Until").fill("15:30");
  await edit.getByText("More details").click();
  await edit.getByLabel("Link").fill("https://tea.example.com/book");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => state.plans.find((p) => p.id === "pl2")).toMatchObject({ ends_at: "15:30", link: "https://tea.example.com/book" });
  await expect(page.locator("#entry-pl2 .time-pill")).toHaveText("14:00–15:30");
  await openEntry(page, "Tea house");
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
  await (await openWays(page)).getByLabel("Getting around").selectOption("car");
  await page.keyboard.press("Escape");
  await expect.poll(() => state.trips[0].getting_around).toBe("car");
  await expect(hop).toContainText("1 h 30 min drive");
  await expect(notes).toContainText("Arrive around 10:45 (land 09:15, then 1 h 30 min) · check-in from 15:00 · about 4 h 15 min to fill");

  // The airport is on the map, and day 1's route runs from it to the hotel.
  const markers = () => page.evaluate(() => (window as unknown as { __map: { markers: { o: { title: string } }[] } }).__map.markers.map((m) => m.o.title));
  await expect.poll(markers).toEqual(expect.arrayContaining(["BCN airport", "Hill Lodge"]));
  // The map follows the day open beside it, which is day 1: its route is drawn.
  await expect(page.getByRole("region", { name: "Map" }).getByRole("button", { name: "All days" })).toBeVisible();
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
  await openAddSheet(page, "Seoul");
  // The sheet is named for the view it shows ("Type it", "Find a place").
  const sheet = page.getByRole("dialog");
  await expect(sheet).toHaveAccessibleName("Add to Seoul");
  await expect(viewport).toHaveCSS("overflow-y", "hidden");
  await sheet.getByRole("button", { name: "Type it" }).click();
  if (phone) await expect(sheet.getByLabel("Tell Nexus about a booking")).not.toBeFocused();
  else await expect(sheet.getByLabel("Tell Nexus about a booking")).toBeFocused();
  await sheet.getByRole("button", { name: "Back to the ways to add" }).click();
  await sheet.getByRole("button", { name: "Find a place" }).click();
  if (phone) expect(await smallest(sheet)).toBeGreaterThanOrEqual(16);
  await page.keyboard.press("Escape");
  await expect(viewport).toHaveCSS("overflow-y", "auto");

  // The short forms the user opens show as they are, without fading in, and their fields don't zoom.
  for (const choice of [/A booking/, /A plan/, /An idea/]) {
    await tripAdd(page).click();
    await page.getByRole("dialog").getByRole("button", { name: choice }).click();
    const form = page.getByRole("dialog").getByRole("form", { name: "Add to the itinerary" });
    await expect(form).toBeVisible();
    await expect(form).not.toHaveAttribute("data-reveal", /.*/);
    if (phone) expect(await smallest(form)).toBeGreaterThanOrEqual(16);
    await page.keyboard.press("Escape");
  }

  // So does a plan opened to change in place, by tapping it.
  await editEntry(page, "ZZ12 SIN → NRT");
  const change = itineraryOf(page).getByRole("form", { name: "Change the entry" });
  await expect(change).toBeVisible();
  await expect(change).not.toHaveAttribute("data-reveal", /.*/);
  if (phone) expect(await smallest(change)).toBeGreaterThanOrEqual(16);
  await change.getByRole("button", { name: "Cancel" }).click();

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
  state.trips[0] = { ...state.trips[0], status: "finished", companions: ["Ann"] };
  await page.reload();
  // It opens on Money; Next up is Plan's, and there it says who still owes.
  await expect(page.getByRole("navigation", { name: "Trip sections" }).getByRole("button", { name: "Money", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "Next up" })).toHaveCount(0);
  await openTab(page, "Plan");
  await expect(page.getByRole("region", { name: "Next up" })).toContainText("Ann still owes you");
  await openTab(page, "Money");
  const settle = page.getByRole("region", { name: "To do" });
  await expect(settle).toContainText("Ann");
  const numbers = page.getByRole("region", { name: "The trip cost" });
  // To do fills the first screen, so the figures below it count up once scrolled to.
  await numbers.scrollIntoViewIfNeeded();
  await expect(numbers).toContainText("SGD 818.00");
  // Settling up sits above what it cost.
  expect((await settle.boundingBox())!.y).toBeLessThan((await numbers.boundingBox())!.y);
  await expect(tripAdd(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Expenses/ })).toBeVisible();
});

/** A finished-looking trip on the Money tab with these people going. */
async function moneyTrip(page: Page, companions: string[]) {
  const state = await fakeApi(page);
  await addTrip(page, "Osaka", "2026-11-10", "2026-11-12");
  state.trips[0] = { ...state.trips[0], companions };
  await page.reload();
  await openTab(page, "Money");
  return state;
}

const paidByAnn = (note: string, paidOn: string) => ({
  id: "pay1",
  person: "Ann",
  amount: { amount: "60000.0000", currency: "JPY" },
  note,
  paid_on: paidOn,
  split_with: ["Ben"],
  my_share: { amount: "20000.0000", currency: "JPY" },
  settled: false,
  settled_at: null,
});

test("travellers are added and removed on the Money tab, and the split switch follows them", async ({ page }) => {
  const state = await moneyTrip(page, []);
  await expect(page.getByRole("button", { name: /^Travellers/ })).toContainText("You");
  const travellers = await openSection(page, "Travellers");
  await expect(travellers.getByRole("list", { name: "Who's going" })).toHaveText("You");
  // Nobody else is going, so there is nothing to split yet, and no To do.
  await expect(travellers.getByRole("switch", { name: "Split costs evenly" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "To do" })).toHaveCount(0);

  await travellers.getByRole("textbox", { name: "Add a traveller" }).fill("Ann");
  await travellers.getByRole("button", { name: "Add" }).click();
  await expect.poll(() => state.tripPuts.at(-1)).toMatchObject({ companions: ["Ann"] });
  await expect(travellers.getByRole("list", { name: "Who's going" })).toContainText("Ann");
  await expect(page.getByRole("button", { name: /^Travellers/ })).toContainText("You and Ann");
  await expect(travellers.getByRole("switch", { name: "Split costs evenly" })).toBeVisible();
  await expect(page.getByRole("region", { name: "To do" })).toBeVisible();
  // Enter adds too, and a name already there (any case) is not added twice.
  await travellers.getByRole("textbox", { name: "Add a traveller" }).fill("ben");
  await travellers.getByRole("textbox", { name: "Add a traveller" }).press("Enter");
  await expect.poll(() => state.tripPuts.at(-1)).toMatchObject({ companions: ["Ann", "ben"] });
  await travellers.getByRole("textbox", { name: "Add a traveller" }).fill("ANN");
  await travellers.getByRole("button", { name: "Add" }).click();
  expect(state.tripPuts).toHaveLength(2);

  await travellers.getByRole("button", { name: "Remove Ann" }).click();
  await expect.poll(() => state.tripPuts.at(-1)).toMatchObject({ companions: ["ben"] });
  await travellers.getByRole("button", { name: "Remove ben" }).click();
  await expect.poll(() => state.tripPuts.at(-1)).toMatchObject({ companions: [] });
  await expect(travellers.getByRole("list", { name: "Who's going" })).toHaveText("You");
  await expect(travellers.getByRole("switch", { name: "Split costs evenly" })).toHaveCount(0);
});

test("split all evenly asks first, then the shares show in To do", async ({ page }) => {
  const state = await moneyTrip(page, ["Ann", "Ben"]);
  // Even splitting is on by default (the switch is with the travellers), and offers the trip's costs without changing anything.
  const travellers = await openSection(page, "Travellers");
  await expect(travellers.getByRole("switch", { name: "Split costs evenly" })).toHaveAttribute("aria-checked", "true");
  const split = page.getByRole("region", { name: "To do" });
  await expect(split).toContainText("2 costs to split");
  await expect(split).toContainText("SGD 818.00");
  await expect(split).toContainText("Ichiran");
  await expect(split).toContainText("Air ticket");
  await split.getByRole("button", { name: "See costs" }).click();
  await expect(split.getByRole("list", { name: "To split" })).toContainText("Ichiran");
  await expect(split.getByRole("list", { name: "To split" })).toContainText("Air ticket");
  expect(state.splitPosts).toEqual([]);

  await split.getByRole("button", { name: "Split all evenly" }).click();
  const confirm = split.getByRole("group", { name: "Confirm splitting all" });
  await expect(confirm).toContainText("Split 2 costs (SGD 818.00) evenly with Ann and Ben?");
  await expect(confirm).toContainText("Each share is about SGD 272.67.");
  // Not now splits nothing.
  await confirm.getByRole("button", { name: "Not now" }).click();
  await expect(confirm).toHaveCount(0);
  expect(state.splitPosts).toEqual([]);

  await split.getByRole("button", { name: "Split all evenly" }).click();
  await confirm.getByRole("button", { name: "Split evenly" }).click();
  await expect.poll(() => state.splitPosts).toEqual([{ all: true }]);
  await expect(split.getByRole("status")).toContainText("Split 2 costs evenly with Ann and Ben");
  await expect(split.getByRole("list", { name: "To split" })).toHaveCount(0);
  await expect(split).not.toContainText("costs to split");

  // The IOUs show up as people to settle with: what Ann owes now includes her shares of both bills.
  const ann = split.getByRole("listitem").filter({ hasText: "Ann owes you" });
  await expect(ann).toBeVisible();
  await expect(split.getByRole("listitem").filter({ hasText: "Ben owes you" })).toBeVisible();
  await ann.getByRole("button", { name: "Details" }).click();
  const parts = ann.getByRole("list", { name: "What Ann owes you" });
  await expect(parts).toContainText("Dinner");
  await expect(parts).toContainText("Ichiran");
  await expect(parts).toContainText("Air ticket");
  // Nothing is moved: this only records.
  await expect(split).toContainText("It doesn't move money");
});

test("the even split can be switched off, and one cost kept as just mine and offered again", async ({ page }) => {
  const state = await moneyTrip(page, ["Ann"]);
  const split = page.getByRole("region", { name: "To do" });
  await split.getByRole("button", { name: "See costs" }).click();
  const toSplit = split.getByRole("list", { name: "To split" });

  await split.getByRole("button", { name: "Keep Ichiran as just mine" }).click();
  await expect.poll(() => state.keepMinePosts).toEqual([{ transaction_ids: ["k1"], keep: true }]);
  await expect(toSplit).not.toContainText("Ichiran");
  await expect(toSplit).toContainText("Air ticket");
  // It is set aside, not lost: still listed in Expenses as just mine, and offered again on request.
  const expenses = await openSection(page, "Expenses");
  await expect(expenses.getByRole("listitem").filter({ hasText: "Ichiran" })).toContainText("Just mine");
  await expenses.getByRole("button", { name: "Offer Ichiran for splitting again" }).click();
  await expect.poll(() => state.keepMinePosts.at(-1)).toEqual({ transaction_ids: ["k1"], keep: false });
  await expect(toSplit).toContainText("Ichiran");
  await expect(expenses.getByRole("listitem").filter({ hasText: "Ichiran" })).toContainText("To split");
  await expect(expenses.getByRole("button", { name: "Offer Ichiran for splitting again" })).toHaveCount(0);
  // Nothing was split along the way.
  expect(state.splitPosts).toEqual([]);

  // One row can be split on its own.
  await split.getByRole("button", { name: "Split Air ticket evenly" }).click();
  await expect.poll(() => state.splitPosts).toEqual([{ transaction_ids: ["k2"] }]);
  await expect(toSplit).not.toContainText("Air ticket");
  await expect(expenses.getByRole("listitem").filter({ hasText: "Air ticket" })).toContainText("Split with Ann");

  // Switching it off stops offering costs; on again brings them back.
  const travellers = await openSection(page, "Travellers");
  const toggle = travellers.getByRole("switch", { name: "Split costs evenly" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(split).not.toContainText("to split");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(split).toContainText("1 cost to split");
  await expect(split).toContainText("Ichiran");
});

test("someone else paid: it is listed with your share and nets against what they owe you", async ({ page }) => {
  const state = await moneyTrip(page, ["Ann", "Ben"]);
  await tripAdd(page).click();
  await expect(page.getByRole("heading", { name: "What are you adding?" })).toBeVisible();
  await page.getByRole("button", { name: "Someone else paid" }).click();
  const form = page.getByRole("form", { name: "Someone else paid" });
  await form.getByLabel("Who paid").selectOption("Ann");
  await form.getByLabel("Amount").fill("60000");
  await form.getByLabel("Currency").fill("jpy");
  await form.getByLabel("What it was for").fill("Ryokan");
  await form.getByLabel("Date").fill("2026-09-20");
  await expect(form.getByRole("group", { name: "Split with (you're in it too)" })).toContainText("Ben");
  await form.getByRole("button", { name: "Save" }).click();

  await expect(form).toHaveCount(0);
  const paid = await openSection(page, "Paid by others");
  await expect(paid).toContainText("Ann paid for Ryokan");
  await expect(paid).toContainText("split with you, Ben");
  await expect(paid).toContainText("your share JPY 20,000");
  expect(state.paidByOthers.trip1).toHaveLength(1);

  // Ann already owed JPY 15,000 (SGD 135.00); your share of the ryokan is SGD 180.00, so you owe her the difference.
  const todo = page.getByRole("region", { name: "To do" });
  const ann = todo.getByRole("listitem").filter({ hasText: "You owe Ann" });
  await expect(ann).toContainText("You owe Ann SGD 45.00");
  await ann.getByRole("button", { name: "Details" }).click();
  await expect(ann.getByRole("list", { name: "What you owe Ann" })).toContainText("Ryokan");
  await expect(ann.getByRole("list", { name: "What Ann owes you" })).toContainText("Dinner");

  // Taking it away puts the balance back.
  await paid.getByRole("button", { name: "Remove what Ann, Ryokan paid" }).click();
  const sure = paid.getByRole("group", { name: "Remove what Ann, Ryokan paid" });
  await sure.getByRole("button", { name: "Keep" }).click();
  await expect(paid).toContainText("Ann paid for Ryokan");
  await paid.getByRole("button", { name: "Remove what Ann, Ryokan paid" }).click();
  await sure.getByRole("button", { name: "Remove" }).click();
  // With nothing paid by others, the section is gone.
  await expect(page.getByRole("button", { name: /^Paid by others/ })).toHaveCount(0);
  expect(state.paidByOthers.trip1).toEqual([]);
  await expect(todo.getByRole("listitem").filter({ hasText: "Ann owes you" })).toContainText("Ann owes you SGD 135.00");
});

test("a payment someone else made can be changed", async ({ page }) => {
  const state = await moneyTrip(page, ["Ann", "Ben"]);
  state.paidByOthers.trip1 = [paidByAnn("Ryokan", "2026-09-20")];
  await page.reload();
  await openTab(page, "Money");
  const paid = await openSection(page, "Paid by others");
  await paid.getByRole("button", { name: "Change what Ann, Ryokan paid" }).click();
  const form = page.getByRole("form", { name: "Change what Ann paid" });
  await form.getByLabel("Amount").fill("30000");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(paid).toContainText("your share JPY 10,000");
});

test("mark settled records the payment, with or without counting your share as spent", async ({ page }) => {
  const state = await moneyTrip(page, ["Ann", "Ben"]);
  state.paidByOthers.trip1 = [paidByAnn("Ryokan", "2026-09-20"), { ...paidByAnn("Taxi", "2026-09-21"), id: "pay2", person: "Ben", split_with: ["Ann"] }];
  await page.reload();
  await openTab(page, "Money");
  const settle = page.getByRole("region", { name: "To do" });

  // Ann: you owe her more than she owes you. Logging the payment is on, and says what it records.
  await settle.getByRole("button", { name: "Settle up with Ann" }).click();
  const confirm = settle.getByRole("group", { name: "Settle up with Ann" });
  const record = confirm.getByRole("checkbox", { name: "Also record my share as spent" });
  await expect(record).toBeChecked();
  await expect(confirm).toContainText("Nexus doesn't move any money.");
  // Not now records nothing.
  await confirm.getByRole("button", { name: "Not now" }).click();
  await expect(confirm).toHaveCount(0);
  expect(state.settlePosts).toEqual([]);
  await settle.getByRole("button", { name: "Settle up with Ann" }).click();
  await confirm.getByRole("button", { name: "Mark settled" }).click();
  await expect.poll(() => state.settlePosts).toEqual([{ person: "Ann", log: true }]);
  await expect(settle.getByRole("status")).toContainText("Settled with Ann: 1 IOU from Ann marked paid back");
  await expect(settle.getByRole("status")).toContainText("1 payment you owed Ann marked paid, JPY 20,000 recorded as spent");
  await expect(settle.getByRole("button", { name: "Settle up with Ann" })).toHaveCount(0);

  // Ben: left unticked, it is marked paid without touching what you've spent.
  await settle.getByRole("button", { name: "Settle up with Ben" }).click();
  const benConfirm = settle.getByRole("group", { name: "Settle up with Ben" });
  await benConfirm.getByRole("checkbox", { name: "Also record my share as spent" }).uncheck();
  await benConfirm.getByRole("button", { name: "Mark settled" }).click();
  await expect.poll(() => state.settlePosts.at(-1)).toEqual({ person: "Ben", log: false });
  await expect(settle.getByRole("status")).toContainText("nothing added to what you've spent");
  await expect(settle.getByRole("button", { name: /^Settle up with/ })).toHaveCount(0);
});

test("when they only owe you, settling has no spending choice", async ({ page }) => {
  const state = await moneyTrip(page, ["Ann"]);
  const settle = page.getByRole("region", { name: "To do" });
  await settle.getByRole("button", { name: "Settle up with Ann" }).click();
  const confirm = settle.getByRole("group", { name: "Settle up with Ann" });
  await expect(confirm.getByRole("checkbox")).toHaveCount(0);
  await expect(confirm).toContainText("Ann paid you back");
  await confirm.getByRole("button", { name: "Mark settled" }).click();
  await expect.poll(() => state.settlePosts).toEqual([{ person: "Ann", log: false }]);
  await expect(settle.getByRole("status")).toContainText("Settled with Ann: 1 IOU from Ann marked paid back");
});

test("a shared link can leave bookings out, and the shared page says so", async ({ page }) => {
  const state = await fakeApi(page);
  page.on("dialog", (d) => void d.accept());
  await addTrip(page, "Tokyo", "2026-11-10", "2026-11-12");
  const entry = { trip_id: "trip1", provider: null, segments: [], name: null, day: null, at: null, category: null, place_id: null, scheduled: true, logged: false, manual: true };
  state.plans.push(
    { ...entry, id: "pl1", kind: "hotel", title: "Hotel Kumo", hotel: "Hotel Kumo", starts: "2026-11-10", ends: "2026-11-12", check_in: "2026-11-10", check_out: "2026-11-12", address: "1-2-3 Example-cho, Tokyo", reference: "HK55821", booked_via: "Agoda", note: null, cost: null },
    { ...entry, id: "pl2", kind: "activity", title: "Fish market breakfast", name: "Fish market breakfast", starts: "2026-11-11", ends: "2026-11-11", day: "2026-11-11", at: "07:30", address: "4-5 Market St, Tokyo", hotel: null, check_in: null, check_out: null, reference: null, booked_via: null, note: null, cost: null },
  );
  await page.reload();

  await page.getByRole("button", { name: "Share the plan" }).click();
  const sheet = page.getByRole("dialog", { name: "Share the plan" });
  const toggle = sheet.getByRole("switch", { name: "Show bookings (flights, stays, tickets)" });
  // Bookings are shown unless you say otherwise, even before there is a link.
  await expect(toggle).toBeChecked();
  const created = page.waitForRequest((r) => r.url().endsWith("/travel/trips/trip1/share") && r.method() === "POST");
  await sheet.getByRole("button", { name: "Create a link" }).click();
  expect((await created).postDataJSON()).toEqual({ show_bookings: true });
  const link = sheet.getByLabel("The trip's link");
  await expect(link).toHaveValue(/\/shared\/fakeShare0001x+$/);
  await expect(toggle).toBeChecked();
  expect(state.shareBookings.trip1).toBe(true);

  const off = page.waitForRequest((r) => r.url().endsWith("/travel/trips/trip1/share") && r.method() === "POST");
  await toggle.click();
  expect((await off).postDataJSON()).toEqual({ show_bookings: false });
  await expect(sheet.getByRole("status")).toHaveText("Saved");
  await expect(toggle).not.toBeChecked();
  expect(state.shareBookings.trip1).toBe(false);
  // A new link keeps the choice.
  await sheet.getByRole("button", { name: "Make a new link" }).click();
  await expect(link).toHaveValue(/\/shared\/fakeShare0002x+$/);
  await expect(toggle).not.toBeChecked();
  const shared = new URL(await link.inputValue()).pathname;
  await page.keyboard.press("Escape");

  await page.goto(shared);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tokyo");
  await expect(page.getByRole("note")).toHaveText("Bookings aren't shown on this link.");
  const plan = page.getByRole("region", { name: "The plan" });
  // Their own plans stay; flights and stays are gone, and the days they filled read as travel days.
  await expect(plan).toContainText("Fish market breakfast");
  const text = await page.locator("main").innerText();
  for (const hidden of ["ZZ12", "Hotel Kumo", "Staying at", "HK55821"]) expect(text).not.toContain(hidden);
  await expect(plan.getByText("Travel day")).toHaveCount(2);
  await expect(plan.getByText("Free day")).toHaveCount(0);

  // Back on, the bookings return and the note goes.
  await page.goto("/travel/trips/trip1");
  await page.getByRole("button", { name: "Share the plan" }).click();
  await sheet.getByRole("switch", { name: "Show bookings (flights, stays, tickets)" }).click();
  await expect.poll(() => state.shareBookings.trip1).toBe(true);
  await page.goto(shared);
  await expect(page.getByRole("note")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "The plan" })).toContainText("Staying at Hotel Kumo");
  await expect(page.getByRole("region", { name: "The plan" })).toContainText("ZZ12 SIN → NRT");

  // Stopping and sharing again starts from the default: bookings shown.
  await page.goto("/travel/trips/trip1");
  await page.getByRole("button", { name: "Share the plan" }).click();
  await sheet.getByRole("switch", { name: "Show bookings (flights, stays, tickets)" }).click();
  await expect.poll(() => state.shareBookings.trip1).toBe(false);
  await sheet.getByRole("button", { name: "Stop sharing" }).click();
  await expect(sheet.getByRole("button", { name: "Create a link" })).toBeVisible();
  await expect(sheet.getByRole("switch", { name: "Show bookings (flights, stays, tickets)" })).toBeChecked();
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
  const money = page.getByRole("region", { name: "Money this month" });
  const card = money.locator(".card");
  await expect(card).toBeVisible();
  // The title sits above the card, not inside it.
  const title = (await money.getByRole("heading", { name: "Money this month" }).boundingBox())!;
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

// --- the trip page: Next up, the tabs, ideas, notes and packing ---------------------------

/** A made-up itinerary entry for ``state.plans``: an idea (no day) unless ``more`` puts it on one. */
const tripEntry = (id: string, more: Record<string, unknown>) => ({
  id, trip_id: "trip1", kind: "activity", title: "", provider: null, starts: "2026-09-28", ends: null, segments: [], hotel: null,
  address: null, check_in: null, check_out: null, name: null, day: null, at: null, ends_at: null, note: null, cost: null, logged: false,
  manual: true, reference: null, booked_via: null, category: null, place_id: null, link: null, list_name: null, order: null,
  scheduled: false, ...more,
});
const idea = (id: string, name: string, more: Record<string, unknown> = {}) => tripEntry(id, { title: name, name, ...more });
const planOn = (id: string, name: string, day: string, more: Record<string, unknown> = {}) =>
  tripEntry(id, { title: name, name, day, starts: day, ends: day, scheduled: true, ...more });
/** A stay covering the nights of the trip, so no night is left without a place. */
const stay = (id: string, from: string, to: string) =>
  tripEntry(id, { kind: "hotel", title: "Hotel Kumo", hotel: "Hotel Kumo", starts: from, ends: to, check_in: from, check_out: to, scheduled: true });

test("Next up names a free day while planning, and its button opens the Ideas tab", async ({ page }) => {
  const state = await fakeApi(page);
  // With a budget, a way there and a place every night, the first free day is next.
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13", (form) => form.getByLabel(/^Budget/).fill("3000"));
  state.plans.push(stay("pl1", "2026-11-10", "2026-11-13"));
  await page.reload();
  const strip = page.getByRole("region", { name: "Next up" });
  // The flight is on day 1; day 2 has nothing yet, and no ideas to fill it with.
  await expect(strip).toContainText("Day 2 in Seoul is still free.");
  await expect(strip).not.toContainText("could fill it");

  // With ideas saved, it says how many could fill the day.
  state.plans.push(idea("pl2", "Lantern Alley", { list_name: "Nightlife" }), idea("pl3", "Namdaemun Market", { list_name: "Shopping" }));
  await page.reload();
  await expect(strip).toContainText("Day 2 in Seoul is still free. 2 of your ideas could fill it.");
  await strip.getByRole("button", { name: /^Find ideas:/ }).click();
  await expect(page.getByRole("navigation", { name: "Trip sections" }).getByRole("button", { name: "Ideas", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Lantern Alley");
  await expect(page).toHaveURL(/tab=ideas/);
});

test("an idea is put on a day from Ideas, shows on that day of Plan, and is taken off again", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push(idea("pl1", "Lantern Alley", { list_name: "Nightlife" }), planOn("pl2", "Old Temple", "2026-11-11", { at: "10:00" }));
  await page.reload();

  await openTab(page, "Ideas");
  await page.getByRole("list", { name: "Ideas" }).getByRole("button", { name: "Put Lantern Alley on a day" }).click();
  const picker = page.getByRole("dialog", { name: "Put on a day" });
  // The day open on Plan comes first, then every day with its label, or "Free day", and what's on it.
  await expect(picker.getByRole("region", { name: "Viewing" })).toContainText("Day 1");
  const all = picker.getByRole("region", { name: "All days" });
  await expect(all.getByRole("button", { name: /^Day 2 ·/ })).toContainText("1 plan");
  await expect(all.getByRole("button", { name: /^Day 3 ·/ })).toContainText("Free day");
  await expect(picker.getByRole("button", { name: "Keep it as an idea" })).toBeVisible();
  await all.getByRole("button", { name: /^Day 3 ·/ }).click();
  await expect(picker).toHaveCount(0);
  await expect.poll(() => state.moves).toEqual(["pl1>2026-11-12@first"]);
  await expect(page.getByRole("list", { name: "Ideas" })).toHaveCount(0);

  // On Plan, day 3 has it.
  await openTab(page, "Plan");
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ }).click();
  await expect(itineraryOf(page).getByRole("list", { name: /^Day 3/ })).toContainText("Lantern Alley");
  await expect(itineraryOf(page).getByRole("heading", { name: /^Day 3/ })).toContainText("1 plan");

  // Its day picker has the way back: take it off, and it is an idea again.
  await editEntry(page, "Lantern Alley");
  await itineraryOf(page).getByRole("button", { name: "Move to…" }).click();
  const back = page.getByRole("dialog", { name: "Put on a day" });
  await expect(back.getByRole("region", { name: "All days" }).getByRole("button", { name: /^Day 3 ·/ })).toContainText("Here now");
  await back.getByRole("button", { name: "Take it off Day 3" }).click();
  await expect.poll(() => state.moves.at(-1)).toBe("pl1>places@first");
  await expect(itineraryOf(page).getByRole("list", { name: /^Day 3/ })).not.toContainText("Lantern Alley");
  await openTab(page, "Ideas");
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Lantern Alley");
});

test("a new idea from the + on Ideas goes in a new list, and shows with its list chip", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push(idea("pl1", "Lantern Alley", { list_name: "Nightlife" }));
  await page.reload();
  await openTab(page, "Ideas");
  await expect(tripAdd(page)).toHaveAccessibleName("Add an idea");
  await tripAdd(page).click();

  // The short form: a name and a list. The lists so far are chips; a new one is typed.
  const sheet = page.getByRole("dialog", { name: "Add an idea" });
  const form = sheet.getByRole("form", { name: "Add to the itinerary" });
  await expect(form.getByRole("button", { name: "Nightlife" })).toBeVisible();
  await expect(form.getByLabel("Day", { exact: true })).toHaveCount(0);
  await form.getByLabel("Name", { exact: true }).fill("Ramen Street");
  await form.getByLabel("New list").fill("Food");
  await form.getByRole("button", { name: "Add" }).click();
  await expect(sheet).toHaveCount(0);
  await expect.poll(() => state.plans.at(-1)).toMatchObject({ name: "Ramen Street", list_name: "Food", day: null });

  // It is in the list of ideas, and its list is a chip that filters.
  const ideas = page.getByRole("list", { name: "Ideas" });
  await expect(ideas.getByRole("listitem")).toHaveCount(2);
  await expect(ideas).toContainText("Ramen Street");
  const chips = page.getByRole("group", { name: "Lists" });
  await expect(chips.getByRole("button", { name: /^Food/ })).toBeVisible();
  await expect(chips.getByRole("button", { name: /^Nightlife/ })).toBeVisible();
  await chips.getByRole("button", { name: /^Food/ }).click();
  await expect(ideas.getByRole("listitem")).toHaveCount(1);
  await expect(ideas).toContainText("Ramen Street");
});

test("the notes on Prep are saved on their own, and are there after a reload", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13", (form) => form.getByLabel(/^Budget/).fill("3000"));
  await openTab(page, "Prep");
  const notes = page.getByRole("textbox", { name: "Notes" });
  const save = page.getByRole("form", { name: "Trip notes" }).getByRole("button", { name: "Save" });
  await expect(save).toBeDisabled(); // nothing changed yet
  await notes.fill("Visa not needed. Meet Ann at Gate 3.");
  await save.click();
  // Only the notes go (their own endpoint, as a member's do), so nothing else about the trip can change.
  await expect.poll(() => state.notesPuts.at(-1)).toEqual({ notes: "Visa not needed. Meet Ann at Gate 3." });
  expect(state.tripPuts).toHaveLength(0);
  await expect(page.getByRole("region", { name: "Notes" })).toContainText("Saved");

  // Leaving the field saves too.
  await notes.fill("Visa not needed. Meet Ann at Gate 3. Bring cash.");
  await notes.blur();
  await expect.poll(() => state.notesPuts.at(-1)).toEqual({ notes: "Visa not needed. Meet Ann at Gate 3. Bring cash." });
  await expect.poll(() => state.trips[0]).toMatchObject({ notes: "Visa not needed. Meet Ann at Gate 3. Bring cash." });

  // After a reload the page is on Prep, with the notes in the field.
  await page.reload();
  await expect(page.getByRole("navigation", { name: "Trip sections" }).getByRole("button", { name: "Prep", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("textbox", { name: "Notes" })).toHaveValue("Visa not needed. Meet Ann at Gate 3. Bring cash.");
});

test("packing is there months before the trip, and the + on Prep adds to it", async ({ page }) => {
  const state = await fakeApi(page);
  // 43 days out: well before the last week, when getting ready used to come into view.
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  await expect(page.getByRole("region", { name: "Packing list" })).toHaveCount(0); // it lives on Prep
  await openTab(page, "Prep");
  const packing = page.getByRole("region", { name: "Packing list" });
  await expect(packing).toBeVisible();
  await expect(packing).toContainText("Nothing on the list yet");
  await packing.getByRole("button", { name: "Suggest", exact: true }).click();
  await expect(packing.getByRole("list", { name: "Things to pack" })).toContainText("Passport");
  await packing.getByRole("checkbox", { name: "Passport" }).check();
  await expect(packing).toContainText("1 of 3 packed");

  // The + on this tab asks what to add; "Something to pack" takes you to the packing field. (On a phone it
  // steps aside while the page scrolls down, and is back at the top.)
  await page.locator(".main-viewport").evaluate((el) => el.scrollTo({ top: 0 }));
  await expect(tripAdd(page)).toHaveAccessibleName("Add to prep");
  await tripAdd(page).click();
  await page.getByRole("dialog", { name: "Add to prep" }).getByRole("button", { name: /Something to pack/ }).click();
  await expect(packing.getByLabel("Thing to pack")).toBeFocused();
  await page.keyboard.type("Sunscreen");
  await page.keyboard.press("Enter");
  await expect(packing).toContainText("1 of 4 packed");
  await expect.poll(() => state.trips[0].packing).toEqual([
    { text: "Passport", done: true },
    { text: "Travel adapter", done: false },
    { text: "Umbrella or rain jacket", done: false },
    { text: "Sunscreen", done: false },
  ]);
});

test("a planned cost is added from the + on Money with the whole trip, and taken off again", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13", (form) => form.getByLabel(/^Budget/).fill("3000"));
  await openTab(page, "Money");
  await expect(page.getByRole("list", { name: "Planned costs" })).toHaveCount(0);
  await expect(tripAdd(page)).toHaveAccessibleName("Add a planned cost");
  await tripAdd(page).click();
  const form = page.getByRole("form", { name: "Add a planned cost" });
  await form.getByLabel("Name").fill("Flights");
  await form.getByLabel(/^Amount/).fill("820");
  await form.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => state.tripPuts.at(-1)).toMatchObject({ destination: "Seoul", budget: "3000", planned: { Flights: "820" } });
  const planned = page.getByRole("list", { name: "Planned costs" });
  await expect(planned).toContainText("Flights");
  await expect(planned).toContainText("820.00");
  await expect(form).toHaveCount(0);

  await planned.getByRole("button", { name: "Remove planned cost Flights" }).click();
  await expect.poll(() => state.tripPuts.at(-1)).toMatchObject({ budget: "3000", planned: {} });
  await expect(page.getByRole("list", { name: "Planned costs" })).toHaveCount(0);
});

test("picking a day in the day pills changes the map's day", async ({ page }) => {
  const state = await fakeApi(page);
  state.mapKey = "test-browser-key";
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push(
    planOn("pl1", "Hanok Noodle Bar", "2026-11-11", { at: "12:00", place_id: "fakePlaceNoodle01" }),
    planOn("pl2", "Namdaemun Market", "2026-11-12", { at: "12:00", place_id: "fakePlaceMarket01" }),
  );
  await page.reload();
  const map = page.getByRole("region", { name: "Map" });
  const onMap = map.getByRole("list", { name: "On the map" }).getByRole("listitem");
  const titles = () => page.evaluate(() => (window as unknown as { __map: { markers: { o: { title: string } }[] } }).__map.markers.map((m) => m.o.title));
  const pills = itineraryOf(page).getByRole("navigation", { name: "Days" });

  // Day 1 is open and has no places on it.
  await expect(map).toContainText("Nothing on the map that day.");
  await expect(map.getByRole("button", { name: "All days" })).toBeVisible();

  // Each pill puts that day's places on the map.
  await pills.getByRole("button", { name: /11/ }).click();
  await expect(onMap).toHaveText(["1. Hanok Noodle Bar"]);
  await expect.poll(titles).toEqual(["Hanok Noodle Bar"]);
  await pills.getByRole("button", { name: /12/ }).click();
  await expect(onMap).toHaveText(["1. Namdaemun Market"]);
  await expect.poll(titles).toEqual(["Namdaemun Market"]);

  // All days shows both; This day goes back to the day open beside it.
  await map.getByRole("button", { name: "All days" }).click();
  await expect(onMap).toHaveText(["1. Hanok Noodle Bar", "1. Namdaemun Market"]);
  await expect.poll(titles).toEqual(["Hanok Noodle Bar", "Namdaemun Market"]);
  await map.getByRole("button", { name: "This day" }).click();
  await expect(onMap).toHaveText(["1. Namdaemun Market"]);
  expect(state.mapKey).toBe("test-browser-key");
});

test("the open tab stays in the address: reload keeps it, and Back goes to the tab before", async ({ page }) => {
  await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  const nav = page.getByRole("navigation", { name: "Trip sections" });
  const current = async () => nav.locator("[aria-current=page]").innerText();
  expect(await current()).toBe("Plan");

  // A day picked on Plan is kept in the address too, without a history entry of its own.
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ }).click();
  await openTab(page, "Ideas");
  await openTab(page, "Money");
  await expect(page).toHaveURL(/tab=money/);

  // Reload: still Money.
  await page.reload();
  expect(await current()).toBe("Money");
  await expect(page.getByRole("button", { name: /^Where it goes/ })).toBeVisible();

  // Back goes to Ideas, then Plan, on the day that was open.
  await page.goBack();
  expect(await current()).toBe("Ideas");
  await expect(page).toHaveURL(/tab=ideas/);
  await page.goBack();
  expect(await current()).toBe("Plan");
  await expect(itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ })).toHaveAttribute("aria-current", "true");

  // A link straight to a tab opens on it.
  await page.goto("/travel/trips/trip1?tab=prep");
  expect(await current()).toBe("Prep");
});

// --- stops, suggested day labels and the Ideas map ---------------------------------------

/** A stay with a linked Google Maps place, so its city and area are known. */
const stayAt = (id: string, hotel: string, from: string, to: string, placeId: string) =>
  tripEntry(id, { kind: "hotel", title: hotel, hotel, starts: from, ends: to, check_in: from, check_out: to, scheduled: true, place_id: placeId });

/** What the fake Google Maps drew: the pins (title, fill) and the rings' labels. */
const drawn = (page: Page) =>
  page.evaluate(() => {
    const log = (window as unknown as { __map?: { markers: { o: { title: string; icon: { fillColor?: string } } }[]; circles: unknown[] } }).__map;
    return { pins: (log?.markers ?? []).map((m) => [m.o.title, m.o.icon.fillColor ?? ""]), rings: log?.circles.length ?? 0 };
  });
const pressPin = (page: Page, title: string) =>
  page.evaluate((t) => (window as unknown as { __map: { markers: { o: { title: string }; click: () => void }[] } }).__map.markers.find((m) => m.o.title === t)!.click(), title);
/** Shows the Ideas map: on a phone through the List/Map switch, beside the list on a wide screen. */
async function showIdeasMap(page: Page) {
  await openTab(page, "Ideas");
  const switcher = page.getByRole("group", { name: "Show ideas as" }).getByRole("button", { name: "Map", exact: true });
  if (await switcher.isVisible()) await switcher.click();
  await expect(page.getByRole("region", { name: "Map" })).toBeVisible();
}
/** A Seoul trip with a plan on Day 2 (noodles) and Day 3 (market), each linked to a place, and ideas
 * with their own pins: one 120 m from Day 2, one 1.3 km from Day 3, and one with no position. */
async function seoulWithIdeas(page: Page, mapKey: string | null) {
  const state = await fakeApi(page);
  state.mapKey = mapKey;
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push(
    planOn("pl1", "Hanok Noodle Bar", "2026-11-11", { at: "12:00", place_id: "fakePlaceNoodle01" }),
    planOn("pl2", "Namdaemun Market", "2026-11-12", { at: "12:00", place_id: "fakePlaceMarket01" }),
    idea("pl3", "Lantern Alley", { list_name: "Nightlife", lat: 37.566, lng: 126.9902 }),
    idea("pl4", "Hilltop Tower", { list_name: "Outdoors", lat: 37.5512, lng: 126.9882 }),
    idea("pl5", "Secret Garden", { list_name: "Outdoors" }),
  );
  await page.reload();
  return state;
}

test("stops follow the stays, are edited and saved, and Use suggested puts them back", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Japan", "2026-11-10", "2026-11-16");
  state.plans.push(
    stayAt("pl1", "Hotel Kumo Shinjuku", "2026-11-10", "2026-11-13", "fakePlaceTokyoInn1"),
    stayAt("pl2", "Machiya Inn Higashiyama", "2026-11-13", "2026-11-16", "fakePlaceKyotoInn1"),
  );
  await page.reload();

  // Two stays in two cities: a stop each, named by the city, with a travel day between.
  const stops = page.getByRole("list", { name: "Stops" });
  const tokyo = stops.getByRole("button", { name: /^Tokyo/ });
  const kyoto = stops.getByRole("button", { name: /^Kyoto/ });
  await expect(stops.getByRole("button")).toHaveCount(2);
  await expect(tokyo).toContainText("3 nights");
  await expect(kyoto).toContainText("3 nights");
  await expect(stops.getByRole("listitem", { name: /^Travel day/ })).toHaveCount(1);
  const pills = itineraryOf(page).getByRole("navigation", { name: "Days" });
  await expect(pills.getByTitle("Travel day: Tokyo to Kyoto", { exact: true })).toHaveCount(1);
  await expect(pills.getByTitle("Tokyo", { exact: true }).first()).toBeVisible();

  // A tap on a stop opens its first day.
  await kyoto.click();
  await expect(pills.getByRole("button", { name: /13/ })).toHaveAttribute("aria-current", "true");

  // Edit: they still follow the stays. A stop starting before the last one ends is refused, and nothing is sent.
  await page.getByRole("button", { name: "Edit stops" }).click();
  const sheet = page.getByRole("dialog", { name: "Stops" });
  await expect(sheet).toContainText("These follow your places to stay until you save them.");
  await expect(sheet.getByLabel("Name of stop 1")).toHaveValue("Tokyo");
  await expect(sheet.getByLabel("Stop 2 starts")).toHaveValue("2026-11-13");
  await sheet.getByLabel("Stop 2 starts").fill("2026-11-11");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet.getByRole("alert")).toContainText("overlap");
  expect(state.stopPuts).toEqual([]);

  // Rename Kyoto and meet in the middle a day earlier: saved as the stops.
  await sheet.getByLabel("Name of stop 2").fill("Kyoto and Nara");
  await sheet.getByLabel("Stop 1 ends").fill("2026-11-12");
  await sheet.getByLabel("Stop 2 starts").fill("2026-11-12");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toHaveCount(0);
  expect(state.stopPuts).toEqual([
    [
      { name: "Tokyo", start: "2026-11-10", end: "2026-11-12" },
      { name: "Kyoto and Nara", start: "2026-11-12", end: "2026-11-16" },
    ],
  ]);
  await expect(stops.getByRole("button", { name: /^Kyoto and Nara/ })).toContainText("4 nights");
  await expect(tokyo).toContainText("2 nights");
  await expect(pills.getByTitle("Travel day: Tokyo to Kyoto and Nara", { exact: true })).toHaveCount(1);

  // Saved stops no longer follow the stays; Use suggested puts them back.
  await page.getByRole("button", { name: "Edit stops" }).click();
  await expect(sheet).not.toContainText("These follow your places to stay");
  await sheet.getByRole("button", { name: "Use suggested" }).click();
  await expect(sheet).toHaveCount(0);
  expect(state.stopPuts.at(-1)).toEqual([]);
  await expect(stops.getByRole("button", { name: /^Kyoto and Nara/ })).toHaveCount(0);
  await expect(kyoto).toContainText("3 nights");
  await expect(tokyo).toContainText("3 nights");
});

test("a day's suggested label comes from its places, is marked Suggested, and is accepted from the pencil", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push(
    planOn("pl1", "Hanok Noodle Bar", "2026-11-11", { at: "12:00", place_id: "fakePlaceNoodle01" }),
    planOn("pl2", "Namdaemun Market", "2026-11-11", { at: "15:00", place_id: "fakePlaceMarket01" }),
  );
  await page.reload();
  const labels = () => (state.trips[0] as { day_labels: Record<string, string> }).day_labels;
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /11/ }).click();
  const dayTwo = page.locator("#day-2026-11-11");

  // The area both places are in and what they are; nothing is saved yet.
  await expect(dayTwo.getByRole("heading", { level: 3 })).toContainText("Jung-gu · food");
  await expect(dayTwo.locator(".suggest-chip")).toHaveText("Suggested");
  expect(labels()).toEqual({});
  // A day with nothing on it has nothing to suggest.
  await expect(page.locator("#day-2026-11-12").locator(".suggest-chip")).toHaveCount(0);

  // The pencil opens it filled in; saving keeps it, and the chip goes.
  await dayTwo.getByRole("button", { name: "Name this day" }).click();
  await expect(dayTwo.getByLabel("Name for this day")).toHaveValue("Jung-gu · food");
  await dayTwo.getByRole("button", { name: "Save" }).click();
  await expect.poll(labels).toEqual({ "2026-11-11": "Jung-gu · food" });
  await expect(dayTwo.getByRole("heading", { level: 3 })).toContainText("Jung-gu · food");
  await expect(dayTwo.locator(".suggest-chip")).toHaveCount(0);

  // Whatever is typed wins over the suggestion.
  await dayTwo.getByRole("button", { name: "Name this day" }).click();
  await dayTwo.getByLabel("Name for this day").fill("Noodle crawl");
  await dayTwo.getByRole("button", { name: "Save" }).click();
  await expect.poll(labels).toEqual({ "2026-11-11": "Noodle crawl" });
  await expect(dayTwo.getByRole("heading", { level: 3 })).toContainText("Noodle crawl");
  await expect(dayTwo.getByRole("heading", { level: 3 })).not.toContainText("Jung-gu");
});

test("the Ideas map pins ideas by list, rings the days, and a pin opens the picker with the nearest day first", async ({ page }) => {
  const state = await seoulWithIdeas(page, "test-browser-key");
  await showIdeasMap(page);
  expect(await page.evaluate(() => (window as unknown as { __map: { key: string } }).__map.key)).toBe("test-browser-key");

  // A pin for each idea with a position, in its list's colour; a ring and a name for each day with plans.
  await expect.poll(async () => (await drawn(page)).pins.map(([title]) => title).sort()).toEqual([
    "Day 2 · Jung-gu · food", "Day 3 · Jung-gu · food", "Hilltop Tower", "Lantern Alley",
  ]);
  const { pins, rings } = await drawn(page);
  expect(rings).toBe(2);
  const fill = (title: string) => pins.find(([t]) => t === title)![1];
  expect(fill("Lantern Alley")).toMatch(/^#[0-9a-f]{6}$/i); // a real colour, not a CSS variable Google can't read
  expect(fill("Hilltop Tower")).toMatch(/^#[0-9a-f]{6}$/i);
  expect(fill("Lantern Alley")).not.toBe(fill("Hilltop Tower")); // different lists, different colours
  // The idea with no position is listed under the map, not pinned.
  await expect(page.getByRole("region", { name: "Map" })).toContainText("Not on the map: link a place to pin it. Secret Garden");

  // Tap a pin: the day with the nearest plans comes first, with how far it is.
  await pressPin(page, "Hilltop Tower");
  const picker = page.getByRole("dialog", { name: "Put on a day" });
  await expect(picker).toContainText("Hilltop Tower");
  const closest = picker.getByRole("region", { name: "Closest days" });
  await expect(closest.getByRole("button")).toHaveCount(2);
  await expect(closest.getByRole("button").first()).toContainText("Day 3");
  await expect(closest.getByRole("button").first()).toContainText("1.3 km · 1 plan");
  await expect(closest.getByRole("button").nth(1)).toContainText("Day 2");
  await expect(closest.getByRole("button").nth(1)).toContainText("1.5 km · 1 plan");

  // Choosing it puts the idea on that day, after what's there.
  await closest.getByRole("button").first().click();
  await expect(picker).toHaveCount(0);
  await expect.poll(() => state.moves).toEqual(["pl4>2026-11-12@pl2"]);
  await openTab(page, "Plan");
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /12/ }).click();
  await expect(itineraryOf(page).getByRole("list", { name: /^Day 3/ })).toContainText("Hilltop Tower");
});

test("holding the Ideas map drops a pin that becomes an idea, then goes on a day shown on Plan", async ({ page }) => {
  const state = await seoulWithIdeas(page, "test-browser-key");
  await showIdeasMap(page);
  await expect.poll(async () => (await drawn(page)).rings).toBe(2);

  // A long press asks what to call the pin.
  await page.waitForFunction(() => Boolean((window as unknown as { __map?: { longPress?: unknown } }).__map?.longPress));
  await page.evaluate(() => (window as unknown as { __map: { longPress: (a: number, b: number) => void } }).__map.longPress(37.57, 126.99));
  const prompt = page.getByRole("dialog", { name: "Drop a pin here" });
  await expect(prompt.getByLabel("Name")).toHaveValue("Dropped pin");
  await prompt.getByLabel("Name").fill("Rooftop Bar");
  await prompt.getByRole("button", { name: "Save pin" }).click();

  // It is saved as an idea with the pin's own position, and the day picker opens for it.
  const picker = page.getByRole("dialog", { name: "Put on a day" });
  await expect(picker).toContainText("Rooftop Bar");
  expect(state.plans.find((p) => p.name === "Rooftop Bar")).toMatchObject({ id: "pl6", scheduled: false, lat: 37.57, lng: 126.99, place_id: null });
  const closest = picker.getByRole("region", { name: "Closest days" });
  await expect(closest.getByRole("button").first()).toContainText("Day 2");
  await expect(closest.getByRole("button").first()).toContainText("550 m");
  await closest.getByRole("button").first().click();
  await expect.poll(() => state.moves).toEqual(["pl6>2026-11-11@pl1"]);

  // On Plan, it is on Day 2.
  await openTab(page, "Plan");
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /11/ }).click();
  await expect(itineraryOf(page).getByRole("list", { name: /^Day 2/ })).toContainText("Rooftop Bar");
});

test("an idea's row says which day it is near, with its distance", async ({ page }) => {
  await seoulWithIdeas(page, "test-browser-key");
  await openTab(page, "Ideas");
  const rows = page.getByRole("list", { name: "Ideas" });
  await expect(rows.getByRole("listitem").filter({ hasText: "Lantern Alley" })).toContainText("Near Day 2 · 120 m");
  await expect(rows.getByRole("listitem").filter({ hasText: "Hilltop Tower" })).toContainText("Near Day 3 · 1.3 km");
  // No position: nothing to measure, so it is not called near anything.
  await expect(rows.getByRole("listitem").filter({ hasText: "Secret Garden" })).not.toContainText("Near Day");
});

test("without a map key the Ideas tab has no Map switch, but rows still say what is near", async ({ page }) => {
  await seoulWithIdeas(page, null);
  await openTab(page, "Ideas");
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Lantern Alley");
  await expect(page.getByRole("group", { name: "Show ideas as" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Map", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Map" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Near Day 2 · 120 m");
});

// --- scheduled moves, and moves recognised by a wallet's words ---------------------------

test("a scheduled move picks its wallet, which is only offered when it isn't spending", async ({ page }) => {
  const state = await fakeApi(page, { ibkr: true });
  await page.goto("/accounting/budgets");
  const form = page.getByRole("form", { name: "Add a scheduled payment" });
  await expect(form.getByLabel("Moves money to (optional)")).toHaveCount(0); // spending
  await form.getByLabel("Counts as spending").uncheck();
  const wallet = form.getByLabel("Moves money to (optional)");
  // Spending itself isn't offered.
  await expect(wallet.locator("option")).toHaveText(["No wallet", "Investments", "Savings", "Card", "IBKR"]);
  await form.getByLabel("Name").fill("IBKR top-up");
  await form.getByLabel("Next due").fill("2026-10-05");
  await form.getByLabel(/Amount/).fill("1000");
  await wallet.selectOption({ label: "IBKR" });
  await form.getByLabel("Counts as spending").check();
  await expect(wallet).toHaveCount(0); // hidden again for spending
  await form.getByLabel("Counts as spending").uncheck();
  await expect(wallet).toHaveValue("w-ibkr"); // and remembered
  await form.getByRole("button", { name: "Add", exact: true }).click();
  await expect.poll(() => state.bills[0]).toMatchObject({
    name: "IBKR top-up",
    spending: false,
    wallet: { id: "w-ibkr", name: "IBKR" },
  });

  const bills = page.getByRole("region", { name: "Scheduled payments" });
  const row = bills.getByRole("listitem").filter({ hasText: "IBKR top-up" });
  await expect(row.getByRole("heading")).toContainText("→ IBKR");
  await expect(row.getByRole("button", { name: "Link to a wallet" })).toHaveCount(0);
  // The form is reset for the next one.
  await expect(form.getByLabel("Counts as spending")).toBeChecked();

  // Marking it done says that the move was logged, and the move is in the ledger.
  await row.getByRole("button", { name: "Mark done" }).click();
  await expect(bills.getByRole("status")).toContainText(
    "logged a move of 1000.00 SGD from Spending to IBKR.",
  );
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Moves", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "IBKR top-up" })).toContainText("→ IBKR");
});

test("a payment that isn't spending can be linked to a wallet afterwards", async ({ page }) => {
  const state = await fakeApi(page, { ibkr: true });
  await page.goto("/accounting/budgets");
  const form = page.getByRole("form", { name: "Add a scheduled payment" });
  await form.getByLabel("Name").fill("Index fund");
  await form.getByLabel("Next due").fill("2026-10-05");
  await form.getByLabel(/Amount/).fill("500");
  await form.getByLabel("Counts as spending").uncheck();
  await form.getByRole("button", { name: "Add", exact: true }).click();
  const bills = page.getByRole("region", { name: "Scheduled payments" });
  const row = bills.getByRole("listitem").filter({ hasText: "Index fund" });
  await expect(row.getByRole("heading")).not.toContainText("→");

  // A spending payment never offers it.
  await form.getByLabel("Name").fill("Rent");
  await form.getByLabel("Next due").fill("2026-10-01");
  await form.getByRole("button", { name: "Add", exact: true }).click();
  const rent = bills.getByRole("listitem").filter({ hasText: "Rent" });
  await expect(rent.getByRole("button", { name: "Mark paid" })).toBeVisible();
  await expect(rent.getByRole("button", { name: "Link to a wallet" })).toHaveCount(0);

  await row.getByRole("button", { name: "Link to a wallet" }).click();
  const link = row.getByRole("form", { name: "Link Index fund to a wallet" });
  await expect(link.getByLabel("Wallet for Index fund").locator("option")).toHaveText([
    "Investments",
    "Savings",
    "Card",
    "IBKR",
  ]);
  await link.getByLabel("Wallet for Index fund").selectOption({ label: "IBKR" });
  await link.getByRole("button", { name: "Save" }).click();
  await expect(row.getByRole("heading")).toContainText("→ IBKR");
  await expect(row.getByRole("button", { name: "Link to a wallet" })).toHaveCount(0);
  expect(state.bills.find((b) => b.name === "Index fund")?.wallet).toMatchObject({ id: "w-ibkr" });
});

test("the Home nudge for a missed move settles with 'It went through' or 'Skip this month'", async ({ page }) => {
  const state = await fakeApi(page, { ibkr: true, missedMoves: true });
  await page.goto("/");
  const needs = page.getByRole("region", { name: "Needs you" });
  const ibkr = needs.getByRole("listitem").filter({ hasText: "IBKR top-up" });
  const savings = needs.getByRole("listitem").filter({ hasText: "Savings top-up" });
  await expect(ibkr).toContainText("Your SGD 1,000.00 IBKR top-up on 25 Sep hasn't shown up. Did it go through?");
  // Items without actions have no buttons.
  const email = needs.getByRole("listitem").filter({ hasText: "2 receipts from email" });
  await expect(email.getByRole("button")).toHaveCount(0);
  await expect(ibkr.getByRole("button")).toHaveText(["It went through", "Skip this month"]);

  await ibkr.getByRole("button", { name: "It went through" }).click();
  await expect(needs.getByText(/IBKR top-up on 25 Sep/)).toHaveCount(0);
  await expect(savings).toBeVisible();
  expect(state.missed).toEqual([{ bill: "move2", due: "2026-09-25" }]);

  await savings.getByRole("button", { name: "Skip this month" }).click();
  await expect(needs.getByText(/Savings top-up/)).toHaveCount(0);
  expect(state.missed).toEqual([]);
  await expect(needs.getByRole("link", { name: /Rent/ })).toBeVisible();

  // Only the one that went through is in the ledger, as a move.
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Moves", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "IBKR top-up" })).toContainText("→ IBKR");
  await expect(page.getByRole("row").filter({ hasText: "Savings top-up" })).toHaveCount(0);
});

test("a nudge's button shows the error inline when the API refuses", async ({ page }) => {
  await fakeApi(page, { ibkr: true, missedMoves: true });
  await page.route("**/api/bills/move1/paid*", (route) =>
    route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "that bill has nothing left to pay" }) }),
  );
  await page.goto("/");
  const needs = page.getByRole("region", { name: "Needs you" });
  const ibkr = needs.getByRole("listitem").filter({ hasText: "IBKR top-up" });
  await ibkr.getByRole("button", { name: "It went through" }).click();
  await expect(ibkr.getByRole("alert")).toHaveText("that bill has nothing left to pay");
  await expect(ibkr.getByRole("button", { name: "It went through" })).toBeEnabled();
});

test("an import preview shows rows that name a wallet as moves, and sends back what it shows", async ({ page }) => {
  const state = await fakeApi(page, { ibkr: true });
  await page.goto("/settings/import");
  await page.getByLabel("Choose a CSV or PDF").setInputFiles({
    name: "sept.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "Date,Description,Amount\n" +
        "28/09/2026,IBKR deposit,-500.00\n" +
        "28/09/2026,Kopitiam,-4.20\n" +
        "28/09/2026,IBKR withdrawal,200.00\n" +
        "28/09/2026,IBKR monthly,-300.00\n",
    ),
  });
  const preview = page.getByRole("region", { name: "Check before importing" });
  const row = (name: string) => preview.getByRole("row").filter({ hasText: name });
  await expect(row("IBKR deposit")).toContainText("Move → IBKR");
  await expect(row("IBKR withdrawal")).toContainText("Move IBKR → Spending");
  await expect(row("IBKR deposit")).not.toContainText("Other");
  // An ordinary row is as it was: its category, and no move controls.
  await expect(row("Kopitiam")).toContainText("Other");
  await expect(row("Kopitiam").getByRole("button")).toHaveCount(0);

  // The wallet can be changed, and a move can go back to being an ordinary entry.
  await row("IBKR monthly").getByLabel("Wallet for IBKR monthly").selectOption({ label: "Savings" });
  await expect(row("IBKR monthly")).toContainText("Move → Savings");
  await row("IBKR withdrawal").getByRole("button", { name: "Income instead" }).click();
  await expect(row("IBKR withdrawal")).toContainText("Ordinary entry");
  await expect(row("IBKR withdrawal")).not.toContainText("Move IBKR");

  await preview.getByRole("button", { name: "Import 4 transactions" }).click();
  await expect(page.getByRole("status").getByText("Imported 4 transactions.")).toBeVisible();
  expect(state.importBodies).toEqual([
    {
      include: [0, 1, 2, 3],
      moves: [
        { row: 0, as_move: "w-ibkr" },
        { row: 3, as_move: "w-savings" },
      ],
    },
  ]);
});

test("an unticked move row is not sent, and an ordinary entry can be made a move again", async ({ page }) => {
  const state = await fakeApi(page, { ibkr: true });
  await page.goto("/settings/import");
  await page.getByLabel("Choose a CSV or PDF").setInputFiles({
    name: "sept.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Date,Description,Amount\n28/09/2026,IBKR deposit,-500.00\n28/09/2026,IBKR monthly,-300.00\n"),
  });
  const preview = page.getByRole("region", { name: "Check before importing" });
  await preview.getByRole("checkbox", { name: "Import IBKR deposit" }).uncheck();
  const monthly = preview.getByRole("row").filter({ hasText: "IBKR monthly" });
  await monthly.getByRole("button", { name: "Expense instead" }).click();
  await expect(monthly).toContainText("Ordinary entry");
  await monthly.getByRole("button", { name: "Make it a move" }).click();
  await expect(monthly).toContainText("Move → IBKR");
  await preview.getByRole("button", { name: "Import 1 transaction" }).click();
  await expect(page.getByRole("status").getByText("Imported 1 transaction.")).toBeVisible();
  expect(state.importBodies).toEqual([{ include: [1], moves: [{ row: 1, as_move: "w-ibkr" }] }]);
});

test("an email that names a wallet asks whether it was a move", async ({ page }) => {
  const state = await fakeApi(page, { emailConnected: true, ibkr: true, emailMove: true });
  await page.goto("/settings/email");
  const checked = page.getByRole("region", { name: "Checked emails" });
  const ibkr = checked.getByRole("listitem").filter({ hasText: "Transfer to IBKR" });
  await expect(ibkr.getByText("Was this a move to IBKR?")).toBeVisible();
  await expect(ibkr.getByRole("button")).toHaveText(["Move", "Expense", "Skip"]);
  // The other pending email has no such question.
  const grab = checked.getByRole("listitem").filter({ hasText: "Your Grab e-receipt" });
  await expect(grab.getByText(/Was this a move/)).toHaveCount(0);
  await expect(grab.getByRole("button", { name: "Log it" })).toBeVisible();

  await ibkr.getByRole("button", { name: "Move" }).click();
  await expect(ibkr.getByText("Logged")).toBeVisible();
  await expect(ibkr.getByText(/Was this a move/)).toHaveCount(0);
  expect(state.emailMoves).toEqual([{ id: "e4", body: {} }]);

  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Moves", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "IBKR" })).toContainText("→ IBKR");
});

test("'Expense' on a move question logs the email as usual", async ({ page }) => {
  const state = await fakeApi(page, { emailConnected: true, ibkr: true, emailMove: true });
  await page.goto("/settings/email");
  const ibkr = page.getByRole("region", { name: "Checked emails" }).getByRole("listitem").filter({ hasText: "Transfer to IBKR" });
  await ibkr.getByRole("button", { name: "Expense" }).click();
  await expect(ibkr.getByText("Logged")).toBeVisible();
  expect(state.emailMoves).toEqual([]);
});

test("entries that look like moves are reviewed one at a time from the Wallets card", async ({ page }) => {
  const state = await fakeApi(page, { ibkr: true, likelyMoves: true });
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Wallets" });
  await expect(card.getByText("2 entries look like moves")).toBeVisible();
  await card.getByRole("button", { name: "Review" }).click();

  const review = card.getByRole("group", { name: "Review likely moves" });
  await expect(review).toContainText("IBKR Cash Deposit");
  await expect(review).toContainText("The description names IBKR.");
  await expect(review.getByLabel("Moved to")).toHaveValue("w-ibkr"); // the API's own suggestion
  await review.getByRole("button", { name: "Make it a move" }).click();
  await expect.poll(() => state.txs.find((t) => t.id === "t201")?.direction).toBe("move");
  expect(state.txs.find((t) => t.id === "t201")?.to_wallet?.name).toBe("IBKR");

  // Next: money in, with no suggested wallet, so one has to be picked before it's a move.
  await expect(review).toContainText("FAST Transfer");
  await expect(review.getByLabel("Moved from")).toHaveValue("");
  await expect(review.getByRole("button", { name: "Make it a move" })).toBeDisabled();
  await review.getByRole("button", { name: "Not a move" }).click();
  await expect(card.getByText("That's all of them.")).toBeVisible();
  expect(state.txs.find((t) => t.id === "t202")?.direction).toBe("in"); // nothing was changed
});

// --- finding by stop, day or theme, and research into ideas -------------------------------

/** The scope chip (with its menu) and the theme chips of the finder that is open. */
const lookIn = (page: Page) => page.getByRole("group", { name: "Look in" });
const scopeChip = (page: Page) => lookIn(page).getByRole("button", { name: /^Look in:/ });
/** Opens the scope menu and picks one: "Whole trip", "In Kyoto", "Near Day 2"… */
async function lookInPick(page: Page, name: string | RegExp) {
  await scopeChip(page).click();
  await lookIn(page).getByRole("menuitemradio", { name }).click();
}
const openFinder = (page: Page) => page.getByRole("button", { name: "Find ideas", exact: true }).click();
const themesOf = (page: Page) => page.getByRole("group", { name: "Themes" });
const finderBox = (page: Page) => page.getByRole("search", { name: "Search Google Maps" }).getByLabel("Look for");

/** A Japan trip of three days in Tokyo then three in Kyoto, from stays linked to a place in each. */
async function japanWithStops(page: Page) {
  const state = await fakeApi(page);
  await addTrip(page, "Japan", "2026-11-10", "2026-11-16");
  state.plans.push(
    stayAt("pl1", "Hotel Kumo Shinjuku", "2026-11-10", "2026-11-13", "fakePlaceTokyoInn1"),
    stayAt("pl2", "Machiya Inn Higashiyama", "2026-11-13", "2026-11-16", "fakePlaceKyotoInn1"),
  );
  await page.reload();
  return state;
}

test("a search looks in one stop or the whole trip, and asks again when the scope changes", async ({ page }) => {
  const state = await japanWithStops(page);
  await openTab(page, "Ideas");
  await openFinder(page);

  // One chip with the scope, and a menu of the whole trip, each stop and the day open on Plan. The stop of that day is where it begins.
  const scope = lookIn(page);
  await expect(scopeChip(page)).toHaveAccessibleName("Look in: In Tokyo");
  await expect(page.getByRole("dialog", { name: "Find ideas" })).toContainText("In Tokyo.");
  await scopeChip(page).click();
  await expect(scope.getByRole("menuitemradio")).toHaveText(["Whole trip", "In Tokyo", "In Kyoto", /^Near Day 1/]);
  await expect(scope.getByRole("menuitemradio", { name: "In Tokyo" })).toHaveAttribute("aria-checked", "true");
  await expect(scope.getByRole("menuitemradio", { name: "Whole trip" })).toHaveAttribute("aria-checked", "false");

  // "In Kyoto" sends the stop with both requests; the trip's destination isn't in the text.
  await scope.getByRole("menuitemradio", { name: "In Kyoto" }).click();
  await expect(scopeChip(page)).toHaveAccessibleName("Look in: In Kyoto");
  await finderBox(page).fill("best ramen");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Results" });
  await expect(results).toContainText("Hanok Noodle Bar");
  await expect.poll(() => state.placeScopes).toEqual([{ q: "best ramen", trip_id: "trip1", stop: "Kyoto", day: null }]);
  await expect.poll(() => state.ideaScopes).toEqual([{ q: "best ramen", stop: "Kyoto", day: null }]);

  // Looking somewhere else asks the same question again, there.
  await lookInPick(page, "In Tokyo");
  await expect.poll(() => state.placeScopes.at(-1)).toEqual({ q: "best ramen", trip_id: "trip1", stop: "Tokyo", day: null });
  await expect.poll(() => state.ideaScopes.at(-1)).toEqual({ q: "best ramen", stop: "Tokyo", day: null });
  await lookInPick(page, "Whole trip");
  await expect(page.getByRole("dialog", { name: "Find ideas" })).toContainText("Across Tokyo and Kyoto.");
  await expect.poll(() => state.placeScopes.at(-1)).toEqual({ q: "best ramen", trip_id: "trip1", stop: null, day: null });
  await expect.poll(() => state.ideaScopes.at(-1)).toEqual({ q: "best ramen", stop: null, day: null });
  expect(state.placeScopes).toHaveLength(3);
});

test("a theme chip fills the search and runs it, and what is saved goes in a list of that theme", async ({ page }) => {
  const state = await japanWithStops(page);
  await openTab(page, "Ideas");
  await openFinder(page);
  const themes = themesOf(page);
  await expect(themes.getByRole("button")).toHaveText(["Food", "Sights", "Museums", "Nature", "Shopping", "Nightlife", "Rainy day"]);

  await themes.getByRole("button", { name: "Food" }).click();
  await expect(finderBox(page)).toHaveValue("Best food");
  await expect(themes.getByRole("button", { name: "Food" })).toHaveAttribute("aria-pressed", "true");
  const results = page.getByRole("list", { name: "Results" });
  await expect(results).toContainText("Lantern Alley");
  // It began on the stop of the open day, and guides were read too: it is an idea-ish query.
  await expect.poll(() => state.placeScopes).toEqual([{ q: "Best food", trip_id: "trip1", stop: "Tokyo", day: null }]);
  await expect.poll(() => state.ideaScopes).toEqual([{ q: "Best food", stop: "Tokyo", day: null }]);

  // Saved under the theme, not the guide's kind (Nightlife).
  await results.getByRole("button", { name: "Save: Lantern Alley" }).click();
  await expect.poll(() => state.plans.at(-1)).toMatchObject({ name: "Lantern Alley", day: null, list_name: "Food", place_id: null });
  await expect(results.getByRole("button", { name: "Lantern Alley is saved" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Lantern Alley");

  // Typing by hand lets the theme go: a next save is filed by the guide's kind.
  await openFinder(page);
  await themesOf(page).getByRole("button", { name: "Rainy day" }).click();
  await expect(finderBox(page)).toHaveValue("Rainy day");
  await finderBox(page).fill("best quiet cafes");
  await expect(themesOf(page).getByRole("button", { name: "Rainy day" })).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("list", { name: "Results" }).getByRole("button", { name: "Save: Lantern Alley" }).click();
  await expect.poll(() => state.plans.at(-1)).toMatchObject({ name: "Lantern Alley", list_name: "Nightlife" });
});

test("Find ideas near here on a day opens the finder near it, adds to that day, and Plan shows it there", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  state.plans.push(planOn("pl1", "Hanok Noodle Bar", "2026-11-11", { at: "12:00", place_id: "fakePlaceNoodle01" }));
  await page.reload();
  await itineraryOf(page).getByRole("navigation", { name: "Days" }).getByRole("button", { name: /11/ }).click();
  const day2 = page.locator("#day-2026-11-11");
  await day2.getByRole("button", { name: "Find ideas near here, Day 2" }).click();

  // It opens on "Near Day 2", the day it was opened from.
  const sheet = page.getByRole("dialog");
  await expect(scopeChip(page)).toHaveAccessibleName(/^Look in: Near Day 2/);
  await expect(sheet).toContainText("Within about 2 km of Day 2's plans.");
  await finderBox(page).fill("best coffee");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Results" });
  await expect(results).toContainText("Lantern Alley");
  await expect.poll(() => state.placeScopes).toEqual([{ q: "best coffee", trip_id: "trip1", stop: null, day: "2026-11-11" }]);
  await expect.poll(() => state.ideaScopes).toEqual([{ q: "best coffee", stop: null, day: "2026-11-11" }]);

  // Each result can be kept as an idea, or put on that day.
  await expect(results.getByRole("button", { name: "Save: Lantern Alley" })).toBeVisible();
  await results.getByRole("button", { name: "Add to Day 2: Lantern Alley" }).click();
  await expect.poll(() => state.plans.at(-1)).toMatchObject({ name: "Lantern Alley", day: "2026-11-11", list_name: null });
  await expect(sheet).toContainText("Added Lantern Alley to Day 2.");
  await page.keyboard.press("Escape");
  await expect(day2).toContainText("Lantern Alley");
  await expect(day2).toContainText("Hanok Noodle Bar");

  // Widening to the whole trip asks again, with no day; Add to Day goes away with the scope.
  await day2.getByRole("button", { name: "Find ideas near here, Day 2" }).click();
  await finderBox(page).fill("best coffee");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(results).toContainText("Namdaemun Market");
  await lookInPick(page, "Whole trip");
  await expect.poll(() => state.placeScopes.at(-1)).toEqual({ q: "best coffee", trip_id: "trip1", stop: null, day: null });
  await expect(results.getByRole("button", { name: /^Add to Day 2:/ })).toHaveCount(0);
});

test("a place found by Google Maps and by a guide is one card, with its rating, why and both tags", async ({ page }) => {
  const state = await fakeApi(page);
  await addTrip(page, "Seoul", "2026-11-10", "2026-11-13");
  await openTab(page, "Ideas");
  await openFinder(page);
  await finderBox(page).fill("best noodles");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Results" });
  // Google's four places and the guide's one without a match: the noodle bar comes once, not twice.
  await expect(results.getByRole("listitem")).toHaveCount(5);
  await expect.poll(() => state.ideaSearches).toEqual(["best noodles"]);
  const card = results.getByRole("listitem").filter({ hasText: "Hanok Noodle Bar" });
  await expect(card).toHaveCount(1);
  await expect(card.getByLabel("Rated 4.6 out of 5 from 2310 ratings")).toBeVisible();
  await expect(card).toContainText("“Hand-pulled noodles worth the queue.”");
  await expect(card.getByRole("link", { name: "Seoul's best noodles" })).toHaveAttribute("href", "https://food.example.com/seoul-noodles");
  await expect(card).toContainText("Google Maps");
  await expect(card).toContainText("From a guide");
  // A place only one of them knew says only that.
  const market = results.getByRole("listitem").filter({ hasText: "Namdaemun Market" });
  await expect(market).toContainText("Google Maps");
  await expect(market).not.toContainText("From a guide");
  const alley = results.getByRole("listitem").filter({ hasText: "Lantern Alley" });
  await expect(alley).toContainText("From a guide");
  await expect(alley).not.toContainText("Google Maps");
  // Saving the merged card keeps the Google place.
  await card.getByRole("button", { name: "Save: Hanok Noodle Bar" }).click();
  await expect.poll(() => state.plans.filter((p) => p.name === "Hanok Noodle Bar")).toHaveLength(1);
  expect(state.plans[0]).toMatchObject({ name: "Hanok Noodle Bar", place_id: "fakePlaceNoodle01" });
});

test("research areas are saved to an existing trip: a duplicate is skipped, and the ideas sit under each area", async ({ page }) => {
  const state = await fakeApi(page, { research: true });
  await addTrip(page, "Osaka", "2027-01-06", "2027-01-17");
  state.plans.push(idea("pl1", "Senso-ji"));
  await page.reload();
  await page.goto("/travel/research/rs1");

  // A box for each area with things to do, all ticked.
  const shinjuku = page.getByRole("checkbox", { name: "Save its ideas from Shinjuku" });
  const asakusa = page.getByRole("checkbox", { name: "Save its ideas from Asakusa" });
  await expect(shinjuku).toBeChecked();
  await expect(asakusa).toBeChecked();
  await expect(page.getByText("Saves the things to do in 2 of 2 areas as ideas.")).toBeVisible();
  await shinjuku.uncheck();
  await expect(page.getByText("Saves the things to do in 1 of 2 areas as ideas.")).toBeVisible();
  await asakusa.uncheck();
  await expect(page.getByRole("button", { name: "Add to a trip…" })).toBeDisabled();
  await shinjuku.check();
  await asakusa.check();

  await page.getByRole("button", { name: "Add to a trip…" }).click();
  await expect(page.getByRole("heading", { name: "Which trip?" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "Which trip?" })).toHaveCount(0);
  expect(state.researchIdeaPosts).toEqual([]);

  await page.getByRole("button", { name: "Add to a trip…" }).click();
  await page.getByRole("button", { name: /^Osaka/ }).click();
  await expect(page.getByRole("heading", { name: "Ideas added" })).toBeVisible();
  expect(state.researchIdeaPosts).toEqual([{ run: "rs1", trip_id: "trip1", areas: ["Shinjuku", "Asakusa"] }]);
  // Senso-ji was already an idea on the trip.
  await expect(page.getByText("Added 3 ideas to Osaka (1 was already there).")).toBeVisible();

  // They are on Ideas, one list per area.
  await page.getByRole("link", { name: "See them on the trip's Ideas tab" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip1\?tab=ideas/);
  const lists = page.getByRole("group", { name: "Lists" });
  await expect(lists.getByRole("button", { name: /^Shinjuku/ })).toBeVisible();
  await lists.getByRole("button", { name: /^Asakusa/ }).click();
  const places = page.getByRole("list", { name: "Ideas" });
  await expect(places).toContainText("Nakamise street");
  await expect(places).toContainText("Kappabashi");
  await expect(places).not.toContainText("Senso-ji");
  await lists.getByRole("button", { name: /^Shinjuku/ }).click();
  await expect(places).toContainText("Gyoen garden");
  expect(state.plans.filter((p) => p.list_name === "Asakusa").map((p) => p.name)).toEqual(["Nakamise street", "Kappabashi"]);
});

test("the research's city is offered as a stop, says what it changes, and is saved with the stops made room", async ({ page }) => {
  const state = await fakeApi(page, { research: true });
  // The trip starts four days before the research's dates, so Osaka has to end where Tokyo starts.
  await addTrip(page, "Osaka", "2027-01-06", "2027-01-17");
  await page.goto("/travel/research/rs1");
  await page.getByRole("button", { name: "Add to a trip…" }).click();
  await page.getByRole("button", { name: /^Osaka/ }).click();
  await expect(page.getByRole("heading", { name: "Ideas added" })).toBeVisible();
  await expect(page.getByText("Added 4 ideas to Osaka.")).toBeVisible();

  const offer = page.locator(".research-stop");
  await expect(offer).toContainText("Add Tokyo as a stop for");
  await expect(offer).toContainText(/Osaka would end on .*10/);
  expect(state.stopPuts).toEqual([]);
  await offer.getByRole("button", { name: "Add Tokyo as a stop" }).click();
  await expect(page.getByText("Added Tokyo as a stop.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the trip" }).last()).toBeVisible();
  // The new stop kept whole; the old one ends on its first day.
  expect(state.stopPuts).toEqual([
    [
      { name: "Osaka", start: "2027-01-06", end: "2027-01-10" },
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-17" },
    ],
  ]);
  await expect(offer).toHaveCount(0);
  await page.getByRole("link", { name: "Open the trip" }).last().click();
  const stops = page.getByRole("list", { name: "Stops" });
  await expect(stops.getByRole("button")).toHaveCount(2);
  await expect(stops.getByRole("button", { name: /^Tokyo/ })).toBeVisible();
});

test("after Make it a trip, the areas' ideas are added to the new trip when asked", async ({ page }) => {
  const state = await fakeApi(page, { research: true });
  await page.goto("/travel/research/rs1");
  // Only Asakusa's, this time.
  await page.getByRole("checkbox", { name: "Save its ideas from Shinjuku" }).uncheck();
  await page.getByRole("button", { name: "Make it a trip" }).click();
  await expect(page.getByRole("heading", { name: "Add the ideas from these areas to the trip too?" })).toBeVisible();
  await expect(page).toHaveURL(/\/travel\/research\/rs1$/);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ideas added" })).toBeVisible();
  expect(state.researchIdeaPosts).toEqual([{ run: "rs1", trip_id: "trip9", areas: ["Asakusa"] }]);
  await expect(page.getByText("Added 3 ideas to Tokyo.")).toBeVisible();
  // The research is for Tokyo and so is the trip: no stop to offer.
  await expect(page.locator(".research-stop")).toHaveCount(0);
  await page.getByRole("link", { name: "See them on the trip's Ideas tab" }).click();
  await expect(page).toHaveURL(/\/travel\/trips\/trip9\?tab=ideas/);
  await expect(page.getByRole("list", { name: "Ideas" })).toContainText("Nakamise street");
});

// A voice note in the chat. Chromium has no microphone here, so the page gets a stand-in
// for getUserMedia and MediaRecorder (the upload and the replies are real).
const STUB_RECORDER = () => {
  const w = window as unknown as Record<string, unknown>;
  class StubRecorder {
    static isTypeSupported(type: string) {
      return type === "audio/webm;codecs=opus";
    }
    state = "inactive";
    mimeType: string;
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    constructor(_stream: unknown, options?: { mimeType?: string }) {
      this.mimeType = options?.mimeType ?? "audio/webm";
    }
    start() {
      this.state = "recording";
      (w.__recording as { on: boolean }).on = true;
    }
    stop() {
      this.state = "inactive";
      (w.__recording as { on: boolean }).on = false;
      this.ondataavailable?.({ data: new Blob(["pretend voice"], { type: this.mimeType }) });
      this.onstop?.();
    }
  }
  w.__recording = { on: false, tracksStopped: 0 };
  w.MediaRecorder = StubRecorder;
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: async () => ({
        getTracks: () => [{ stop: () => ((w.__recording as { tracksStopped: number }).tracksStopped += 1) }],
      }),
    },
  });
};

test("a voice note in the chat is sent and answered like a typed message", async ({ page }) => {
  await page.addInitScript(STUB_RECORDER);
  const state = await fakeApi(page);
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  // The mic stands where Send does while the box is empty.
  await expect(chat.getByRole("button", { name: "Send" })).toHaveCount(0);
  await chat.getByRole("button", { name: "Record a voice note" }).click();
  await expect(chat.getByRole("status").filter({ hasText: "Recording" })).toBeVisible();
  await expect(chat.getByLabel("Message")).toBeDisabled();
  await expect(chat.getByRole("button", { name: "Cancel recording" })).toBeVisible();
  await expect(chat.getByText(/^0:0[1-9]$/)).toBeVisible(); // the timer is running
  await chat.getByRole("button", { name: "Stop and send" }).click();

  await expect(chat.locator(".msg-user").last()).toHaveText("🎙 Voice note…");
  await expect(chat.locator(".msg-bot").first()).toContainText("Delete 2026-09-27");
  await chat.getByRole("button", { name: "Confirm" }).click();
  await expect(chat.getByText("Deleted.")).toBeVisible();
  expect(state.voiceSent).toHaveLength(1);
  expect(state.voiceSent[0]).toMatchObject({ filename: "voice.webm", contentType: "audio/webm;codecs=opus" });
  expect(state.voiceSent[0].bytes).toBeGreaterThan(0);
  expect(await page.evaluate(() => (window as unknown as { __recording: { tracksStopped: number } }).__recording.tracksStopped)).toBe(1);
  // Nothing sideways on a phone or a desktop.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a voice note that is too long is refused in the server's words", async ({ page }) => {
  await page.addInitScript(STUB_RECORDER);
  const state = await fakeApi(page, { voiceFails: 413 });
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await chat.getByRole("button", { name: "Record a voice note" }).click();
  await chat.getByRole("button", { name: "Stop and send" }).click();
  await expect(chat.getByRole("alert")).toHaveText("That's too long — keep voice notes under 2 minutes.");
  await expect(chat.getByText("🎙 Voice note…")).toHaveCount(0);
  expect(state.voiceSent).toHaveLength(1);
  await expect(chat.getByRole("button", { name: "Record a voice note" })).toBeVisible();
});

test("cancelling a recording sends nothing", async ({ page }) => {
  await page.addInitScript(STUB_RECORDER);
  const state = await fakeApi(page);
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await chat.getByRole("button", { name: "Record a voice note" }).click();
  await chat.getByRole("button", { name: "Cancel recording" }).click();
  await expect(chat.getByRole("button", { name: "Record a voice note" })).toBeVisible();
  expect(state.voiceSent).toHaveLength(0);
  expect(await page.evaluate(() => (window as unknown as { __recording: { on: boolean } }).__recording.on)).toBe(false);
});

test("without a microphone the chat says so and still types", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true }));
  await fakeApi(page);
  await page.goto("/accounting");
  await page.getByRole("button", { name: "Ask Nexus", exact: true }).filter({ visible: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  const mic = chat.getByRole("button", { name: "Record a voice note" });
  await expect(mic).toHaveAttribute("aria-disabled", "true");
  await mic.click({ force: true }); // aria-disabled, not disabled: a tap still explains
  await expect(chat.getByText("Mic isn't available here — send a voice note in the Telegram chat instead.")).toBeVisible();
  await chat.getByLabel("Message").fill("delete the grab ride");
  await expect(chat.getByRole("button", { name: "Send" })).toBeEnabled();
});
