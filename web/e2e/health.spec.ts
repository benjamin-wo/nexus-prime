import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Health happy path against an in-memory Gym backend: consent, an empty workout, one set, finish.
// Set SHOT_DIR to also save pictures of the Today page, a library exercise and the workout screen.
const SHOTS = process.env.SHOT_DIR;

const bench = {
  id: "Barbell_Bench_Press",
  name: "Barbell bench press",
  category: "strength",
  level: "beginner",
  equipment: "barbell",
  force: "push",
  mechanic: "compound",
  primary_muscles: ["chest"],
  secondary_muscles: ["triceps", "shoulders"],
  instructions: ["Lie on the bench with your feet flat.", "Lower the bar to your chest.", "Press it back up."],
  images: [],
};
const WORKOUT = "22222222-2222-2222-2222-222222222222";

async function healthApi(page: Page) {
  const state = { consented: false, open: false, sets: [] as Record<string, unknown>[], finished: false };
  const json = (route: import("@playwright/test").Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/health/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^\/api\/health/, "");
    const method = req.method();
    if (path === "/consent" && method === "GET") return json(route, { consented_at: state.consented ? "2026-11-20T08:00:00Z" : null });
    if (path === "/consent" && method === "POST") {
      state.consented = true;
      return json(route, { consented_at: "2026-11-20T08:00:00Z" }, 201);
    }
    if (path === "/today") {
      const workout = { id: WORKOUT, routine_id: null, started_at: new Date().toISOString(), finished_at: null, note: null };
      return json(route, { routine: null, in_progress: state.open && !state.finished ? workout : null });
    }
    if (path === "/workouts" && method === "POST") {
      state.open = true;
      return json(route, { id: WORKOUT, routine_id: null, started_at: new Date().toISOString(), finished_at: null, note: null }, 201);
    }
    if (path === `/workouts/${WORKOUT}`) {
      return json(route, { id: WORKOUT, routine_id: null, started_at: new Date().toISOString(), finished_at: null, note: null, sets: state.sets });
    }
    if (path === `/workouts/${WORKOUT}/sets` && method === "POST") {
      const b = JSON.parse(req.postData() ?? "{}");
      const set = { id: "s1", workout_id: WORKOUT, position: 1, kind: "working", seconds: null, rpe: null, unit: "kg", done_at: new Date().toISOString(), ...b };
      state.sets.push(set);
      return json(route, set, 201);
    }
    if (path === `/workouts/${WORKOUT}/finish`) {
      state.finished = true;
      return json(route, { workout_id: WORKOUT, duration_seconds: 600, sets: state.sets.length, volume_kg: "400.00", prs: {} });
    }
    if (path === "/exercises") return json(route, [bench]);
    if (path === `/exercises/${bench.id}`) return json(route, bench);
    if (path === `/exercises/${bench.id}/last`) return json(route, []);
    if (path === `/exercises/${bench.id}/progress`) return json(route, []);
    if (path === "/routines") return json(route, []);
    if (path === "/plan") return json(route, null);
    return json(route, { detail: "not mocked" }, 404);
  });
  return state;
}

test("turn on Health, start an empty workout, log a set and finish", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  await healthApi(page);
  await page.goto("/health");

  await expect(page.getByText(/not medical advice/i)).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/health-consent.png`, fullPage: true });
  await page.getByRole("button", { name: "Turn on Health" }).click();

  await expect(page.getByRole("button", { name: "Start an empty workout" })).toBeVisible();
  await page.waitForTimeout(800);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/health-today.png`, fullPage: true });
  await page.getByRole("button", { name: "Start an empty workout" }).click();

  await page.getByRole("button", { name: "Add exercise" }).first().click();
  await page.getByRole("button", { name: /Barbell bench press/ }).click();
  await page.getByLabel("Weight (kg), set 1 of Barbell bench press").fill("80");
  await page.getByLabel("Reps, set 1 of Barbell bench press").fill("5");
  await page.getByRole("button", { name: "Log set 1 of Barbell bench press" }).click();
  await expect(page.getByText("Logged 80 kg × 5.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Skip rest" })).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/health-workout.png`, fullPage: true });

  await page.getByRole("button", { name: "Finish workout" }).click();
  const summary = page.getByRole("dialog", { name: "Workout finished" });
  await expect(summary).toBeVisible();
  await expect(summary.getByText("Volume")).toBeVisible();
  await summary.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("button", { name: "Start an empty workout" })).toBeVisible();
});

test("a library exercise opens in a sheet with its steps and body map", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  state.consented = true;
  await page.goto("/health/library");
  await page.getByRole("button", { name: /Barbell bench press/ }).click();
  const sheet = page.getByRole("dialog", { name: "Barbell bench press" });
  await expect(sheet.getByRole("img", { name: "Works chest; also triceps, shoulders" })).toBeVisible();
  await expect(sheet.getByText("Lower the bar to your chest.")).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/health-library-detail.png` });
});
