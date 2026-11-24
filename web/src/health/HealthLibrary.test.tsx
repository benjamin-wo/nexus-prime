import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { exercises, push, squat } from "./fixtures";
import { HealthLibrary } from "./HealthLibrary";

afterEach(() => vi.restoreAllMocks());

function library(consented = true) {
  const routines = [{ ...push }];
  const calls = mockApi({
    "GET /health/consent": () => ({ consented_at: consented ? "2026-11-20T08:00:00Z" : null }),
    "GET /health/exercises": (_b, url) => {
      const text = url.searchParams.get("text")?.toLowerCase();
      const muscle = url.searchParams.get("muscle");
      return exercises.filter((e) => (!text || e.name.toLowerCase().includes(text)) && (!muscle || e.primary_muscles.includes(muscle as never)));
    },
    "GET /health/routines": () => routines,
    "PUT /health/routines/11111111-1111-1111-1111-111111111111": (body) => body,
  });
  return calls;
}

describe("Library", () => {
  it("asks for consent first", async () => {
    library(false);
    renderWithProviders(<HealthLibrary />);
    expect(await screen.findByRole("button", { name: "Turn on Health" })).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("lists exercises as rows and filters by search and by a muscle chip", async () => {
    const calls = library();
    renderWithProviders(<HealthLibrary />);
    const list = await screen.findByRole("list", { name: "Exercises" });
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    expect(within(list).getByText("chest · barbell · beginner")).toBeInTheDocument();

    await userEvent.type(screen.getByRole("searchbox", { name: "Search exercises" }), "squat");
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Exercises" })).getAllByRole("button")).toHaveLength(1));
    expect(calls.some((c) => c.path === "/health/exercises")).toBe(true);

    await userEvent.clear(screen.getByRole("searchbox", { name: "Search exercises" }));
    const muscles = screen.getByRole("group", { name: "Muscle" });
    await userEvent.click(within(muscles).getByRole("button", { name: "chest" }));
    expect(within(muscles).getByRole("button", { name: "chest" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Exercises" })).getAllByRole("button")).toHaveLength(1));
    expect(screen.getByRole("group", { name: "Equipment" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Level" })).toBeInTheDocument();
  });

  it("opens an exercise in a sheet with photos, steps and a body map, and adds it to a routine", async () => {
    library();
    renderWithProviders(<HealthLibrary />);
    await userEvent.click(await screen.findByRole("button", { name: /Barbell bench press/ }));
    const sheet = await screen.findByRole("dialog", { name: "Barbell bench press" });
    const photos = within(sheet).getAllByRole("img", { name: /step \d of 2/ });
    expect(photos).toHaveLength(2);
    expect(photos[0]).toHaveAttribute("loading", "lazy");
    expect(photos[0]).toHaveAttribute("alt", "Barbell bench press, step 1 of 2");
    expect(within(sheet).getByRole("img", { name: "Works chest; also triceps, shoulders" })).toBeInTheDocument();
    expect(within(sheet).getByRole("list", { name: "Steps" })).toHaveTextContent("Lower the bar to your chest.");

    await userEvent.click(within(sheet).getByRole("button", { name: "Add to routine" }));
    const adding = await screen.findByRole("dialog", { name: "Add to routine" });
    await userEvent.click(await within(adding).findByRole("button", { name: "Add Barbell bench press to Push day" }));
    expect(await screen.findByText("Added Barbell bench press to Push day.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not show an exercise without photos a broken picture", async () => {
    library();
    renderWithProviders(<HealthLibrary />);
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(squat.name) }));
    const sheet = await screen.findByRole("dialog", { name: squat.name });
    expect(within(sheet).queryAllByRole("img", { name: /step/ })).toHaveLength(0);
  });
});
