import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// A drag in the chat belongs to the chat: it scrolls the messages, and neither pulls the page behind it to
// refresh nor slides the chat down with it.
test.use({ viewport: { width: 390, height: 700 } });
test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "mobile", "needs a touch screen");
});

/** How many times Home's data has been fetched: a pull-to-refresh fetches it again. */
function countHomeFetches(page: Page): () => number {
  let n = 0;
  page.on("request", (req) => {
    if (req.method() === "GET" && new URL(req.url()).pathname === "/api/home") n += 1;
  });
  return () => n;
}

async function drag(page: Page, x: number, from: number, to: number) {
  const cdp = await page.context().newCDPSession(page);
  const send = (type: "touchStart" | "touchMove" | "touchEnd", y?: number) =>
    cdp.send("Input.dispatchTouchEvent", { type, touchPoints: y === undefined ? [] : [{ x, y }] });
  const step = from < to ? 15 : -15;
  await send("touchStart", from);
  for (let i = 1; i <= 20; i++) await send("touchMove", from + step * i);
  await send("touchEnd");
  await page.waitForTimeout(400);
}

test("a hard swipe down in the chat scrolls the chat, not the page", async ({ page }) => {
  await fakeApi(page, { chatHistory: true, todayItems: true });
  const homeFetches = countHomeFetches(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Money this month" })).toBeVisible();
  await page.getByRole("button", { name: "Ask Nexus" }).last().click();

  const drawer = page.locator(".drawer");
  const messages = drawer.locator(".messages");
  await expect(messages).toContainText("SGD 12.40 on Dining Out so far.");
  await messages.evaluate((el) => {
    const filler = document.createElement("div");
    filler.style.height = "2000px";
    el.prepend(filler);
    el.scrollTop = el.scrollHeight;
  });
  const box = (await messages.boundingBox())!;
  const before = await messages.evaluate((el) => el.scrollTop);
  const fetched = homeFetches();

  const ptr = page.locator(".main-viewport");
  const cdp = await page.context().newCDPSession(page);
  const send = (type: "touchStart" | "touchMove" | "touchEnd", y?: number) =>
    cdp.send("Input.dispatchTouchEvent", { type, touchPoints: y === undefined ? [] : [{ x: 180, y }] });
  const mid = Math.round(box.y + box.height / 2);
  const tops: number[] = [];
  let pulled = false;
  await send("touchStart", mid);
  for (let i = 1; i <= 20; i++) {
    await send("touchMove", mid + 15 * i);
    pulled ||= await ptr.evaluate((el) => el.classList.contains("ptr-active"));
    tops.push((await drawer.boundingBox())!.y);
  }
  await send("touchEnd");
  await page.waitForTimeout(400);

  expect(pulled).toBe(false);
  expect(tops.every((top) => top === 0)).toBe(true);
  expect(await messages.evaluate((el) => el.scrollTop)).toBeLessThan(before);
  expect(homeFetches()).toBe(fetched);
});

test("the page keeps its place and its pull to refresh after the chat closes", async ({ page }) => {
  await fakeApi(page, { chatHistory: true, todayItems: true });
  const homeFetches = countHomeFetches(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Money this month" })).toBeVisible();
  const main = page.locator(".main-viewport");
  await main.evaluate((el) => {
    el.scrollTop = 150;
  });
  const placed = await main.evaluate((el) => el.scrollTop);
  expect(placed).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Ask Nexus" }).last().click();
  await expect(page.locator(".drawer")).toBeVisible();
  await expect(main).toHaveCSS("overflow-y", "hidden");
  await page.getByRole("button", { name: "Close chat" }).click();
  await expect(page.locator(".drawer")).toHaveCount(0);
  await expect(main).not.toHaveCSS("overflow-y", "hidden");
  expect(await main.evaluate((el) => el.scrollTop)).toBe(placed);

  await main.evaluate((el) => {
    el.scrollTop = 0;
  });
  const fetched = homeFetches();
  await drag(page, 180, 200, 500);
  await expect.poll(homeFetches).toBeGreaterThan(fetched);
});
