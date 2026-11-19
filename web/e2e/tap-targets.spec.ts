import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// On a touch screen every control needs a hit area of at least 44 x 44 px (a finger is about that big).
// A control may be smaller to look at if its hit area is bigger: padding, or an ::after box. So this does
// not read the element's own size alone: it walks outwards from the control's centre with elementFromPoint,
// along the horizontal and the vertical line, for as long as the point still lands on the control (or its
// label), and the run must be at least 44 px each way.

const MIN = 44;
const REACH = 60;
/** A box edge that falls between two pixels measures one pixel short. */
const SLACK = 1;
const CONTROLS = 'button, a[href], [role="button"], [role="tab"], [role="switch"], input[type="checkbox"]';

/** Controls that may stay small, and why. Keep it short: a real control belongs in the CSS instead. */
const ALLOWED: { selector: string; why: string }[] = [
  // WCAG 2.5.8 lets a link sit inside a sentence at the size of its text, and a superscript cannot grow
  // without covering its neighbours.
  { selector: "a.cite", why: "a numbered source mark inside a sentence of research text (WCAG 2.5.8 inline exception)" },
  // The Costs bar chart shows up to 90 days across a phone, 4 px each: no hit area can be 44 px wide.
  // The day's figures are in the list under the chart too.
  // A notification is a link round its whole sentence, as a sentence in a paragraph (WCAG 2.5.8).
  { selector: ".note-text a", why: "a notification's own sentence, a link in running text (WCAG 2.5.8 inline exception)" },
  { selector: ".cost-hit", why: "one of 30 to 90 bars of a chart across a phone: they cannot each be 44 px wide" },
  // Visually hidden until focused: it has no hit area while it is hidden.
  { selector: ".ptr-button:not(:focus-visible)", why: "the pull-to-refresh button for keyboard users, hidden until focused" },
];

type Bad = { tag: string; text: string; cls: string; size: string; hit: string };

/** Every visible control on the page whose own hit area is smaller than 44 x 44. */
async function smallControls(page: Page): Promise<Bad[]> {
  return page.evaluate(
    ({ CONTROLS, MIN, REACH, ALLOWED }) => {
      const bad: Bad[] = [];
      const own = (el: Element, x: number, y: number) => {
        const hit = document.elementFromPoint(x, y);
        if (!hit) return false;
        if (el === hit || el.contains(hit)) return true;
        const label = hit.closest("label");
        return !!label && (label as HTMLLabelElement).control === el;
      };
      /** How far the control's hit area runs from (x, y) in one direction, in px. */
      const run = (el: Element, x: number, y: number, dx: number, dy: number) => {
        let n = 0;
        while (n < REACH && own(el, x + dx * (n + 1), y + dy * (n + 1))) n++;
        return n;
      };
      for (const el of Array.from(document.querySelectorAll<HTMLElement>(CONTROLS))) {
        if (el.closest("[aria-hidden='true'], [inert], [hidden]")) continue;
        const style = getComputedStyle(el);
        if (style.visibility === "hidden" || style.display === "none" || style.pointerEvents === "none") continue;
        if (el.getBoundingClientRect().width === 0 || el.getBoundingClientRect().height === 0) continue;
        if (ALLOWED.some((a) => el.matches(a.selector))) continue;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const cx = Math.round(rect.left + rect.width / 2);
        const cy = Math.round(rect.top + rect.height / 2);
        // A control that something else covers at its centre (a sheet over the page) is not tappable at all.
        if (!own(el, cx, cy)) continue;
        const w = 1 + run(el, cx, cy, -1, 0) + run(el, cx, cy, 1, 0);
        const h = 1 + run(el, cx, cy, 0, -1) + run(el, cx, cy, 0, 1);
        if (w < MIN || h < MIN) {
          bad.push({
            tag: el.tagName.toLowerCase(),
            text: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40),
            cls: String(el.className).slice(0, 60),
            size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
            hit: `${w}x${h}`,
          });
        }
      }
      return bad;
    },
    { CONTROLS, MIN: MIN - SLACK, REACH, ALLOWED },
  );
}

async function ready(page: Page, route: string) {
  await page.goto(route);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(page.getByText("Loading…")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500); // the reveal animation
}

const ROUTES = [
  "/",
  "/accounting",
  "/accounting/ledger",
  "/accounting/budgets",
  "/accounting/cashflow",
  "/investment",
  "/investment/watchlist",
  "/investment/plans",
  "/investment/plans/p1",
  "/investment/stocks/AMD",
  "/travel",
  "/travel/trips/tripnow",
  "/travel/trips/tripnow?tab=ideas",
  "/travel/trips/tripnow?tab=money",
  "/travel/trips/tripnow?tab=prep",
  "/travel/research/rs1",
  "/settings",
  "/settings/updates",
  "/settings/time-zone",
  "/settings/shared-trips",
  "/settings/notifications",
  "/settings/voice",
  "/settings/email",
  "/settings/import",
  "/settings/categories",
  "/settings/wallets",
  "/settings/rules",
  "/settings/memory",
  "/settings/data",
  "/settings/costs",
];

test.describe("every control has a hit area of 44 px on a touch screen", () => {
  test.skip(({ isMobile }) => !isMobile, "a touch screen");

  test("the phone reports a coarse pointer", async ({ page }) => {
    await fakeApi(page);
    await page.goto("/");
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
  });

  // Sheets and drawers that open over a page.
  const OPENED: [string, string, (page: Page) => Promise<void>][] = [
    ["the entry sheet", "/", (page) => page.getByRole("button", { name: "Log expense" }).click()],
    ["the chat drawer", "/", (page) => page.getByRole("button", { name: "Ask Nexus" }).first().click()],
    ["the ledger's Select mode", "/accounting/ledger", (page) => page.getByRole("button", { name: "Select", exact: true }).click()],
    ["the ledger's filters", "/accounting/ledger", (page) => page.getByRole("button", { name: /^Filter/ }).click()],
    ["the trip's share sheet", "/travel/trips/tripnow", (page) => page.getByRole("button", { name: "Share the plan" }).click()],
    ["the trip's options", "/travel/trips/tripnow", (page) => page.getByRole("button", { name: "Trip options" }).click()],
    ["a ledger entry", "/accounting/ledger", (page) => page.getByRole("button", { name: "Maxwell Food Centre" }).first().click()],
    ["the trip's add sheet", "/travel/trips/tripnow", (page) => page.getByRole("button", { name: /^Add/ }).last().click()],
  ];
  for (const [name, route, open] of OPENED) {
    test(`${name} (${route})`, async ({ page }) => {
      await fakeApi(page, { todayItems: true, tripMode: true, research: true });
      await ready(page, route);
      await open(page);
      await page.waitForTimeout(600);
      const bad = await smallControls(page);
      const lines = bad.map((b) => `${b.tag}.${b.cls.replace(/ /g, ".")} "${b.text}" ${b.size} hit ${b.hit}`);
      expect(lines, `${name}: controls with a hit area under ${MIN} px`).toEqual([]);
    });
  }

  for (const route of ROUTES) {
    test(route, async ({ page }) => {
      await fakeApi(page, { todayItems: true, tripMode: true, research: true });
      await ready(page, route);
      const bad = await smallControls(page);
      const lines = bad.map((b) => `${b.tag}.${b.cls.replace(/ /g, ".")} "${b.text}" ${b.size} hit ${b.hit}`);
      expect(lines, `${route}: controls with a hit area under ${MIN} px`).toEqual([]);
    });
  }
});
