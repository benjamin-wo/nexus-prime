import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// On a phone there is no rail, so Settings ends with an Account group: Invite someone (the owner's) and
// Sign out. Made-up data only.
test.skip(({ isMobile }) => !isMobile, "the desktop rail has these; this is the phone's way to them");
test.use({ viewport: { width: 390, height: 844 }, permissions: ["clipboard-read", "clipboard-write"] });

const account = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Account" });

test("Sign out is at the end of Settings on a phone and leads to the sign-in page", async ({ page }) => {
  await fakeApi(page);
  await page.goto("/settings");
  await account(page).scrollIntoViewIfNeeded();
  const out = account(page).getByRole("button", { name: "Sign out" });
  await expect(out).toBeVisible();
  const box = (await out.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);
  await out.click();
  await expect(page).toHaveURL(/\/login$/);
});

test("the owner makes an invite on a phone, sees the link and how long it works, and copies it", async ({ page }) => {
  const state = await fakeApi(page);
  await page.goto("/settings");
  await account(page).getByRole("button", { name: /Invite someone/ }).click();
  const link = account(page).getByLabel("Invite link");
  await expect(link).toHaveValue(/\/invite\/fakeAppInvite1$/);
  await expect(account(page).getByText(/Single-use link, valid for 24 hours/)).toBeVisible();
  expect(state.appInvites).toBe(1);

  await expect(account(page).getByRole("status")).toBeEmpty();
  await account(page).getByRole("button", { name: "Copy" }).click();
  await expect(account(page).getByRole("status")).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/\/invite\/fakeAppInvite1$/);
  // No sideways scrolling with the card open.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("a member sees Sign out but no Invite", async ({ page }) => {
  await fakeApi(page, { member: true });
  await page.goto("/settings");
  await expect(account(page).getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(account(page).getByRole("button", { name: /Invite someone/ })).toHaveCount(0);
});

test("in the demo, Sign out says it ends the demo, and there is no Invite", async ({ page }) => {
  await fakeApi(page, { demo: true });
  await page.goto("/settings");
  await expect(account(page).getByRole("button", { name: /^Sign out/ })).toContainText("Ends the demo");
  await expect(account(page).getByRole("button", { name: /Invite someone/ })).toHaveCount(0);
  await account(page).getByRole("button", { name: /^Sign out/ }).click();
  await expect(page).toHaveURL(/\/login$/);
});
