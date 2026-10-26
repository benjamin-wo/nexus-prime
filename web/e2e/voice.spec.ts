import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

// How Nexus talks, in Settings: pick a vibe, fine-tune, leave a note. Made-up data only.

test("pick Cheeky, the preview changes, set emoji to None, and the note is saved", async ({ page }) => {
  const api = await fakeApi(page);
  await page.goto("/settings");
  const card = page.getByRole("region", { name: "How Nexus talks" });
  await expect(card.getByRole("button", { name: /^Default/ })).toHaveAttribute("aria-pressed", "true");
  const first = card.getByTestId("voice-reply").first();
  await expect(first).toHaveText("Grab 12.00 ✅ Transport's at 108.30 this month.");

  await card.getByRole("button", { name: /^Cheeky/ }).click();
  await expect(card.getByRole("button", { name: /^Cheeky/ })).toHaveAttribute("aria-pressed", "true");
  await expect(first).toHaveText("Grab again? 😏 12 logged.");
  await expect.poll(() => api.voicePuts).toEqual([{ preset: "cheeky" }]);

  const emoji = card.getByRole("group", { name: "Emoji" });
  await emoji.getByRole("button", { name: "None" }).click();
  await expect(emoji.getByRole("button", { name: "None" })).toHaveAttribute("aria-pressed", "true");
  await expect(first).toHaveText("Grab again? 12 logged.");
  await expect.poll(() => api.voicePuts.at(-1)).toEqual({ emoji: "none" });

  const note = card.getByLabel("Anything else?");
  await note.fill("call me boss, no exclamation marks");
  await expect(card.getByTestId("voice-note-count")).toHaveText("34/200");
  await note.press("Enter");
  await expect.poll(() => api.voicePuts.at(-1)).toEqual({ note: "call me boss, no exclamation marks" });
  expect(api.voice).toMatchObject({ preset: "cheeky", emoji: "none", note: "call me boss, no exclamation marks" });

  // It stays after a reload, and nothing sideways on a phone or a desktop.
  await page.reload();
  await expect(card.getByRole("button", { name: /^Cheeky/ })).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByLabel("Anything else?")).toHaveValue("call me boss, no exclamation marks");
  await expect(card.getByRole("group", { name: "Emoji" }).getByRole("button", { name: "None" })).toHaveAttribute("aria-pressed", "true");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
