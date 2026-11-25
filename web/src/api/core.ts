export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let csrfToken = "";

export function setCsrf(token: string): void {
  csrfToken = token;
}

/** Shown when a request times out or never reaches the server. */
export const NETWORK_ERROR_MESSAGE = "Couldn't reach Nexus. Check your connection and try again.";

/** How long a read may take before it is given up on. Only reads: a write (a chat message, a receipt
 * photo, a statement) is never abandoned on a timer, because the server may still finish it, and the
 * person would then send it again and record it twice. */
const READ_TIMEOUT_MS = 30_000;

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal; idempotencyKey?: string } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  // Sent again with the same key, a write is recorded once (POST /transactions): see outbox.ts.
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
  return request<T>(
    path,
    method,
    headers,
    init.body === undefined ? undefined : JSON.stringify(init.body),
    init.signal,
    method === "GET" ? READ_TIMEOUT_MS : null,
  );
}

/** POST a multipart form (a file upload). The browser sets the Content-Type, with its boundary. */
export async function apiForm<T>(path: string, form: FormData, init: { signal?: AbortSignal } = {}): Promise<T> {
  return request<T>(path, "POST", { "X-CSRF-Token": csrfToken }, form, init.signal, null);
}

/** The CSRF header every write carries, for a request made with `fetch` directly (the chat stream). */
export function csrfHeader(): Record<string, string> {
  return { "X-CSRF-Token": csrfToken };
}

/** A message fit to show for the `detail` of an error response. FastAPI sends a string for its own
 * errors and a list of problems for a request it could not validate: the first one, named by its field. */
export function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return fallback;
  const first: unknown = detail[0];
  if (typeof first !== "object" || first === null) return fallback;
  const { msg, loc } = first as { msg?: unknown; loc?: unknown };
  if (typeof msg !== "string" || msg === "") return fallback;
  const field = Array.isArray(loc) && loc.length > 1 ? loc[loc.length - 1] : null;
  return typeof field === "string" && field !== "" ? `${field}: ${msg}` : msg;
}

async function request<T>(
  path: string,
  method: string,
  headers: Record<string, string>,
  body: BodyInit | undefined,
  signal: AbortSignal | undefined,
  timeoutMs: number | null,
): Promise<T> {
  // The caller's signal and the timeout are joined by hand: AbortSignal.any is missing from older WebViews.
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timer = timeoutMs === null ? undefined : setTimeout(abort, timeoutMs);
  try {
    const response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body,
      signal: controller.signal,
    });
    if (response.status === 204) return undefined as T;
    const data: unknown = await response.json().catch((e: unknown) => {
      // An abort while the body was still arriving is not an empty body.
      if (controller.signal.aborted) throw e;
      return null;
    });
    if (!response.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail;
      throw new ApiError(response.status, messageFromDetail(detail, response.statusText));
    }
    return data as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    // The caller gave up on purpose (TanStack Query does, on unmount): leave that an AbortError.
    if (signal?.aborted) throw e;
    // Anything else is the timeout or the network.
    throw new ApiError(0, NETWORK_ERROR_MESSAGE);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

/** The day as YYYYMMDD, for the export's file name when the server's header can't be read. */
function today8(): string {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}

/** The file name in a Content-Disposition header, or null. */
export function filenameFrom(disposition: string | null): string | null {
  const found = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition ?? "");
  if (!found) return null;
  try {
    return decodeURIComponent(found[1]).replace(/[\\/]/g, "_");
  } catch {
    return null;
  }
}

/** Everything Nexus keeps for you, as a zip: fetched as a Blob (same session as every call) and handed
 * to the browser as a download. Throws an ApiError whose message is fit to show. */
export async function exportAll(): Promise<void> {
  const response = await fetch("/api/me/export", { credentials: "same-origin" });
  if (response.status === 429) {
    throw new ApiError(429, "You've downloaded your data a few times just now. Try again in a few minutes.");
  }
  if (!response.ok) throw new ApiError(response.status, "Couldn't prepare your download. Please try again.");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filenameFrom(response.headers.get("Content-Disposition")) ?? `nexus-export-${today8()}.zip`;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Give the browser a moment to start reading the file before letting go of it.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Deletes the signed-in person's data for good and ends the session (204). 422 if the
 * confirmation isn't exactly DELETE. */
export async function deleteEverything(): Promise<void> {
  await api("/me/delete", { method: "POST", body: { confirm: "DELETE" } });
}
