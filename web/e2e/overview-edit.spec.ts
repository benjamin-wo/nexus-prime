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
