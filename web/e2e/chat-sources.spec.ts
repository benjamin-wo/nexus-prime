import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// A web answer in the chat: its sources are small link chips under the reply, which open the
// page outside the app. Made-up data only.

test("a web answer's sources show as link chips that open the page", async ({ page }) => {
  await fakeApi(page);
  await page.addInitScript(() => {
    (window as unknown as { __opened: string[] }).__opened = [];
    window.open = ((url: string) => {
      (window as unknown as { __opened: string[] }).__opened.push(url);
      return null;
    }) as typeof window.open;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Ask Kaya", exact: true }).filter({ visible: true }).click();
  const chat = page.getByRole("dialog", { name: "Chat" });
  await chat.getByLabel("Message").fill("How much is a PS6 in Singapore?");
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(chat.getByText(/About 500 SGD/)).toBeVisible();

  const sources = chat.getByRole("group", { name: "Sources" });
  const chips = sources.getByRole("link");
  await expect(chips).toHaveText(["HardwareZone↗", "XE↗", "Embassy of Japan↗"]);
  // Compact: no taller than 34px, wider than tall, nothing sideways even at a phone's width.
  for (const chip of await chips.all()) {
    const box = await chip.boundingBox();
    expect(box!.height).toBeLessThanOrEqual(34);
    expect(box!.width).toBeGreaterThan(box!.height);
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await chips.nth(1).click();
  expect(await page.evaluate(() => (window as unknown as { __opened: string[] }).__opened)).toEqual([
    "https://www.xe.com/currencyconverter/",
  ]);
});
