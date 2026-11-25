import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import type { SetEntry, Workout } from "./api";
import { consents } from "./bodyFixtures";
import { bench, exercises, push, setEntry, workout } from "./fixtures";
import { HealthToday } from "./HealthToday";
import { RestTimer } from "./RestTimer";
import { render } from "@testing-library/react";

const consented = { consented_at: "2026-11-20T08:00:00Z" };

/** A small in-memory Gym backend: one workout at a time, its sets, last time's sets and the summary. */
function gym({ routine = null as typeof push | null, open = null as Workout | null, last = [] as SetEntry[], prior = [] as unknown[] } = {}) {
  const state = { open, sets: [] as SetEntry[], finished: false };
  const calls = mockApi({
    "GET /health/consent": () => consented,
    "GET /health/today": () => ({ routine, in_progress: state.finished ? null : state.open }),
    "POST /health/workouts": (body) => {
      state.open = { ...workout, routine_id: (body as { routine_id: string | null }).routine_id };
      return state.open;
    },
    "GET /health/workouts/22222222-2222-2222-2222-222222222222": () => ({ ...state.open, sets: state.sets }),
    [`GET /health/routines/${push.id}`]: () => push,
    "GET /health/exercises/Barbell_Bench_Press/last": () => last,
    "GET /health/exercises/Barbell_Bench_Press/progress": () => prior,
    "GET /health/exercises": (_b, url) => { const ids = url.searchParams.get("ids"); return ids ? exercises.filter((e) => ids.split(",").includes(e.id)) : exercises; },
    "POST /health/workouts/22222222-2222-2222-2222-222222222222/sets": (body) => {
      const b = body as Partial<SetEntry>;
      const set = setEntry({ id: `s${state.sets.length + 1}`, position: state.sets.length + 1, done_at: `2026-11-24T08:1${state.sets.length}:00Z`, ...b });
      state.sets.push(set);
      // The server names the records a set sets: here, a working set heavier than the 80 kg of earlier workouts.
      const beats = set.kind === "working" && Number(set.weight) > 80;
      return { ...set, records: beats ? [{ kind: "best_e1rm", exercise_id: set.exercise_id, value_text: "99.17 kg" }] : [] };
    },
    "POST /health/workouts/22222222-2222-2222-2222-222222222222/undo": () => state.sets.pop(),
    "POST /health/workouts/22222222-2222-2222-2222-222222222222/finish": () => {
      state.finished = true;
      return {
        workout_id: workout.id,
        duration_seconds: 3120,
        sets: state.sets.length,
        volume_kg: String(state.sets.reduce((n, s) => n + Number(s.weight) * (s.reps ?? 0), 0)),
        prs: { [bench.id]: ["heaviest_weight", "best_e1rm"] },
      };
    },
  });
  return { calls, state };
}

afterEach(() => vi.restoreAllMocks());

