import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const toast = (page: import("@playwright/test").Page) => page.locator(".toast");

test("a duplicate is deleted from Where it went, with Undo, without leaving the overview", async ({ page }) => {
  const state = await fakeApi(page);
  // The same lunch logged twice.
  state.txs.push({ ...state.txs[0], id: "t4", has_receipt: false });
  await page.goto("/accounting");

  const went = page.getByRole("region", { name: "Where it went" });
  await went.getByRole("button", { name: /Dining Out: SGD.12\.40/ }).click();
  const list = went.getByRole("list", { name: "Dining Out transactions" });
  const rows = list.getByRole("button", { name: /^Edit Maxwell Food Centre, SGD.12\.40, / });
  await expect(rows).toHaveCount(2);

  // Each row is a full finger tall.
  const box = (await rows.first().boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);

  await rows.first().click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByLabel("Amount")).toHaveValue("12.4");

  await sheet.getByRole("button", { name: "Delete" }).click();
  await expect(sheet).toBeHidden();
  await expect(toast(page)).toContainText("Deleted Maxwell Food Centre.");
  await expect(page).toHaveURL(/\/accounting$/);
  await expect(rows).toHaveCount(1);

  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(toast(page)).toContainText("Restored.");
  await expect(rows).toHaveCount(2);
});

test("opening an expense on a phone keeps the keyboard down and the bottom bar there", async ({ page, isMobile }) => {
  test.skip(!isMobile, "the bottom bar and the keyboard are a phone thing");
  await fakeApi(page);
  await page.goto("/accounting");
  const went = page.getByRole("region", { name: "Where it went" });
  await went.getByRole("button", { name: /Dining Out: SGD.12\.40/ }).click();
  const bar = page.getByRole("navigation", { name: "Main (mobile)" });
  await expect(bar).toBeVisible();

  await went.getByRole("list", { name: "Dining Out transactions" }).getByRole("button", { name: /^Edit / }).first().click();
  const sheet = page.getByRole("dialog", { name: "Edit transaction" });
  await expect(sheet).toBeVisible();
  // No field took the focus, so no keyboard: the bar wasn't hidden for one.
  await expect(sheet.getByLabel("Amount")).not.toBeFocused();
  expect(await page.evaluate(() => document.documentElement.classList.contains("keyboard"))).toBe(false);

  await sheet.getByRole("button", { name: "Cancel" }).click();
  await expect(sheet).toBeHidden();
  await expect(bar).toBeVisible();
  await bar.getByRole("link", { name: /Home/ }).click();
  await expect(page).toHaveURL(/\/app$/);
});
