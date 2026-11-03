import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../testing";
import { MonthPicker } from "./MonthPicker";

describe("MonthPicker", () => {
  it("names the month and steps one month at a time", async () => {
    const onChange = vi.fn();
    renderWithProviders(<MonthPicker month="2026-10" current="2026-11" onChange={onChange} />);
    expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/October.*2026/);
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-09");
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-11");
  });

  it("cannot go past this month", () => {
    renderWithProviders(<MonthPicker month="2026-11" current="2026-11" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous month" })).toBeEnabled();
  });

  it("cannot go back more than 24 months", () => {
    renderWithProviders(<MonthPicker month="2024-11" current="2026-11" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Previous month" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next month" })).toBeEnabled();
  });
});
