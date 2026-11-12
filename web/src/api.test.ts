import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, apiForm, messageFromDetail, NETWORK_ERROR_MESSAGE } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** A fetch that never answers on its own and rejects like the browser's when its signal aborts. */
function hangingFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(
    (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        if (init?.signal?.aborted) reject(new DOMException("The operation was aborted.", "AbortError"));
        init?.signal?.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
      }),
  );
}

const validation = [
  { type: "less_than_equal", loc: ["query", "limit"], msg: "Input should be less than or equal to 500", input: "100000", ctx: { le: 500 } },
];

describe("messageFromDetail", () => {
  it("keeps a string as it is", () => {
    expect(messageFromDetail("Not yours", "Forbidden")).toBe("Not yours");
  });

  it("names the field of the first validation problem", () => {
    expect(messageFromDetail(validation, "Unprocessable Entity")).toBe("limit: Input should be less than or equal to 500");
  });

  it("leaves the field out when the location is not a field", () => {
    expect(messageFromDetail([{ loc: ["body"], msg: "Field required" }], "x")).toBe("Field required");
    expect(messageFromDetail([{ loc: ["body", "items", 0], msg: "Bad item" }], "x")).toBe("Bad item");
    expect(messageFromDetail([{ msg: "Bad" }], "x")).toBe("Bad");
  });

  it("falls back when there is nothing readable", () => {
    expect(messageFromDetail(undefined, "Not Found")).toBe("Not Found");
    expect(messageFromDetail([], "Not Found")).toBe("Not Found");
    expect(messageFromDetail([{ loc: ["query", "limit"] }], "Not Found")).toBe("Not Found");
    expect(messageFromDetail({ nope: 1 }, "Not Found")).toBe("Not Found");
  });
});

describe("api errors", () => {
  it("shows a validation error as a sentence", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: validation }, 422));
    const error = await api("/transactions?limit=100000").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, message: "limit: Input should be less than or equal to 500" });
  });

  it("still uses a string detail, and the status text without one", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(json({ detail: "Not yours" }, 403));
    await expect(api("/a")).rejects.toMatchObject({ status: 403, message: "Not yours" });
    fetchMock.mockResolvedValueOnce(new Response("oops", { status: 500, statusText: "Internal Server Error" }));
    await expect(api("/b")).rejects.toMatchObject({ status: 500, message: "Internal Server Error" });
  });

  it("returns undefined for a 204 and the body otherwise", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(api("/a", { method: "DELETE" })).resolves.toBeUndefined();
    fetchMock.mockResolvedValueOnce(json({ ok: 1 }, 200));
    await expect(api("/b")).resolves.toEqual({ ok: 1 });
  });
});

describe("api timeouts and aborts", () => {
  it("turns a network failure into a readable ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api("/me")).rejects.toMatchObject({ status: 0, message: NETWORK_ERROR_MESSAGE });
  });

  it("gives up after 30 seconds", async () => {
    vi.useFakeTimers();
    hangingFetch();
    let settled = false;
    const result = api("/me").catch((e: unknown) => e);
    void result.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(29_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(await result).toMatchObject({ status: 0, message: NETWORK_ERROR_MESSAGE });
  });

  it("never gives up on a write or an upload on a timer: the server may still finish it", async () => {
    vi.useFakeTimers();
    hangingFetch();
    let settled = false;
    const sent = api("/chat", { method: "POST", body: { message: "lunch 8.40" } }).catch((e: unknown) => e);
    const uploaded = apiForm("/import", new FormData()).catch((e: unknown) => e);
    void sent.then(() => (settled = true));
    void uploaded.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(settled).toBe(false);
  });

  it("gives up when the body never finishes arriving", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const response = new Response("{}", { status: 200 });
      vi.spyOn(response, "json").mockImplementation(
        () =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      );
      return response;
    });
    const result = api("/me").catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(30_001);
    expect(await result).toMatchObject({ status: 0, message: NETWORK_ERROR_MESSAGE });
  });

  it("passes the caller's signal on and rejects with the AbortError when it aborts", async () => {
    const fetchMock = hangingFetch();
    const controller = new AbortController();
    const result = api("/me", { signal: controller.signal }).catch((e: unknown) => e);
    controller.abort();
    const error = await result;
    expect(error).not.toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ name: "AbortError" });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it("rejects with an AbortError when the signal is already aborted", async () => {
    hangingFetch();
    const controller = new AbortController();
    controller.abort();
    await expect(api("/me", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  });

  it("does not leave a timer or a listener behind", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ ok: 1 }, 200));
    const controller = new AbortController();
    const remove = vi.spyOn(controller.signal, "removeEventListener");
    await api("/me", { signal: controller.signal });
    expect(vi.getTimerCount()).toBe(0);
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
  });
});

describe("idempotency keys", () => {
  it("sends the key given as an Idempotency-Key header, and no header without one", async () => {
    const fetched = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({}, 200));
    await api("/transactions", { method: "POST", body: { amount: "1" }, idempotencyKey: "0b1d6c3e-5a7f-4e21-9d84-3c2f1a6b7e90" });
    await api("/transactions", { method: "POST", body: { amount: "1" } });
    const sent = fetched.mock.calls.map(([, init]) => init?.headers as Record<string, string>);
    expect(sent[0]["Idempotency-Key"]).toBe("0b1d6c3e-5a7f-4e21-9d84-3c2f1a6b7e90");
    expect(sent[1]).not.toHaveProperty("Idempotency-Key");
  });
});
