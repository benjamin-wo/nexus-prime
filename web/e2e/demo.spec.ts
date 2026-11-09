import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const banner = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Demo account" });
const openChat = (page: import("@playwright/test").Page) =>
  page.getByRole("button", { name: "Ask Kaya", exact: true }).filter({ visible: true }).click();

test("a signed-out visitor sees the landing page and goes into the demo from it", async ({ page }) => {
  const state = await fakeApi(page, { signedIn: false });
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("A personal finance and travel assistant you talk to, on Telegram and the web.")).toBeVisible();
  // The demo leads, with the Telegram sign-in under it.
  const demo = page.getByRole("link", { name: "Try the live demo" });
  const widget = page.locator(".tg-login");
  await expect(widget).toHaveCount(1);
  const [demoBox, widgetBox] = [await demo.boundingBox(), await widget.boundingBox()];
  expect(demoBox!.y).toBeLessThan(widgetBox!.y);

  await demo.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(banner(page)).toContainText("Demo · made-up data · resets in 23 h · Sign in with Telegram to use your own");
  expect(state.demoStarts).toBe(1);
  // /demo isn't left behind in the history: back doesn't start another demo.
  await page.goBack();
  expect(state.demoStarts).toBe(1);
});

test("the /demo link goes straight in", async ({ page }) => {
  const state = await fakeApi(page, { signedIn: false });
  await page.goto("/demo");
  await expect(page).toHaveURL(/\/$/);
  await expect(banner(page)).toBeVisible();
  expect(state.demoStarts).toBe(1);
});

test("the banner can be closed for the session, and its Telegram link signs the demo out", async ({ page }) => {
  await fakeApi(page, { demo: true });
  await page.goto("/");
  await expect(banner(page)).toBeVisible();
  await banner(page).getByRole("button", { name: "Dismiss demo notice" }).click();
  await expect(banner(page)).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(banner(page)).toHaveCount(0);

  // A new session shows it again; the link signs out to the sign-in page.
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await banner(page).getByRole("button", { name: "Sign in with Telegram" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("link", { name: "Try the live demo" })).toBeVisible();
});

test("the chat offers suggestions that send, and counts the messages left", async ({ page }) => {
  const state = await fakeApi(page, { demo: true, demoMessages: 3 });
  await page.goto("/");
  await openChat(page);
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.getByText("3 messages left")).toBeVisible();
  const chips = chat.getByRole("group", { name: "Suggestions" });
  await expect(chips.getByRole("button")).toHaveText([
    "How's my dining budget?",
    "Plan Saturday in Kyoto",
    "I spent 12.50 on lunch at Kopi Corner",
    "What moved in my portfolio today?",
  ]);
  await chips.getByRole("button", { name: "How's my dining budget?" }).click();
  await expect(chat.getByText("Here's what I found in the demo data.")).toBeVisible();
  expect(state.chatSent).toEqual(["How's my dining budget?"]);
  await expect(chat.getByText("2 messages left")).toBeVisible();
  await expect(chips).toHaveCount(0);
});

test("when the messages run out, the reply says so", async ({ page }) => {
  await fakeApi(page, { demo: true, demoMessages: 1 });
  await page.goto("/");
  await openChat(page);
  const chat = page.getByRole("dialog", { name: "Chat" });
  await chat.getByRole("button", { name: "Plan Saturday in Kyoto" }).click();
  await expect(chat.getByText("1 message left")).toHaveCount(0);
  await expect(chat.getByText("0 messages left")).toBeVisible();
  await chat.getByLabel("Message").fill("one more");
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(chat.getByText("That's the end of the demo's messages.")).toBeVisible();
});

test("the suggestions are there for a real user too, without a banner or a count", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/");
  await expect(banner(page)).toHaveCount(0);
  await openChat(page);
  const chat = page.getByRole("dialog", { name: "Chat" });
  await expect(chat.getByRole("button", { name: "What moved in my portfolio today?" })).toBeVisible();
  await expect(chat.getByText(/messages? left/)).toHaveCount(0);
});

test("a demo hides what only a real account has", async ({ page }) => {
  await fakeApi(page, { demo: true });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Wallets/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Receipts by email/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /^Shared trips/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /^Model costs/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Invite someone" })).toHaveCount(0);
});

test("a switched-off demo says it is resting and offers the Telegram sign-in", async ({ page }) => {
  await fakeApi(page, { signedIn: false, demoStart: "off" });
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "The demo is resting right now" })).toBeVisible();
  await expect(page.locator('.tg-login script[data-telegram-login="nexus_test_bot"]')).toHaveCount(1);
  await expect(page).toHaveURL(/\/demo$/);
});

test("too many demos from one network says to try later", async ({ page }) => {
  await fakeApi(page, { signedIn: false, demoStart: "limited" });
  await page.goto("/demo");
  await expect(page.getByText("Too many demos from this network — try again in a bit")).toBeVisible();
});

test("a network error offers a retry that works", async ({ page }) => {
  const state = await fakeApi(page, { signedIn: false, demoStart: "network" });
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "Couldn't set up the demo" })).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(banner(page)).toBeVisible();
  expect(state.demoStarts).toBe(2);
});

test("a signed-in real user opening /demo lands on Home without a demo", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/demo");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
  expect(state.demoStarts).toBe(0);
});
