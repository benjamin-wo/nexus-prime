import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export type Call = { method: string; path: string; body: unknown };

/** Route fetch calls to handlers keyed by "METHOD /path" (query string ignored). */
export function mockApi(handlers: Record<string, (body: unknown) => unknown>): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    const path = url.pathname.replace(/^\/api/, "");
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    const handler = handlers[`${method} ${path}`];
    if (!handler) return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    return new Response(JSON.stringify(handler(body) ?? null), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  return calls;
}

export function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
