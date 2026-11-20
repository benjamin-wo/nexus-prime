import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LoadError } from "./LoadError";

describe("LoadError", () => {
  it("says what failed, as an alert, with a Retry", () => {
    render(<LoadError message="Couldn't load your trips." query={{ refetch: vi.fn() }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load your trips.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("fetches again when Retry is pressed", async () => {
    const refetch = vi.fn();
    render(<LoadError message="Couldn't load your trips." query={{ refetch }} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("holds Retry while a fetch is under way", () => {
    render(<LoadError message="Couldn't load your trips." query={{ refetch: vi.fn(), isFetching: true }} />);
    expect(screen.getByRole("button", { name: "Retry" })).toBeDisabled();
  });

  it("can be a card of its own", () => {
    render(<LoadError message="Couldn't load your trips." query={{ refetch: vi.fn() }} variant="page" />);
    expect(screen.getByRole("alert")).toHaveClass("load-error-page");
  });
});
