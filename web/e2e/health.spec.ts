import { expect, test, type Page } from "@playwright/test";

import { fakeApi } from "./fake-api";

// Health happy paths against an in-memory backend: consent, an empty workout, one set, finish; a food; a weight; the
// trend words with numbers hidden. Set SHOT_DIR to also save pictures of the pages.
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
const WELLNESS = "This product is not intended to diagnose, treat, mitigate, cure or prevent any disease or medical condition.";
const CHECK_IN =
  "I've noticed some patterns in your logs lately that can mean things are hard. No judgement at all. If you'd like to talk to someone, the contacts below are there for you, and I'll keep calorie targets switched off for now.";
const SIGNPOSTS = [
  { name: "SGH Eating Disorders Programme", contact: "eatingdisorders@sgh.com.sg", note: "Specialist support for ages 13 and up." },
  { name: "Samaritans of Singapore", contact: "1767, or WhatsApp 9151 1767", note: "Someone to talk to, any time." },
];
const nut = (kcal: string) => ({ kcal, protein_g: "30", carbs_g: "60", fat_g: "12", fibre_g: null });
const rice = { id: "rice-1", source: "hpb", name: "Chicken rice", aliases: [], kcal_per_100g: "170", portions: [{ label: "1 plate", grams: "350" }] };

async function healthApi(page: Page) {
  const state = {
    consented: false,
    open: false,
    sets: [] as Record<string, unknown>[],
    finished: false,
    hidden: false,
    meals: [] as Record<string, unknown>[],
    weighIns: [] as string[],
    checkIn: false,
    planned: false,
  };
  const ROUTINE = "11111111-1111-1111-1111-111111111111";
  const routine = { id: ROUTINE, name: "Push day", slots: [{ exercise_id: bench.id, sets: 3, reps: 8, seconds: null, rest_seconds: 120, note: null }], created_at: "", updated_at: "" };
  const workoutBody = () => ({ id: WORKOUT, routine_id: state.planned ? ROUTINE : null, started_at: new Date().toISOString(), finished_at: null, note: null });
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
    if (path === "/consent/all") {
      state.consented = true;
      return json(route, { health_consented_at: "2026-11-20T08:00:00Z", scopes: [{ scope: "ai_processing", active: true, granted_at: "2026-11-20T08:00:00Z", withdrawn_at: null }], ai_provider: { name: "OpenRouter", country: "United States" }, wellness_statement: WELLNESS }, 201);
    }
    if (path === "/today") {
      return json(route, { routine: state.planned ? routine : null, in_progress: state.open && !state.finished ? workoutBody() : null });
    }
    if (path === `/routines/${ROUTINE}`) return json(route, routine);
    if (path === "/workouts" && method === "POST") {
      state.open = true;
      return json(route, workoutBody(), 201);
    }
    if (path === `/workouts/${WORKOUT}`) {
      return json(route, { ...workoutBody(), sets: state.sets });
    }
    if (path === `/workouts/${WORKOUT}/sets` && method === "POST") {
      const b = JSON.parse(req.postData() ?? "{}");
      const set = { id: "s1", workout_id: WORKOUT, position: 1, kind: "working", seconds: null, rpe: null, unit: "kg", done_at: new Date().toISOString(), ...b };
      state.sets.push(set);
      return json(route, { ...set, records: [] }, 201);
    }
    if (path === `/workouts/${WORKOUT}/finish`) {
      state.finished = true;
      return json(route, { workout_id: WORKOUT, duration_seconds: 600, sets: state.sets.length, volume_kg: "400.00", prs: {} });
    }
    if (path === "/foods") return json(route, [rice]);
    if (path === "/meals" && method === "POST") {
      const b = JSON.parse(req.postData() ?? "{}");
      const meal = {
        id: `m${state.meals.length + 1}`,
        meal: b.meal,
        eaten_at: new Date().toISOString(),
        source: "manual",
        note: null,
        items: b.items.map((i: Record<string, unknown>) => ({ id: null, name: rice.name, note: null, nutrients: state.hidden ? null : nut("675"), ...i })),
        totals: state.hidden ? null : { point: nut("675"), low: nut("600"), high: nut("750") },
      };
      state.meals.push(meal);
      return json(route, meal, 201);
    }
    if (path === "/day") {
      const t = state.meals.length && !state.hidden ? { point: nut("675"), low: nut("600"), high: nut("750") } : null;
      const safety = { suspended: state.checkIn, signposts: state.checkIn ? SIGNPOSTS : [], new_signals: state.checkIn ? ["restriction"] : [], check_in: state.checkIn ? CHECK_IN : null };
      return json(route, { date: new Date().toLocaleDateString("en-CA"), hidden: state.hidden, meals: state.meals, totals: t, targets_kcal: null, remaining: null, safety });
    }
    if (path === "/samples" && method === "POST") {
      state.weighIns.push(JSON.parse(req.postData() ?? "{}").value);
      return json(route, { id: "s", kind: "weight", value: "82", unit: "kg", value_kg: "82", start_at: new Date().toISOString() }, 201);
    }
    if (path === "/weight") {
      if (state.hidden) return json(route, { hidden: true, trend_words: "slowly down", points: null, trend_kg: null, rate_kg_per_week: null, rate_pct_per_week: null, rate_text: null, last_weigh_in: null });
      const points = [
        { date: "2026-11-10", scale_kg: "83.2", trend_kg: "83.0" },
        { date: "2026-11-17", scale_kg: "82.6", trend_kg: "82.7" },
        { date: "2026-11-24", scale_kg: "82.1", trend_kg: "82.4" },
      ];
      return json(route, { hidden: false, trend_words: "slowly down", points, trend_kg: "82.4", rate_kg_per_week: "-0.3", rate_pct_per_week: "-0.4", rate_text: "about 0.3 kg a week down over the last 2 weeks", last_weigh_in: { at: "2026-11-23T07:00:00Z", kg: "82.1" } });
    }
    if (path === "/consents") return json(route, { health_consented_at: state.consented ? "2026-11-20T08:00:00Z" : null, scopes: [], ai_provider: { name: "OpenRouter", country: "United States" }, wellness_statement: WELLNESS });
    if (path === "/profile") return json(route, null);
    if (path === "/exercises") return json(route, [bench]);
    if (path === "/preferences") return json(route, { unit: "kg" });
    if (path === `/exercises/${bench.id}`) return json(route, bench);
    if (path === `/exercises/${bench.id}/last`) return json(route, []);
    if (path === `/exercises/${bench.id}/progress`) return json(route, []);
    if (path === "/routines") return json(route, []);
    if (path === "/plan") return json(route, null);
    return json(route, { detail: "not mocked" }, 404);
  });
  return state;
}

