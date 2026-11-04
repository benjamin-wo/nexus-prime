import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Settings is a short list; each row opens its own page. Made-up data only.

test("opens a section from the list, and the way back leads to the list", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  // The list shows current values, and no form.
  await expect(page.getByRole("link", { name: /^Telegram updates/ }).getByText("Daily at 9pm")).toBeVisible();
  await expect(page.getByRole("link", { name: /^Time zone/ }).getByText("Singapore · UTC+8")).toBeVisible();
  await expect(page.getByRole("link", { name: /^Wallets/ }).getByText(/^\d+ wallets?$/)).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveCount(0);

  await page.getByRole("link", { name: /^Telegram updates/ }).click();
  await expect(page).toHaveURL(/\/settings\/updates$/);
  await expect(page.getByRole("heading", { name: "Telegram updates", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Telegram updates" }).getByLabel("Send me my transactions")).toBeVisible();

  await page.getByRole("link", { name: "Back to Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("link", { name: /^Wallets/ })).toBeVisible();
});

test("the sections have addresses of their own, and an unknown one goes to the list", async ({ page }) => {
  await fakeApi(page);
  for (const [address, name] of [
    ["/settings/wallets", "Wallets"],
    ["/settings/categories", "Categories"],
    ["/settings/data", "Download or delete"],
  ]) {
    await page.goto(address);
    await expect(page.getByRole("region", { name })).toBeVisible();
  }
  await page.goto("/settings/nonsense");
  await expect(page).toHaveURL(/\/settings$/);
});

test("Track which card paid: flip it on and off, and it is still there after a reload", async ({ page }) => {
  const state = await fakeApi(page, { trackCards: false });
  await page.goto("/settings");
  const paid = page.getByRole("switch", { name: "Track which card paid" });
  await expect(page.getByText("Off keeps logging simple. On adds a Paid with field to expenses.")).toBeVisible();
  await expect(paid).not.toBeChecked();

  await paid.click();
  await expect(paid).toBeChecked();
  await expect.poll(() => state.preferencePuts).toEqual([{ track_cards: true }]);
  await page.reload();
  await expect(page.getByRole("switch", { name: "Track which card paid" })).toBeChecked();

  await page.getByRole("switch", { name: "Track which card paid" }).click();
  await expect(page.getByRole("switch", { name: "Track which card paid" })).not.toBeChecked();
  await expect.poll(() => state.preferencePuts).toEqual([{ track_cards: true }, { track_cards: false }]);
});

test("Track which card paid starts on by default", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  await expect(page.getByRole("switch", { name: "Track which card paid" })).toBeChecked();
});

test("Track which card paid goes back and says why when the save fails", async ({ page }) => {
  await fakeApi(page, { trackCards: false, preferencesFail: true });
  await page.goto("/settings");
  await page.getByRole("switch", { name: "Track which card paid" }).click();
  await expect(page.getByRole("alert")).toContainText("Couldn't save that preference");
  await expect(page.getByRole("switch", { name: "Track which card paid" })).not.toBeChecked();
});
