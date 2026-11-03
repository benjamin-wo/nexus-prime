import { expect, type Page, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Today is Monday 28 September 2026 in Singapore, the month the made-up entries (27 September) are in.
test.use({ timezoneId: "Asia/Singapore", reducedMotion: "reduce" });

async function open(page: Page, options: Parameters<typeof fakeApi>[1] = {}) {
  const state = await fakeApi(page, options);
  await page.clock.setFixedTime(new Date("2026-09-28T04:00:00Z"));
  return state;
}

const walletsCard = (page: Page) => page.getByRole("region", { name: "Wallets" });
const row = (page: Page, name: string) => page.getByRole("row").filter({ has: page.getByRole("button", { name, exact: true }) });

test("add a card's details, make it the usual card, and an expense is paid with it", async ({ page }) => {
  await open(page);
  await page.goto("/settings");
  const card = walletsCard(page);
  await card.getByText("Manage", { exact: true }).click();
  const yours = card.getByRole("list", { name: "Your wallets" });

  // Cash is there from the start and, like Spending, can be renamed but not deleted.
  const cash = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Cash", exact: true }) });
  await expect(cash.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(cash.getByRole("button", { name: "Delete" })).toHaveCount(0);

  // The card's details: the box keeps only the last 4 digits of what is pasted, and says so.
  const plain = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Card", exact: true }) });
  await plain.getByRole("button", { name: "Edit" }).click();
  const edit = card.getByRole("form", { name: "Edit Card" });
  await edit.getByLabel("Bank").fill("Citi");
  await edit.getByLabel("Card", { exact: true }).fill("PremierMiles");
  await edit.getByLabel("Network").selectOption({ label: "Visa" });
  const last4 = edit.getByLabel("Last 4 digits");
  await expect(last4).toHaveAttribute("inputmode", "numeric");
  await last4.fill("0000 0000 0000 4321");
  await expect(last4).toHaveValue("4321");
  await expect(edit.getByText("Only the last 4 digits are kept.")).toBeVisible();
  await edit.getByRole("button", { name: "Save" }).click();

  const citi = yours.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Card ·· 4321" }) });
  await expect(citi).toBeVisible();
  await expect(citi.getByText("Citi · PremierMiles · Visa")).toBeVisible();

  // The usual card: one at a time, and it can be cleared.
  const usual = card.getByLabel("Usual card");
  await expect(card.getByText("Used when you don't say which card")).toBeVisible();
  await usual.selectOption({ label: "Card ·· 4321" });
  await expect(citi.getByText("Usual card")).toBeVisible();
  await usual.selectOption({ label: "None" });
  await expect(citi.getByText("Usual card")).toHaveCount(0);
  await usual.selectOption({ label: "Card ·· 4321" });
  await expect(citi.getByText("Usual card")).toBeVisible();

  // A new expense starts on it, and the ledger names it under the merchant.
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  const paidWith = sheet.getByLabel("Paid with");
  await expect(paidWith).toHaveValue("w-card");
  await expect(paidWith.locator("option")).toHaveText(["Card ·· 4321", "Spending", "Cash", "Not set", "+ Add a card…"]);
  await sheet.getByLabel("Amount").fill("8.40");
  await sheet.getByLabel("Paid to").fill("Kopi");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await expect(row(page, "Kopi").getByText("Card ·· 4321")).toBeVisible();

  // Money in and moves have no card to pick.
  await page.getByRole("button", { name: "Add transaction" }).click();
  const another = page.getByRole("dialog");
  await another.getByRole("button", { name: "Money in", exact: true }).click();
  await expect(another.getByLabel("Paid with")).toHaveCount(0);
  await another.getByRole("button", { name: "Move", exact: true }).click();
  await expect(another.getByLabel("Paid with")).toHaveCount(0);
});

test("with one card and no usual card, a new expense starts on that card and is saved with it", async ({ page }) => {
  await open(page);
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await expect(sheet.getByLabel("Paid with")).toHaveValue("w-card");
  await sheet.getByLabel("Amount").fill("3.20");
  await sheet.getByLabel("Paid to").fill("Teh");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await expect(row(page, "Teh").getByText("Card", { exact: true })).toBeVisible();
});

test("with several cards and no usual card, the sheet asks which card", async ({ page }) => {
  await open(page, { cards: true });
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  const paidWith = sheet.getByLabel("Paid with");
  await expect(paidWith).toHaveValue("");
  await expect(paidWith.locator("option:checked")).toHaveText("Which card?");
  await sheet.getByLabel("Amount").fill("2.00");
  await sheet.getByLabel("Paid to").fill("Toast Box");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await expect(row(page, "Toast Box").getByText("Citi PremierMiles")).toHaveCount(0);
  await expect(row(page, "Toast Box").getByText("DBS Altitude")).toHaveCount(0);
});

test("add a card from the entry sheet, keep what was typed, and save the expense paid with it", async ({ page }) => {
  await open(page, { cards: true });
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await sheet.getByLabel("Amount").fill("8.40");
  await sheet.getByLabel("Paid to").fill("Kopi");

  const paidWith = sheet.getByLabel("Paid with");
  await paidWith.selectOption({ label: "+ Add a card…" });
  const form = sheet.getByRole("form", { name: "New card" });

  // Cancel puts the select back where it was.
  await form.getByRole("button", { name: "Cancel new card" }).click();
  await expect(form).toBeHidden();
  await expect(paidWith.locator("option:checked")).toHaveText("Which card?");

  await paidWith.selectOption({ label: "+ Add a card…" });
  await form.getByLabel("Bank").fill("OCBC");
  await form.getByLabel("Card", { exact: true }).fill("Frank");
  await form.getByLabel("Network").selectOption({ label: "Mastercard" });
  const last4 = form.getByLabel("Last 4 digits");
  await last4.fill("0000 0000 0000 4321");
  await expect(last4).toHaveValue("4321");
  await expect(form.getByText("Only the last 4 digits are kept.")).toBeVisible();
  await form.getByLabel("Make this my usual card").check();
  await form.getByRole("button", { name: "Add card" }).click();

  await expect(form).toBeHidden();
  await expect(paidWith.locator("option:checked")).toHaveText("OCBC Frank ·· 4321");
  await expect(sheet.getByLabel("Amount")).toHaveValue("8.40");
  await expect(sheet.getByLabel("Paid to")).toHaveValue("Kopi");
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await expect(row(page, "Kopi").getByText("OCBC Frank ·· 4321")).toBeVisible();

  // It is now the usual card: the next expense starts on it.
  await page.getByRole("button", { name: "Add transaction" }).click();
  await expect(page.getByRole("dialog").getByLabel("Paid with").locator("option:checked")).toHaveText("OCBC Frank ·· 4321");
});

test("a card that can't be added shows why inside the form", async ({ page }) => {
  await open(page, { cards: true });
  await page.goto("/accounting/ledger");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const sheet = page.getByRole("dialog", { name: "Log money out" });
  await sheet.getByLabel("Paid with").selectOption({ label: "+ Add a card…" });
  const form = sheet.getByRole("form", { name: "New card" });
  // "Citi PremierMiles" is a wallet already.
  await form.getByLabel("Bank").fill("Citi");
  await form.getByLabel("Card", { exact: true }).fill("PremierMiles");
  await form.getByRole("button", { name: "Add card" }).click();
  await expect(form.getByRole("alert")).toHaveText("a wallet with that name already exists");
  await expect(form).toBeVisible();
});

test("change an entry's card, and filter the ledger by a card or by Not set", async ({ page }) => {
  await open(page, { cards: true });
  await page.goto("/accounting/ledger");
  await expect(row(page, "Maxwell Food Centre").getByText("Citi PremierMiles ·· 4321")).toBeVisible();
  await expect(row(page, "Grab").getByText("DBS Altitude ·· 8765")).toBeVisible();

  // Open the Grab entry: it shows its card, and another can be picked.
  await page.getByRole("button", { name: "Grab", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await expect(sheet.getByLabel("Paid with")).toHaveValue("w-dbs");
  await sheet.getByLabel("Paid with").selectOption({ label: "Cash" });
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await expect(row(page, "Grab").getByText("Cash", { exact: true })).toBeVisible();
  await expect(row(page, "Grab").getByText("DBS Altitude ·· 8765")).toHaveCount(0);

  // The Paid with filter lists what can pay, never investment or savings wallets.
  const filter = page.getByRole("combobox", { name: "Paid with" });
  await expect(filter.locator("option")).toHaveText([
    "Paid with: any",
    "Card",
    "Citi PremierMiles ·· 4321",
    "DBS Altitude ·· 8765",
    "Spending",
    "Cash",
    "Not set",
  ]);

  // One card: its entries only, in the address and as a chip that takes it off.
  await filter.selectOption({ label: "Citi PremierMiles ·· 4321" });
  await expect(page).toHaveURL(/paid_with=w-citi/);
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Grab", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Employer", exact: true })).toHaveCount(0);
  const chip = page.locator(".filter-chip").filter({ hasText: "Paid with" });
  await expect(chip).toContainText("Citi PremierMiles ·· 4321");
  // Export carries it.
  await page.getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("menuitem", { name: "Export CSV" })).toHaveAttribute("href", "/api/export.csv?paid_with=w-citi");
  await page.keyboard.press("Escape");

  // It sits beside the other filters.
  await page.getByRole("button", { name: "Money out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();

  await chip.getByRole("button").click();
  await expect(page).not.toHaveURL(/paid_with/);
  await expect(chip).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Grab", exact: true })).toBeVisible();

  // Not set: Grab is paid with Cash now, so put it back to nothing and look for it.
  await page.getByRole("button", { name: "Grab", exact: true }).click();
  await sheet.getByLabel("Paid with").selectOption({ label: "Not set" });
  await sheet.getByRole("button", { name: "Save" }).click();
  await expect(sheet).toBeHidden();
  await filter.selectOption({ label: "Not set" });
  await expect(page).toHaveURL(/paid_with=none/);
  await expect(page.getByRole("button", { name: "Grab", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toHaveCount(0);
  await expect(page.locator(".filter-chip").filter({ hasText: "Paid with" })).toContainText("Not set");
});

test("each card shows what it paid for this month and links to its entries", async ({ page }) => {
  await open(page, { cards: true });
  await page.goto("/settings");
  const group = walletsCard(page).getByRole("group", { name: "Spend by card" });
  const citi = group.getByRole("listitem").filter({ hasText: "Citi PremierMiles ·· 4321" });
  await expect(citi).toContainText(/SGD.12\.40 this month · 1 purchase/);
  await expect(group.getByRole("listitem").filter({ hasText: "DBS Altitude ·· 8765" })).toContainText(/SGD.25\.00 this month · 1 purchase/);
  await expect(group.getByRole("listitem").filter({ hasText: "Cash" })).toContainText(/SGD.0\.00 this month · 0 purchases/);
  await expect(group.getByRole("listitem").filter({ hasText: "Investments" })).toHaveCount(0);

  // Another month, with the month picker.
  await group.getByRole("button", { name: "Previous month" }).click();
  await expect(citi).toContainText(/SGD.0\.00 in August 2026 · 0 purchases/);
  await group.getByRole("button", { name: "Next month" }).click();
  await expect(citi).toContainText("this month");

  await citi.getByRole("link", { name: /See in ledger/ }).click();
  await expect(page).toHaveURL(/\/accounting\/ledger\?paid_with=w-citi$/);
  await expect(page.getByRole("button", { name: "Maxwell Food Centre", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Grab", exact: true })).toHaveCount(0);
});
