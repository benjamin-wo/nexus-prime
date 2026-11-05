import type { Page } from "@playwright/test";

/** The Ledger's one Filter button opens a sheet; this opens it and returns it. */
export async function openFilters(page: Page) {
  await page.getByRole("button", { name: /^Filter/ }).click();
  const sheet = page.getByRole("dialog", { name: "Filter transactions" });
  await sheet.waitFor();
  return sheet;
}

/** Shows only one kind of entry ("Money out", "Money in", "Transfers", "Pending" or "All"), then closes the sheet. */
export async function showOnly(page: Page, view: "All" | "Money out" | "Money in" | "Transfers" | "Pending") {
  const sheet = await openFilters(page);
  await sheet.getByRole("button", { name: view, exact: true }).click();
  await page.keyboard.press("Escape");
  await sheet.waitFor({ state: "hidden" });
}