test("turn on Health in one tap, start an empty workout, log a set and finish", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  await page.goto("/health");

  await expect(page.getByText(/not medical advice/i)).toBeVisible();
  await expect(page.getByText(/through OpenRouter in United States/)).toBeVisible();
  await page.waitForTimeout(500);
  if (SHOTS) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${SHOTS}/simple-consent.png`, fullPage: true });
  }
  await expect(page.getByText(WELLNESS)).toBeVisible();
  await page.getByRole("button", { name: "Turn on Health" }).click();
  expect(state.consented).toBe(true);

  await expect(page.getByRole("heading", { name: "Health", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Gym", exact: true }).click();
  await expect(page.getByRole("button", { name: "Start an empty workout" })).toBeVisible();
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
  await page.goto("/health/gym/library");
  await page.getByRole("button", { name: /Barbell bench press/ }).click();
  const sheet = page.getByRole("dialog", { name: "Barbell bench press" });
  await expect(sheet.getByRole("img", { name: "Works chest; also triceps, shoulders" })).toBeVisible();
  await expect(sheet.getByText("Lower the bar to your chest.")).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/health-library-detail.png` });
});

test("Today shows a meal, the weight line, and logs a weight", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  state.consented = true;
  const item = (name: string, source_detail: string, food_id: string | null) => ({ id: null, food_id, source_detail, name, grams: "350", label: "1 plate", kind: "portion", cooking: null, note: null, nutrients: nut("675") });
  state.meals.push(
    { id: "m1", meal: "lunch", eaten_at: new Date().toISOString(), source: "chat", note: null, items: [item("Chicken rice", "db", "rice-1")], totals: { point: nut("675"), low: nut("600"), high: nut("750") } },
    { id: "m2", meal: "dinner", eaten_at: new Date().toISOString(), source: "chat", note: null, items: [item("Laksa", "ai_estimate", null)], totals: { point: nut("675"), low: nut("600"), high: nut("750") } },
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/health");
  await expect(page.getByRole("button", { name: "Open chat" })).toContainText("Snap your food or tell Nexus what you ate.");
  const meals = page.getByRole("list", { name: "Meals today" });
  await expect(meals).toContainText("Lunch · Chicken rice");
  await expect(meals).toContainText("about 600–750 kcal");
  await expect(meals.getByRole("button", { name: "Open Dinner" })).toContainText("rough guide");
  await expect(page.getByText("82.4 kg, slowly down")).toBeVisible();
  await page.waitForTimeout(800);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/simple-today.png`, fullPage: true });

  await page.getByRole("button", { name: "Log weight" }).click();
  const weigh = page.getByRole("dialog", { name: "Log weight" });
  await weigh.getByLabel("Weight (kg)").fill("82.1");
  await weigh.getByRole("button", { name: "Save weight" }).click();
  await expect(weigh.getByRole("status")).toHaveText("Saved 82.1 kg");
  expect(state.weighIns).toEqual(["82.1"]);
  await weigh.getByRole("button", { name: "Done" }).click();
  await page.getByRole("button", { name: "See trend" }).click();
  await expect(page.getByRole("dialog", { name: "Weight trend" }).getByRole("img", { name: /Weight trend/ })).toBeVisible();
});

test("start a planned workout from Today", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  state.consented = true;
  state.planned = true;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/health");
  await page.getByRole("link", { name: /Push day/ }).click();
  await expect(page).toHaveURL(/\/health\/gym$/);
  await page.getByRole("button", { name: "Start Push day" }).click();
  await expect(page.getByLabel("Reps, set 3 of Barbell bench press")).toHaveValue("8");
  await page.waitForTimeout(800);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/simple-gym-planned.png`, fullPage: true });
  await page.getByLabel("Weight (kg), set 1 of Barbell bench press").fill("60");
  await page.getByRole("button", { name: "Log set 1 of Barbell bench press" }).click();
  await expect(page.getByText("Logged 60 kg × 8.")).toBeVisible();
});

