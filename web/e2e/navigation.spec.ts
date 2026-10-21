import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Names, navigation and Settings: where pages live, how the bottom bar reads, the Ledger's menu.

const OLD_ADDRESSES: [string, RegExp, string][] = [
  ["/accounting/plan", /\/accounting\/budgets$/, "Budgets"],
  ["/plan", /\/accounting\/budgets$/, "Budgets"],
  ["/budgets", /\/accounting\/budgets$/, "Budgets"],
  ["/accounting/email", /\/settings\/email$/, "Receipts by email"],
  ["/email", /\/settings\/email$/, "Receipts by email"],
  ["/accounting/import", /\/settings\/import$/, "Import a statement"],
  ["/import", /\/settings\/import$/, "Import a statement"],
];

for (const [old, now, heading] of OLD_ADDRESSES) {
  test(`the old address ${old} lands on ${heading}`, async ({ page }) => {
    await fakeApi(page, { emailConnected: true });
    await page.goto(old);
    await expect(page).toHaveURL(now);
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
  });
}

test("Accounting has four tabs, and Investment's plans are Trade plans", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting");
  await expect(page.getByRole("navigation", { name: "Accounting pages" }).getByRole("link")).toHaveText([
    "Overview",
    "Ledger",
    "Budgets",
    "Cash flow",
  ]);
  await page.goto("/investment");
  await expect(page.getByRole("navigation", { name: "Investment pages" }).getByRole("link")).toHaveText([
    "Portfolio",
    "Watchlist",
    "Trade plans",
  ]);
  await page.getByRole("navigation", { name: "Investment pages" }).getByRole("link", { name: "Trade plans" }).click();
  await expect(page).toHaveURL(/\/investment\/plans$/);
  await expect(page.getByRole("heading", { name: "Trade plans", level: 1 })).toBeVisible();
});

