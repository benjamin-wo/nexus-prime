import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { lazyNamed, lazyPage } from "./lazyPage";

const reload = vi.fn();

beforeEach(() => {
  reload.mockClear();
  window.sessionStorage.clear();
  vi.stubGlobal("location", { ...window.location, reload });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Hello() {
  return <p>Hello page</p>;
}

describe("lazyPage", () => {
  it("shows the fallback, then the page", async () => {
    const Page = lazyNamed(async () => ({ Hello }), "Hello");
    render(
      <Suspense fallback={<p>Loading…</p>}>
        <Page />
      </Suspense>,
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Hello page")).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads once when the chunk is gone, and keeps the fallback up meanwhile", async () => {
    const load = vi.fn().mockRejectedValue(new Error("Failed to fetch dynamically imported module"));
    const Page = lazyPage(load);
    render(
      <Suspense fallback={<p>Loading…</p>}>
        <Page />
      </Suspense>,
    );
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("nexus-chunk-reloaded")).toBe("1");
  });

  it("does not reload twice in a row: the error reaches the boundary", async () => {
    window.sessionStorage.setItem("nexus-chunk-reloaded", "1");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Page = lazyPage(() => Promise.reject(new Error("still gone")));
    const { ErrorBoundary } = await import("./components/ErrorBoundary");
    render(
      <ErrorBoundary>
        <Suspense fallback={<p>Loading…</p>}>
          <Page />
        </Suspense>
      </ErrorBoundary>,
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("forgets the guard after a page loads, so a later deploy can recover again", async () => {
    window.sessionStorage.setItem("nexus-chunk-reloaded", "1");
    const Page = lazyPage(async () => ({ default: Hello }));
    render(
      <Suspense fallback={<p>Loading…</p>}>
        <Page />
      </Suspense>,
    );
    expect(await screen.findByText("Hello page")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("nexus-chunk-reloaded")).toBeNull();
  });
});