test("the old Food and Weight addresses open Today", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  state.consented = true;
  for (const old of ["/health/food", "/health/weight"]) {
    await page.goto(old);
    await expect(page).toHaveURL(/\/health$/);
    await expect(page.getByRole("heading", { name: "Health", level: 1 })).toBeVisible();
  }
});

test("with numbers hidden, Today shows only words and nothing echoes a number", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  state.consented = true;
  state.hidden = true;
  await page.goto("/health");
  await expect(page.getByText("Slowly down")).toBeVisible();
  await page.getByRole("button", { name: "Log weight" }).click();
  const weigh = page.getByRole("dialog", { name: "Log weight" });
  await weigh.getByLabel("Weight (kg)").fill("82.1");
  await weigh.getByRole("button", { name: "Save weight" }).click();
  await expect(weigh.getByRole("status")).toHaveText("Saved");
});

test("the soft check-in shows once", async ({ page }) => {
  await fakeApi(page, { showHealth: true });
  const state = await healthApi(page);
  state.consented = true;
  state.checkIn = true;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/health");
  const sheet = page.getByRole("dialog", { name: "Checking in" });
  await expect(sheet).toContainText(CHECK_IN);
  await expect(sheet.getByRole("link", { name: "1767, or WhatsApp 9151 1767" })).toHaveAttribute("href", "tel:1767");
  await expect(sheet.getByRole("link", { name: "eatingdisorders@sgh.com.sg" })).toHaveAttribute("href", "mailto:eatingdisorders@sgh.com.sg");
  await page.waitForTimeout(500);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/h7-checkin.png` });
  await sheet.getByRole("button", { name: "Close" }).last().click();
  await expect(sheet).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Health", level: 1 })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Checking in" })).toHaveCount(0);
});