test("Settings leads to Receipts by email and back, with Settings still marked", async ({ page, isMobile }) => {
  await fakeApi(page, { emailConnected: true });
  await page.goto("/settings");
  await expect(page.locator("h2.section-title")).toHaveText(["Notifications", "Connections", "Your data"]);
  await page.getByRole("region", { name: "Receipts by email" }).getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/settings\/email$/);
  await expect(page.getByRole("region", { name: "Checked emails" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Accounting pages" })).toHaveCount(0);
  if (!isMobile) {
    const rail = page.getByRole("navigation", { name: "Main", exact: true });
    await expect(rail.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  }
  await page.getByRole("link", { name: "Back to Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);

  await page.getByRole("region", { name: "Import a statement" }).getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/settings\/import$/);
  await expect(page.getByLabel("Choose a CSV or PDF")).toBeVisible();
  await page.getByRole("link", { name: "Back to Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
});

test("the Ledger has a compact Add and a More menu that opens, closes and goes to the import", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  const add = page.getByRole("button", { name: "Add transaction" });
  await expect(add).toBeVisible();
  expect((await add.boundingBox())!.width).toBeLessThan(120);
  const more = page.getByRole("button", { name: "More" });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("link", { name: "Import statement" })).toHaveCount(0);

  await more.click();
  await expect(more).toHaveAttribute("aria-expanded", "true");
  const menu = page.getByRole("menu", { name: "More" });
  await expect(menu.getByRole("menuitem")).toHaveText(["Import statement", "Export CSV"]);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(more).toBeFocused();

  await more.click();
  await page.getByRole("heading", { name: "Ledger", level: 1 }).click();
  await expect(menu).toHaveCount(0);

  await more.click();
  await page.getByRole("menuitem", { name: "Import statement" }).click();
  await expect(page).toHaveURL(/\/settings\/import$/);
  await expect(page.getByRole("heading", { name: "Import a statement", level: 1 })).toBeVisible();
});

test("the Ledger's Dates control is one select, and Custom dates shows From and To", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  await expect(page.getByRole("group", { name: "When" })).toHaveCount(0);
  const dates = page.getByRole("combobox", { name: "Dates" });
  await expect(dates).toHaveValue("any");
  await expect(page.getByLabel("From")).toHaveCount(0);
  await dates.selectOption("this");
  await expect(dates).toHaveValue("this");
  await dates.selectOption("custom");
  await expect(page.getByLabel("From")).toBeVisible();
  await expect(page.getByLabel("To", { exact: true })).toBeVisible();
  await dates.selectOption("any");
  await expect(page.getByLabel("From")).toHaveCount(0);
  // The type tabs and the search are in the same filter box.
  await expect(page.getByRole("group", { name: "Show" }).getByRole("button")).toHaveText([
    "All",
    "Money out",
    "Money in",
    "Moves",
    "Pending",
  ]);
  await expect(page.getByRole("searchbox", { name: "Search merchant or notes" })).toBeVisible();
});

test("a Ledger row names its category under the merchant on a phone, and in its column on a wide screen", async ({ page, isMobile }) => {
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  const row = page.getByRole("row").filter({ hasText: "Maxwell Food Centre" });
  const caption = row.locator(".category-line");
  if (isMobile) {
    await expect(caption).toBeVisible();
    await expect(caption).toHaveText("Dining Out");
    // Under the merchant, and clear of the amount on the right.
    const merchant = (await row.getByRole("button", { name: "Maxwell Food Centre" }).boundingBox())!;
    const category = (await caption.boundingBox())!;
    const amount = (await row.locator("td.amount").boundingBox())!;
    expect(category.y).toBeGreaterThanOrEqual(merchant.y + merchant.height - 2);
    expect(category.x + category.width).toBeLessThanOrEqual(amount.x + 1);
  } else {
    await expect(caption).toBeHidden();
    await expect(row.locator("td.secondary")).toContainText("Dining Out");
  }
});

test("the bottom bar on a phone has a short label under each icon, and nothing spills", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "the bottom bar is a phone's");
  await fakeApi(page);
  for (const width of [390, 320, 280]) {
    await page.setViewportSize({ width, height: 640 });
    await page.goto("/");
    const bar = page.getByRole("navigation", { name: "Main (mobile)" });
    await expect(bar).toBeVisible();
    for (const label of ["Home", "Money", "Invest", "Travel"]) {
      await expect(bar.getByText(label, { exact: true }), `${label} at ${width}px`).toBeVisible();
    }
    // The names a screen reader hears still say what each is.
    const names = await bar.getByRole("link").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label") ?? e.textContent));
    expect(names).toEqual(["Home", "Money (Accounting)", "Invest (Investment)", "Travel"]);
    await expect(bar.getByRole("button", { name: "Ask Nexus" })).toBeVisible();

    const problems = await bar.evaluate((el, w) => {
      const out: string[] = [];
      const bounds = (e: Element) => e.getBoundingClientRect();
      for (const target of el.querySelectorAll("a, button")) {
        const r = bounds(target);
        const name = target.getAttribute("aria-label") ?? target.textContent;
        if (r.left < 0 || r.right > w + 0.5) out.push(`${name} is outside the screen`);
        if (r.height < 44) out.push(`${name} is ${r.height}px tall`);
        if (r.width < 44) out.push(`${name} is ${r.width}px wide`);
      }
      for (const label of el.querySelectorAll(".nav-label")) {
        if (label.scrollWidth > label.clientWidth + 0.5) out.push(`${label.textContent} is clipped`);
      }
      if (document.documentElement.scrollWidth > document.documentElement.clientWidth) out.push("the page scrolls sideways");
      return out;
    }, width);
    expect(problems, `bottom bar at ${width}px`).toEqual([]);
  }
});

test("the bottom bar marks where you are, by weight as well as colour", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "the bottom bar is a phone's");
  await fakeApi(page);
  await page.goto("/accounting/ledger");
  const bar = page.getByRole("navigation", { name: "Main (mobile)" });
  const money = bar.getByRole("link", { name: "Money (Accounting)" });
  await expect(money).toHaveAttribute("aria-current", "page");
  const weight = (name: string) =>
    bar.getByRole("link", { name }).locator(".nav-label").evaluate((e) => Number(getComputedStyle(e).fontWeight));
  expect(await weight("Money (Accounting)")).toBeGreaterThan(await weight("Home"));
});

test("the rail on a wide screen keeps the full names", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "the rail is for wide screens");
  await fakeApi(page);
  await page.goto("/");
  const rail = page.getByRole("navigation", { name: "Main", exact: true });
  await expect(rail.getByRole("link")).toHaveText(["Home", "Accounting", "Investment", "Travel", "Settings"]);
});
