import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Nexus's current time zone follows the phone; home is kept. The browser is in Madrid, home is Singapore. Made-up data only.
test.use({ timezoneId: "Europe/Madrid" });

const card = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Time zone" });

test("opening the app reports the phone's zone, and Settings shows it with home beside it", async ({ page }) => {
  const api = await fakeApi(page, { phoneFollows: true });
  await page.goto("/settings");
  await expect(card(page).getByTestId("time-zone-now")).toContainText("Madrid · UTC+");
  await expect(card(page)).toContainText("from your phone");
  await expect(card(page)).toContainText("Home: Singapore");
  await expect(card(page).getByRole("button", { name: "Use home time" })).toBeVisible();
  expect(api.zonePosts).toEqual([{ path: "/me/timezone", body: { timezone: "Europe/Madrid", source: "phone" } }]);
});

test("a zone picked in Settings is saved as the user's own", async ({ page }) => {
  const api = await fakeApi(page, { phoneFollows: true });
  await page.goto("/settings");
  await expect(card(page)).toContainText("from your phone");
  await card(page).getByRole("button", { name: "Change" }).click();
  await card(page).getByLabel("Find a time zone").fill("tokyo");
  await card(page).getByRole("listbox", { name: "Time zone" }).selectOption("Asia/Tokyo");
  await card(page).getByRole("button", { name: "Save" }).click();
  await expect(card(page).getByTestId("time-zone-now")).toContainText("Tokyo · UTC+9");
  await expect(card(page)).toContainText("you set it");
  await expect(card(page).getByRole("status")).toContainText("Saved");
  expect(api.zonePosts.at(-1)).toEqual({ path: "/me/timezone", body: { timezone: "Asia/Tokyo", source: "manual" } });
});

test("Use home time goes back to Singapore and the button goes away", async ({ page }) => {
  const api = await fakeApi(page, { phoneFollows: true });
  await page.goto("/settings");
  await expect(card(page)).toContainText("Madrid");
  await card(page).getByRole("button", { name: "Use home time" }).click();
  await expect(card(page).getByTestId("time-zone-now")).toContainText("Singapore · UTC+8");
  await expect(card(page)).toContainText("home");
  await expect(card(page)).not.toContainText("Home:");
  await expect(card(page).getByRole("button", { name: "Use home time" })).toHaveCount(0);
  expect(api.zonePosts.at(-1)?.path).toBe("/me/timezone/home");
  // Once per load: going home is not undone by the phone until the page is opened again.
  expect(api.zonePosts.filter((p) => p.body?.source === "phone")).toHaveLength(1);
});

test("a zone chosen in the last day is not overridden by the phone on reload", async ({ page }) => {
  const api = await fakeApi(page, { phoneFollows: true });
  await page.goto("/settings");
  await expect(card(page)).toContainText("from your phone");
  await card(page).getByRole("button", { name: "Change" }).click();
  await card(page).getByLabel("Find a time zone").fill("tokyo");
  await card(page).getByRole("listbox", { name: "Time zone" }).selectOption("Asia/Tokyo");
  await card(page).getByRole("button", { name: "Save" }).click();
  await expect(card(page)).toContainText("you set it");
  const posts = api.zonePosts.length;
  await page.reload();
  await expect(card(page).getByTestId("time-zone-now")).toContainText("Tokyo");
  await expect(card(page)).toContainText("you set it");
  // Nothing was sent on the second load.
  expect(api.zonePosts).toHaveLength(posts);
});
