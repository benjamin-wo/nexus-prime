import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary, pageFallback } from "./ErrorBoundary";

let broken = true;

function Page({ name }: { name: string }) {
  if (broken) throw new Error(`${name} exploded`);
  return <p>{name} is fine</p>;
}

beforeEach(() => {
  broken = true;
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

describe("ErrorBoundary", () => {
  it("shows the old fallback with Reload by default", () => {
    render(
      <ErrorBoundary>
        <Page name="Home" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong on this page.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });

  it("shows the page fallback and tries again on request", () => {
    const onReset = vi.fn();
    render(
      <ErrorBoundary fallback={pageFallback} onReset={onReset}>
        <Page name="Home" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This page hit a problem.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    broken = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Home is fine")).toBeInTheDocument();
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("recovers when its resetKey changes, and not before", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/a" fallback={pageFallback}>
        <Page name="A" />
      </ErrorBoundary>,
    );
    broken = false;
    rerender(
      <ErrorBoundary resetKey="/a" fallback={pageFallback}>
        <Page name="A" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(
      <ErrorBoundary resetKey="/b" fallback={pageFallback}>
        <Page name="B" />
      </ErrorBoundary>,
    );
    expect(screen.getByText("B is fine")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
