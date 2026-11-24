import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { bench, setEntry, workout } from "./fixtures";
import { HealthHistory } from "./HealthHistory";

afterEach(() => vi.restoreAllMocks());

const done = {
  ...workout,
  finished_at: "2026-11-24T08:52:00Z",
  sets: [setEntry(), setEntry({ id: "s2", position: 2, done_at: "2026-11-24T08:15:00Z", weight: "85.00" })],
};

function history() {
  return mockApi({
    "GET /health/consent": () => ({ consented_at: "2026-11-20T08:00:00Z" }),
    "GET /health/workouts": () => [done, { ...done, id: "open", finished_at: null }],
    "GET /health/exercises/Barbell_Bench_Press": () => bench,
    "GET /health/exercises/Barbell_Bench_Press/progress": () => [
      { workout_id: "a", at: "2026-11-10T08:00:00Z", weight: "80.00", unit: "kg", reps: 5, e1rm_kg: "93.33" },
      { workout_id: "b", at: "2026-11-17T08:00:00Z", weight: "82.50", unit: "kg", reps: 5, e1rm_kg: "96.25" },
      { workout_id: "c", at: "2026-11-24T08:00:00Z", weight: "85.00", unit: "kg", reps: 5, e1rm_kg: "99.17" },
    ],
    "GET /health/volume": () => ({
      week_start: "2026-11-23",
      muscles: [
        { muscle: "chest", volume_kg: "850.00", sets: 2, secondary_sets: 0 },
        { muscle: "triceps", volume_kg: "0.00", sets: 0, secondary_sets: 2 },
      ],
    }),
  });
}

describe("History", () => {
  it("lists finished workouts only and opens one", async () => {
    history();
    renderWithProviders(<HealthHistory />);
    const list = await screen.findByRole("list", { name: "Past workouts" });
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    expect(within(list).getByText(/2 sets · 52 min · Barbell bench press/)).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("button"));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("80 kg × 5, 85 kg × 5")).toBeInTheDocument();
  });

  it("shows the best set, the e1RM trend and weekly volume with its body map", async () => {
    history();
    renderWithProviders(<HealthHistory />);
    expect(await screen.findByRole("img", { name: /Barbell bench press: estimated one-rep max over 3 workouts/ })).toBeInTheDocument();
    expect(screen.getByText("Best set")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Barbell bench press workouts" })).toBeInTheDocument();
    const volume = await screen.findByRole("list", { name: "Sets per muscle" });
    expect(within(volume).getByText("2 sets")).toBeInTheDocument();
    expect(within(volume).getByText(/2 more as a helper/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Works chest; also triceps" })).toBeInTheDocument();
  });

  it("goes back a week", async () => {
    const calls = history();
    renderWithProviders(<HealthHistory />);
    await userEvent.click(await screen.findByRole("button", { name: "Earlier week" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/health/volume").length).toBeGreaterThan(1));
  });
});
