import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

test("Download all my data hands over the zip and says so", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Download or delete" });
  await expect(card.getByText("Your ledger, budgets, trips, investments, memories and settings, as a zip.")).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), card.getByRole("button", { name: "Download" }).click()]);
  expect(download.suggestedFilename()).toMatch(/^nexus-export-\d{8}\.zip$/);
  await expect(card.getByRole("status")).toHaveText("Downloaded.");
  expect(state.exports).toBe(1);
});

test("a download asked for too often says to wait", async ({ page }) => {
  const state = await fakeApi(page, { exportLimited: true });
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Download or delete" });
  await card.getByRole("button", { name: "Download" }).click();
  await expect(card.getByRole("alert")).toContainText("Try again in a few minutes");
  await expect(card.getByRole("status")).toHaveCount(0);
  expect(state.exports).toBe(1);
});

test("Delete everything waits for DELETE, can be cancelled, and signs out when confirmed", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Download or delete" });
  await expect(card.getByText(/This can't be undone, and you'd need a new invite to come back\./)).toBeVisible();
  const open = card.getByRole("button", { name: "Delete everything…" });

  // Cancel closes the panel and nothing is sent.
  await open.click();
  const field = card.getByLabel("Type DELETE to confirm");
  await expect(field).toBeFocused();
  await field.fill("DELETE");
  await card.getByRole("button", { name: "Cancel" }).click();
  await expect(field).toHaveCount(0);
  await expect(open).toBeVisible();
  expect(state.deletes).toEqual([]);

  // The button stays off until the field is exactly DELETE.
  await open.click();
  await expect(field).toHaveValue("");
  const confirm = card.getByRole("button", { name: "Delete everything", exact: true });
  await expect(confirm).toBeDisabled();
  for (const wrong of ["delete", "DELET", "DELETE ", " DELETE", "Delete"]) {
    await field.fill(wrong);
    await expect(confirm).toBeDisabled();
  }
  await field.fill("DELETE");
  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Sign in with your Telegram account.")).toBeVisible();
  expect(state.deletes).toEqual([{ body: { confirm: "DELETE" }, status: 204 }]);
  // The session is gone, so the app is signed out if it asks again.
  expect(await page.evaluate(async () => (await fetch("/api/me")).status)).toBe(401);
});

test("a refused deletion shows why and keeps the person signed in", async ({ page }) => {
  const state = await fakeApi(page, { deleteRefused: true });
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "Download or delete" });
  await card.getByRole("button", { name: "Delete everything…" }).click();
  await card.getByLabel("Type DELETE to confirm").fill("DELETE");
  await card.getByRole("button", { name: "Delete everything", exact: true }).click();
  await expect(card.getByRole("alert")).toContainText("Type DELETE");
  await expect(page).toHaveURL(/\/settings$/);
  await expect(card.getByLabel("Type DELETE to confirm")).toHaveValue("DELETE");
  expect(state.deletes).toHaveLength(1);
  expect(state.deletes[0].status).toBe(422);
});