describe("Health consent", () => {
  it("shows one plain consent screen and turns Health on with one tap", async () => {
    let given: string | null = null;
    const calls = mockApi({
      "GET /health/consent": () => ({ consented_at: given }),
      "GET /health/consents": () => ({ ...consents, health_consented_at: given }),
      "POST /health/consent/all": () => {
        given = "2026-11-24T08:00:00Z";
        return { ...consents, health_consented_at: given };
      },
      "GET /health/today": () => ({ routine: null, in_progress: null }),
    });
    renderWithProviders(<HealthToday />);
    expect(await screen.findByText(/not medical advice/i)).toBeInTheDocument();
    expect(await screen.findByText(/through OpenRouter in United States/)).toBeInTheDocument();
    expect(screen.getByText(consents.wellness_statement)).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(calls.some((c) => c.path === "/health/today")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Turn on Health" }));
    expect(await screen.findByRole("button", { name: "Start an empty workout" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST" && c.path === "/health/consent/all")).toHaveLength(1);
    expect(calls.some((c) => c.method === "POST" && c.path === "/health/consent")).toBe(false);
  });
});

describe("Today", () => {
  it("offers today's routine from the plan with a Start button, and an empty workout", async () => {
    gym({ routine: push });
    renderWithProviders(<HealthToday />);
    expect(await screen.findByRole("button", { name: "Start Push day" })).toBeInTheDocument();
    expect(await screen.findByText("Barbell bench press")).toBeInTheDocument();
    expect(screen.getByText("2 × 5 · rest 90 s")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start an empty workout" })).toBeInTheDocument();
  });

  it("says so on a rest day", async () => {
    gym();
    renderWithProviders(<HealthToday />);
    expect(await screen.findByText(/Nothing planned for today/)).toBeInTheDocument();
  });

  it("resumes the workout that is open", async () => {
    gym({ open: workout });
    renderWithProviders(<HealthToday />);
    expect(await screen.findByRole("button", { name: "Finish workout" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start an empty workout" })).toBeNull();
  });
});

describe("a planned workout", () => {
  it("lists the planned exercises and prefills sets, reps and rest, with last time's weight", async () => {
    const planned = { exercise_id: bench.id, sets: 3, reps: 8, seconds: null, rest_seconds: 120 };
    const { calls } = gym({ open: { ...workout, planned_slots: [planned] }, last: [setEntry({ weight: "80.00", reps: 5 })] });
    renderWithProviders(<HealthToday />);
    expect(await screen.findByText("Barbell bench press")).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith("/health/routines/"))).toBe(false);
    await screen.findByLabelText("Weight (kg), set 3 of Barbell bench press");
    expect(screen.getByLabelText("Reps, set 1 of Barbell bench press")).toHaveValue("8");
    expect(screen.getByLabelText("Weight (kg), set 1 of Barbell bench press")).toHaveValue("80");
    await userEvent.click(screen.getByRole("button", { name: "Log set 1 of Barbell bench press" }));
    expect(await screen.findByText("Rest 2 minutes.")).toBeInTheDocument();
  });
});

describe("a workout", () => {
  it("logs a set from last time's numbers, starts the rest, undoes it, and finishes with a summary", async () => {
    const { calls } = gym({ last: [setEntry({ weight: "80.00", reps: 5 }), setEntry({ id: "p2", position: 2, weight: "80.00", reps: 5 })] });
    renderWithProviders(<HealthToday />);
    await userEvent.click(await screen.findByRole("button", { name: "Start an empty workout" }));
    expect(await screen.findByText(/An empty workout/)).toBeInTheDocument();

    // Add an exercise from the picker.
    await userEvent.click(screen.getByRole("button", { name: "Add exercise" }));
    const dialog = await screen.findByRole("dialog", { name: "Add an exercise" });
    await userEvent.click(await within(dialog).findByRole("button", { name: /Barbell bench press/ }));

    // The sets are prefilled from the last time.
    const weight = await screen.findByLabelText("Weight (kg), set 1 of Barbell bench press");
    expect(weight).toHaveValue("80");
    expect(screen.getByLabelText("Reps, set 1 of Barbell bench press")).toHaveValue("5");
    expect(screen.getAllByText("Last time 80 kg × 5")).toHaveLength(2);

    // Edit the weight and log it.
    await userEvent.clear(weight);
    await userEvent.type(weight, "82.5");
    await userEvent.click(screen.getByRole("button", { name: "Log set 1 of Barbell bench press" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/sets"))?.body).toMatchObject({ exercise_id: bench.id, weight: "82.5", reps: 5, unit: "kg" }));
    expect(await screen.findByText("Logged 82.5 kg × 5.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Skip rest" })).toBeInTheDocument();
    expect(screen.getByText("Rest 1 minute 30 seconds.")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();

    // Skip the rest.
    await userEvent.click(screen.getByRole("button", { name: "Skip rest" }));
    expect(screen.queryByRole("button", { name: "Skip rest" })).toBeNull();

    // Undo from the toast.
    const toast = screen.getByText("Logged 82.5 kg × 5.").closest(".toast") as HTMLElement;
    await userEvent.click(within(toast).getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Removed 82.5 kg × 5.")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/undo"))).toBe(true);
    await waitFor(() => expect(screen.queryByText("Done")).toBeNull());

    // Log again, then finish.
    await userEvent.click(screen.getByRole("button", { name: "Log set 1 of Barbell bench press" }));
    await screen.findByText("Done");
    await userEvent.click(screen.getByRole("button", { name: "Finish workout" }));
    const summary = await screen.findByRole("dialog", { name: "Workout finished" });
    expect(within(summary).getByText("52 min")).toBeInTheDocument();
    expect(within(summary).getByText("Duration")).toBeInTheDocument();
    expect(within(summary).getByText("New best: Barbell bench press")).toBeInTheDocument();
    expect(within(summary).getByText("Heaviest weight, Best estimated max")).toBeInTheDocument();
  });

  it("says New best in plain text for a set that beats the earlier workouts", async () => {
    gym({
      open: workout,
      last: [setEntry({ id: "old", weight: "80.00", reps: 5 })],
      prior: [{ workout_id: "older", at: "2026-11-10T08:00:00Z", weight: "80.00", unit: "kg", reps: 5, e1rm_kg: "93.33" }],
    });
    // The open workout already has a squat set, so the bench shows beside it; add bench by logging via the picker.
    renderWithProviders(<HealthToday />);
    await userEvent.click(await screen.findByRole("button", { name: "Add exercise" }));
    const dialog = await screen.findByRole("dialog", { name: "Add an exercise" });
    await userEvent.click(await within(dialog).findByRole("button", { name: /Barbell bench press/ }));
    const weight = await screen.findByLabelText("Weight (kg), set 1 of Barbell bench press");
    await userEvent.clear(weight);
    await userEvent.type(weight, "85");
    await userEvent.click(screen.getByRole("button", { name: "Log set 1 of Barbell bench press" }));
    expect(await screen.findByText(/New best: 85 kg × 5/)).toBeInTheDocument();
  });

  it("refuses a set with no reps without asking the server", async () => {
    const { calls } = gym({ open: workout });
    renderWithProviders(<HealthToday />);
    await userEvent.click(await screen.findByRole("button", { name: "Add exercise" }));
    const dialog = await screen.findByRole("dialog", { name: "Add an exercise" });
    await userEvent.click(await within(dialog).findByRole("button", { name: /Barbell bench press/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Log set 1 of Barbell bench press" }));
    expect(await screen.findByText("Enter the reps.")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/sets") && c.method === "POST")).toBe(false);
  });
});

describe("the rest timer", () => {
  it("counts down, says when it starts and ends in a polite live region, and gives a haptic", () => {
    vi.useFakeTimers();
    const post = vi.fn();
    (window as unknown as { ReactNativeWebView: unknown }).ReactNativeWebView = { postMessage: post };
    const skip = vi.fn();
    render(<RestTimer seconds={60} run={1} onSkip={skip} />);
    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent("Rest 1 minute.");
    expect(screen.getByText("1:00")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(30_000));
    expect(live).toHaveTextContent("30 seconds left.");
    expect(screen.getByText("0:30")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(20_000));
    expect(live).toHaveTextContent("10 seconds left.");
    expect(post).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(10_000));
    expect(live).toHaveTextContent("Rest is over.");
    expect(post).toHaveBeenCalledWith(JSON.stringify({ v: 1, type: "haptic", kind: "light" }));
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(skip).toHaveBeenCalled();
    delete (window as unknown as { ReactNativeWebView?: unknown }).ReactNativeWebView;
    vi.useRealTimers();
  });

  it("can be skipped", () => {
    vi.useFakeTimers();
    const skip = vi.fn();
    render(<RestTimer seconds={90} run={1} onSkip={skip} />);
    fireEvent.click(screen.getByRole("button", { name: "Skip rest" }));
    expect(skip).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
