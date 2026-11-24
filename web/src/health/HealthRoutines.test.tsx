import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { move } from "./RoutineEditor";
import { bench, exercises, push, squat } from "./fixtures";
import { HealthRoutines } from "./HealthRoutines";

afterEach(() => vi.restoreAllMocks());

const twoSlots = {
  ...push,
  slots: [push.slots[0], { ...push.slots[0], exercise_id: squat.id, sets: 3, reps: 8 }],
};

describe("move", () => {
  it("swaps neighbours and stops at the ends", () => {
    expect(move(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(move(["a", "b", "c"], 0, -1)).toEqual(["a", "b", "c"]);
    expect(move(["a", "b", "c"], 2, 1)).toEqual(["a", "b", "c"]);
  });
});

describe("Routines", () => {
  it("lists routines and the plan", async () => {
    mockApi({
      "GET /health/consent": () => ({ consented_at: "2026-11-20T08:00:00Z" }),
      "GET /health/routines": () => [push],
      "GET /health/plan": () => ({ kind: "weekly", weekly: { "0": push.id, "3": push.id }, rotation: [] }),
    });
    renderWithProviders(<HealthRoutines />);
    expect(await screen.findByRole("button", { name: "Edit Push day" })).toBeInTheDocument();
    const plan = await screen.findByRole("list", { name: "Weekly plan" });
    expect(within(plan).getByText("Monday")).toBeInTheDocument();
    expect(within(plan).getByText("Thursday")).toBeInTheDocument();
  });

  it("edits a routine: reorders with the buttons, changes sets, and saves", async () => {
    const calls = mockApi({
      "GET /health/consent": () => ({ consented_at: "2026-11-20T08:00:00Z" }),
      "GET /health/routines": () => [twoSlots],
      "GET /health/plan": () => null,
      "GET /health/exercises/Barbell_Bench_Press": () => bench,
      "GET /health/exercises/Barbell_Squat": () => squat,
      "PUT /health/routines/11111111-1111-1111-1111-111111111111": (b) => b,
    });
    renderWithProviders(<HealthRoutines />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Push day" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit routine" });
    await within(sheet).findByText("Barbell squat");
    expect(within(sheet).getByRole("button", { name: "Move Barbell bench press up" })).toBeDisabled();
    await userEvent.click(within(sheet).getByRole("button", { name: "Move Barbell squat up" }));
    const items = within(within(sheet).getByRole("list", { name: "Exercises in this routine" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Barbell squat");
    const sets = within(sheet).getByLabelText("Sets, Barbell squat");
    await userEvent.clear(sets);
    await userEvent.type(sets, "4");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save routine" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")).toBeDefined());
    const body = calls.find((c) => c.method === "PUT")!.body as { name: string; slots: { exercise_id: string; sets: number }[] };
    expect(body.name).toBe("Push day");
    expect(body.slots.map((s) => [s.exercise_id, s.sets])).toEqual([[squat.id, 4], [bench.id, 2]]);
    expect(await screen.findByText("Saved Push day.")).toBeInTheDocument();
  });

  it("makes a routine by picking an exercise in the same sheet", async () => {
    const calls = mockApi({
      "GET /health/consent": () => ({ consented_at: "2026-11-20T08:00:00Z" }),
      "GET /health/routines": () => [],
      "GET /health/plan": () => null,
      "GET /health/exercises": () => exercises,
      "GET /health/exercises/Barbell_Bench_Press": () => bench,
      "POST /health/routines": (b) => ({ ...(b as object), id: "n", created_at: "", updated_at: "" }),
    });
    renderWithProviders(<HealthRoutines />);
    await userEvent.click(await screen.findByRole("button", { name: "New routine" }));
    const sheet = await screen.findByRole("dialog", { name: "New routine" });
    expect(within(sheet).getByRole("button", { name: "Save routine" })).toBeDisabled();
    await userEvent.type(within(sheet).getByLabelText("Name"), "Legs");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add exercise" }));
    const picker = await screen.findByRole("dialog", { name: "Add an exercise" });
    await userEvent.click(await within(picker).findByRole("button", { name: /Barbell bench press/ }));
    const back = await screen.findByRole("dialog", { name: "New routine" });
    await userEvent.click(within(back).getByRole("button", { name: "Save routine" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/health/routines")).toBeDefined());
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ name: "Legs", slots: [{ exercise_id: bench.id, sets: 3, reps: 10, rest_seconds: 90 }] });
  });

  it("saves a rotation plan in order", async () => {
    const calls = mockApi({
      "GET /health/consent": () => ({ consented_at: "2026-11-20T08:00:00Z" }),
      "GET /health/routines": () => [push, { ...push, id: "33333333-3333-3333-3333-333333333333", name: "Pull day" }],
      "GET /health/plan": () => null,
      "PUT /health/plan": (b) => b,
    });
    renderWithProviders(<HealthRoutines />);
    await userEvent.click(await screen.findByRole("button", { name: "Set a plan" }));
    const sheet = await screen.findByRole("dialog", { name: "Training plan" });
    await userEvent.click(within(sheet).getByRole("radio", { name: "Rotation" }));
    const add = within(sheet).getByLabelText("Add a routine to the rotation");
    await userEvent.selectOptions(add, "Push day");
    await userEvent.selectOptions(add, "Pull day");
    await userEvent.click(within(sheet).getByRole("button", { name: "Move Pull day up" }));
    await userEvent.click(within(sheet).getByRole("button", { name: "Save plan" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")).toBeDefined());
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
      kind: "rotation",
      weekly: {},
      rotation: ["33333333-3333-3333-3333-333333333333", push.id],
    });
  });
});
