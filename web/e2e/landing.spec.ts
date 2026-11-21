import { expect, test } from "@playwright/test";

// The landing page and its siblings are static files in the build (the server serves them at /,
// /privacy, /terms and /support); the preview server serves them from /landing/.
const pages = ["/landing/index.html", "/landing/privacy.html", "/landing/terms.html", "/landing/support.html"];

for (const path of pages) {
  test(`${path} has no horizontal scroll at 390px and works without JavaScript`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
    await context.close();
  });
}

test("the landing page links to sign in, the demo and the public pages", async ({ page }) => {
  await page.goto("/landing/index.html");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Say what you need.");
  await expect(page.getByRole("link", { name: "Create your account" }).first()).toHaveAttribute("href", "/login");
  await expect(page.getByRole("link", { name: "Try the demo" }).first()).toHaveAttribute("href", "/demo");
  await expect(page.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  for (const name of ["Privacy", "Terms", "Support"]) {
    await expect(page.getByRole("navigation", { name: "Footer" }).getByRole("link", { name })).toHaveAttribute("href", `/${name.toLowerCase()}`);
  }
});

test("the privacy page is marked as a draft", async ({ page }) => {
  await page.goto("/landing/privacy.html");
  await expect(page.getByText("Draft, last updated 22 November 2026")).toBeVisible();
});
