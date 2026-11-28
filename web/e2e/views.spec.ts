import { expect, test } from "@playwright/test";

import { fakeApi, openChat } from "./fake-api";

// Prime brings a view into the chat as a card (ADR 0005). Mocked API, made-up figures. Set SHOT_DIR to also save pictures.
const SHOTS = process.env.SHOT_DIR;

async function ask(page: import("@playwright/test").Page, text: string) {
  await openChat(page);
  const chat = page.getByRole("dialog", { name: "Chat" });
  await chat.getByLabel("Message").fill(text);
  await chat.getByRole("button", { name: "Send" }).click();
  return chat;
}

test("how am I doing this month? gives an outlook card, and Open shows the page", async ({ page }, info) => {
  const phone = info.project.name === "mobile";
  await fakeApi(page, { views: true, today: "2026-09-27" });
  await page.goto("/app");
  const chat = await ask(page, "how am I doing this month?");

  const card = chat.getByRole("region", { name: "Your outlook for September 2026" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Left at month end")).toBeVisible();
  await expect(card).toContainText("2,899.50");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/views-outlook-chat-${phone ? "phone" : "desktop"}.png` });

  await card.getByRole("button", { name: /^Open/ }).click();
  await expect(page).toHaveURL(/\/accounting\?month=2026-09$/);
  if (phone) {
    // The chat closed; a slim bar brings it back where it was.
    await expect(page.getByRole("dialog", { name: "Chat" })).toBeHidden();
    await expect(page.getByText(/spent in September/)).toBeVisible();
    const back = page.getByRole("button", { name: "← Back to chat" });
    await expect(back).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/views-back-to-chat-phone.png` });
    await back.click();
    await expect(page.getByRole("dialog", { name: "Chat" }).getByRole("region", { name: "Your outlook for September 2026" })).toBeVisible();
    await expect(back).toBeHidden();
  } else {
    // The page changed behind the chat, which is still open.
    await expect(chat).toBeVisible();
    await expect(chat.getByRole("region", { name: "Your outlook for September 2026" })).toBeVisible();
    await expect(page.getByText(/spent in September/)).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/views-open-behind-chat-desktop.png` });
  }
});

test("had chicken rice gives the day's food card", async ({ page }, info) => {
  const phone = info.project.name === "mobile";
  await fakeApi(page, { views: true, showHealth: true });
  await page.goto("/app");
  const chat = await ask(page, "had chicken rice");
  const card = chat.getByRole("region", { name: "Your day" });
  await expect(card).toBeVisible();
  await expect(card.getByText("1 logged")).toBeVisible();
  await expect(card).toContainText("about 675 kcal");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/views-health-today-${phone ? "phone" : "desktop"}.png` });
});

test("with views off the chat has no cards", async ({ page }) => {
  await fakeApi(page, { views: false });
  await page.goto("/app");
  const chat = await ask(page, "how am I doing this month?");
  await expect(chat.getByText(/Delete 2026-09-27/)).toBeVisible();
  await expect(chat.getByRole("region")).toHaveCount(0);
});
