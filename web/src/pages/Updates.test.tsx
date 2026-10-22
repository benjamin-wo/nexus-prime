import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Updates } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { UpdatesSection } from "./Updates";

const base: Updates = {
  frequency: "daily",
  daily_at: "21:00",
  description: "You get a summary of your transactions once a day at 9pm.",
  options: { instant: "as it happens", hourly: "every hour", thrice_daily: "3 times a day", daily: "once a day at 9pm", off: "off" },
  quiet_start: "23:00",
  quiet_end: "08:00",
  move_alert_percent: "5.0",
  market_summary: true,
  daily_cap: 6,
};

function setup() {
  let state = { ...base };
  const calls = mockApi({
    "GET /notifications": () => state,
    "PUT /notifications": (body) => {
      const patch = body as Record<string, unknown>;
      const percent = patch.move_alert_percent;
      if (typeof percent === "number" && (percent < 1 || percent > 20)) {
        return new Response(JSON.stringify({ detail: "a big move can be 1.0% to 20.0% in a day" }), { status: 422, headers: { "Content-Type": "application/json" } });
      }
      state = { ...state, ...patch, ...(typeof percent === "number" ? { move_alert_percent: percent.toFixed(1) } : {}) } as Updates;
      return state;
    },
  });
  renderWithProviders(<UpdatesSection />);
  const puts = () => calls.filter((c) => c.method === "PUT").map((c) => c.body);
  return { puts };
}

describe("investment notification settings", () => {
  it("shows quiet hours from 23:00 to 08:00, the move threshold and the summary, with captions", async () => {
    setup();
    expect(await screen.findByLabelText("From")).toHaveValue("23:00");
    expect(screen.getByLabelText("To")).toHaveValue("08:00");
    expect(screen.getByText("Nexus holds its messages in these hours. A broken stop on a stock you hold still comes through.")).toBeInTheDocument();
    expect(screen.getByLabelText("Big move alerts (%)")).toHaveValue(5);
    expect(screen.getByRole("switch", { name: "Morning investment summary" })).toBeChecked();
    expect(screen.getByText("At 8am after each US trading day.")).toBeInTheDocument();
  });

  it("saves only the quiet hour that changed", async () => {
    const { puts } = setup();
    const from = await screen.findByLabelText("From");
    fireEvent.change(from, { target: { value: "22:30" } });
    await waitFor(() => expect(screen.getByLabelText("From")).toHaveValue("22:30"));
    expect(puts().at(-1)).toEqual({ quiet_start: "22:30" });
    expect(puts().every((b) => !("quiet_end" in (b as object)))).toBe(true);
  });

  it("saves the move threshold once, when the field is left", async () => {
    const { puts } = setup();
    const field = await screen.findByLabelText("Big move alerts (%)");
    await userEvent.clear(field);
    await userEvent.type(field, "12");
    expect(puts()).toEqual([]);
    await userEvent.tab();
    await waitFor(() => expect(puts()).toEqual([{ move_alert_percent: 12 }]));
    expect(screen.getByLabelText("Big move alerts (%)")).toHaveValue(12);
  });

  it("sends nothing when the threshold is unchanged or left empty", async () => {
    const { puts } = setup();
    const field = await screen.findByLabelText("Big move alerts (%)");
    await userEvent.click(field);
    await userEvent.tab();
    await userEvent.clear(field);
    await userEvent.tab();
    expect(puts()).toEqual([]);
    expect(screen.getByLabelText("Big move alerts (%)")).toHaveValue(5);
  });

  it("shows the server's error for a threshold out of range and keeps the saved value", async () => {
    const { puts } = setup();
    const field = await screen.findByLabelText("Big move alerts (%)");
    await userEvent.clear(field);
    await userEvent.type(field, "40");
    await userEvent.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("a big move can be 1.0% to 20.0% in a day");
    expect(puts()).toEqual([{ move_alert_percent: 40 }]);
    expect(screen.getByLabelText("Big move alerts (%)")).toHaveValue(5);
  });

  it("turns the morning summary off with only that field", async () => {
    const { puts } = setup();
    await userEvent.click(await screen.findByRole("switch", { name: "Morning investment summary" }));
    await waitFor(() => expect(puts()).toEqual([{ market_summary: false }]));
    expect(screen.getByRole("switch", { name: "Morning investment summary" })).not.toBeChecked();
  });

  it("shows the daily limit and saves it once, when the field is left", async () => {
    const { puts } = setup();
    const field = await screen.findByLabelText("Messages a day");
    expect(field).toHaveValue(6);
    await userEvent.clear(field);
    await userEvent.type(field, "10");
    expect(puts()).toEqual([]);
    await userEvent.tab();
    await waitFor(() => expect(puts()).toEqual([{ daily_cap: 10 }]));
    expect(screen.getByLabelText("Messages a day")).toHaveValue(10);
  });

  it("does not send a daily limit outside 3 to 20 or a fraction", async () => {
    const { puts } = setup();
    const field = await screen.findByLabelText("Messages a day");
    await userEvent.clear(field);
    await userEvent.type(field, "2");
    await userEvent.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a whole number from 3 to 20");
    await userEvent.clear(field);
    await userEvent.type(field, "4.5");
    await userEvent.tab();
    expect(puts()).toEqual([]);
    expect(screen.getByLabelText("Messages a day")).toHaveValue(6);
  });
});
