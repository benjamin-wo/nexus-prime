import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Someone using the keyboard must see where they are. The focus outline is `outline: 2px solid var(--ring)`;
// if --ring ever stops being a colour (it once did, when the progress ring registered --ring as a
// percentage) every outline computes to none and nothing shows. So this tabs through real pages and reads
// what the browser computes.

type Seen = { tag: string; text: string; shown: boolean; how: string };

/** What the focused element, or the card round it, shows to say it has focus. */
async function focusIndicator(page: Page): Promise<Seen> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement;
    const outlined = (e: Element) => {
      const s = getComputedStyle(e);
      return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0;
    };
    let how = "";
    if (outlined(el)) how = "outline";
    // A text field shows focus with a border and a ring of shadow instead of the outline.
    else if (getComputedStyle(el).boxShadow !== "none" && el.matches("input, select, textarea")) how = "shadow";
    // A card whose whole face is one link outlines the card (:focus-within) rather than the link.
    else if (el.closest(".trip-card, .trip-row") && outlined(el.closest(".trip-card, .trip-row")!)) how = "card outline";
    return { tag: el.tagName.toLowerCase(), text: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 30), shown: how !== "", how };
  });
}

/** Tab through a page a number of times; every stop must show where the focus is. */
async function tabThrough(page: Page, route: string, stops: number) {
  await page.goto(route);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(page.getByText("Loading…")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  const seen: Seen[] = [];
  for (let i = 0; i < stops; i++) {
    await page.keyboard.press("Tab");
    seen.push(await focusIndicator(page));
  }
  // Not just the first few stops, which are the same side rail on every page.
  expect(new Set(seen.map((s) => `${s.tag}:${s.text}`)).size, `${route}: Tab moved on`).toBeGreaterThan(stops / 2);
  expect(
    seen.filter((s) => !s.shown).map((s) => `${s.tag} "${s.text}"`),
    `${route}: stops with no visible focus`,
  ).toEqual([]);
}

test.describe("keyboard focus is visible", () => {
  test.skip(({ isMobile }) => isMobile, "a keyboard, on a desktop");

  test("--ring is a colour, and the outline it draws is not none", async ({ page }) => {
    await fakeApi(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    const ring = await page.evaluate(() => {
      const probe = document.createElement("button");
      probe.style.cssText = "outline: 2px solid var(--ring); position: absolute; left: -999px;";
      document.body.append(probe);
      const outline = getComputedStyle(probe).outlineStyle;
      const colour = getComputedStyle(probe).outlineColor;
      probe.remove();
      return { outline, colour };
    });
    expect(ring.outline).toBe("solid");
    expect(ring.colour).not.toBe("rgba(0, 0, 0, 0)");
  });

  for (const [name, route, stops] of [
    ["Home", "/", 14],
    ["the ledger", "/accounting/ledger", 14],
    ["the portfolio", "/investment", 12],
    ["Travel", "/travel", 14],
    ["Settings", "/settings", 14],
  ] as const) {
    test(`Tab shows its place on ${name}`, async ({ page }) => {
      await fakeApi(page, { todayItems: true, tripMode: true, research: true });
      await tabThrough(page, route, stops);
    });
  }

  test("the trip card outlines itself when its link has focus", async ({ page }) => {
    await fakeApi(page, { tripMode: true });
    await page.goto("/travel");
    const link = page.locator(".trip-card-link").first();
    await link.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(link).toBeFocused();
    const card = page.locator(".trip-card").first();
    expect(await card.evaluate((e) => getComputedStyle(e).outlineStyle)).toBe("solid");
  });

  test("the month shown in the spending chart is outlined", async ({ page }) => {
    await fakeApi(page, { today: "2026-11-02" });
    await page.goto("/accounting?month=2026-09");
    const chart = page.getByRole("region", { name: "Spending by month" });
    await expect(chart.locator(".month.picked")).toHaveCount(1);
    const bar = chart.locator(".month.picked .month-bar");
    expect(await bar.evaluate((e) => getComputedStyle(e).outlineStyle)).toBe("solid");
    expect(await bar.evaluate((e) => parseFloat(getComputedStyle(e).outlineWidth))).toBeGreaterThan(0);
  });
});
