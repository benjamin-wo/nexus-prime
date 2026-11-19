import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Typing a time into Telegram updates used to save on every keystroke, and each answer overwrote the
// field while the next digits were still being typed. Now it is sent once, as typed. Made-up data only.
test.skip(({ isMobile }) => isMobile, "typing into the time field's segments is a keyboard thing");
test.use({ locale: "en-US" });

/** Every PUT /notifications takes a quarter of a second to answer. */
async function slowNotifications(page: import("@playwright/test").Page) {
  await page.route("**/api/notifications", async (route) => {
    if (route.request().method() === "PUT") await new Promise((resolve) => setTimeout(resolve, 250));
    await route.fallback();
  });
}

test("typing 07:45 into Daily summary, with slow saves, ends saved as 07:45", async ({ page }) => {
  const state = await fakeApi(page);
  await slowNotifications(page);
  await page.goto("/settings/updates");
  const card = page.getByRole("region", { name: "Telegram updates" });
  const field = card.getByLabel("Daily summary at");
  await expect(field).toHaveValue("21:00");

  await field.focus();
  // Hours, minutes, then AM (the field is 12-hour here): 9:00 PM becomes 07:45.
  await page.keyboard.type("0745A", { delay: 40 });
  await expect(field).toHaveValue("07:45");
  expect(state.notificationPuts).toEqual([]);
  await page.keyboard.press("Enter");

  await expect(card.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await expect(field).toHaveValue("07:45");
  expect(state.notificationPuts).toEqual([{ frequency: "daily", daily_at: "07:45" }]);
  await expect(card.getByText("You get a summary of your transactions once a day at 7:45am.")).toBeVisible();

  await page.reload();
  await expect(card.getByLabel("Daily summary at")).toHaveValue("07:45");
});

test("typing a quiet-hours time and moving on saves what was typed, not a half-typed time", async ({ page }) => {
  const state = await fakeApi(page);
  await slowNotifications(page);
  await page.goto("/settings/updates");
  const card = page.getByRole("region", { name: "Telegram updates" });
  const from = card.getByLabel("From", { exact: true });
  await expect(from).toHaveValue("23:00");

  await from.focus();
  await page.keyboard.type("1030P", { delay: 40 });
  await card.getByLabel("To", { exact: true }).focus();
  await expect(card.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await expect(from).toHaveValue("22:30");
  expect(state.notificationPuts).toEqual([{ quiet_start: "22:30" }]);
});

test("a refused time is shown next to the field and the typed time stays", async ({ page }) => {
  await fakeApi(page);
  await page.route("**/api/notifications", async (route) => {
    if (route.request().method() === "PUT") return route.fulfill({ status: 422, json: { detail: "that time isn't allowed" } });
    await route.fallback();
  });
  await page.goto("/settings/updates");
  const card = page.getByRole("region", { name: "Telegram updates" });
  const to = card.getByLabel("To", { exact: true });
  await to.fill("07:15");
  await to.press("Enter");
  await expect(card.getByRole("alert")).toHaveText("that time isn't allowed");
  await expect(to).toHaveValue("07:15");
});
