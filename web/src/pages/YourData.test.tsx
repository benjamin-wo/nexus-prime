import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { downloadNote, inPhoneWebview } from "../telegram";
import { canConfirmDelete, YourDataSection } from "./YourData";

afterEach(() => {
  delete window.Telegram;
  vi.restoreAllMocks();
});

/** jsdom has no object URLs and can't follow a download link; stand in for both, and note what was downloaded. */
function stubDownloads(): string[] {
  const names: string[] = [];
  URL.createObjectURL = () => "blob:nexus";
  URL.revokeObjectURL = () => undefined;
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    names.push(this.download);
  });
  return names;
}

describe("the DELETE confirmation", () => {
  it("accepts exactly DELETE and nothing else", () => {
    expect(canConfirmDelete("DELETE")).toBe(true);
    for (const typed of ["", "delete", "Delete", "DELET", "DELETE ", " DELETE", "DELETE!", "DELETEDELETE"]) {
      expect(canConfirmDelete(typed)).toBe(false);
    }
  });

  it("keeps the confirm button off until it is typed, and sends the confirmation once", async () => {
    const calls = mockApi({ "POST /me/delete": () => new Response(null, { status: 204 }) });
    renderWithProviders(<YourDataSection />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete everything…" }));
    const confirm = screen.getByRole("button", { name: "Delete everything" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Type DELETE to confirm"), "delete");
    expect(confirm).toBeDisabled();
    await user.clear(screen.getByLabelText("Type DELETE to confirm"));
    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => expect(calls).toEqual([{ method: "POST", path: "/me/delete", body: { confirm: "DELETE" } }]));
  });

  it("closes on Cancel without sending anything, and starts empty next time", async () => {
    const calls = mockApi({});
    renderWithProviders(<YourDataSection />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete everything…" }));
    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Type DELETE to confirm")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Delete everything…" }));
    expect(screen.getByLabelText("Type DELETE to confirm")).toHaveValue("");
    expect(calls).toEqual([]);
  });

  it("says why when the server refuses", async () => {
    mockApi({ "POST /me/delete": () => new Response(JSON.stringify({ detail: [{ msg: "bad" }] }), { status: 422 }) });
    renderWithProviders(<YourDataSection />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete everything…" }));
    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(screen.getByRole("button", { name: "Delete everything" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Type DELETE in capitals");
  });
});

describe("the Telegram webview note", () => {
  it("is only for Telegram's phone apps", () => {
    expect(inPhoneWebview()).toBe(false);
    for (const [platform, expected] of [["ios", true], ["android", true], ["tdesktop", false], ["web", false], ["macos", false], [undefined, false]] as const) {
      window.Telegram = { WebApp: { platform, ready: () => undefined, expand: () => undefined } };
      expect(inPhoneWebview()).toBe(expected);
    }
  });

  it("says to use the browser when the download may not start", () => {
    expect(downloadNote(true)).toBe("If the download doesn't start, open Nexus in your browser to download it.");
    expect(downloadNote(false)).toBeNull();
  });

  it("shows no note after a download in a browser", async () => {
    const names = stubDownloads();
    mockApi({
      "GET /me/export": () =>
        new Response("PK", { status: 200, headers: { "Content-Type": "application/zip", "Content-Disposition": 'attachment; filename="nexus-export-20261024.zip"' } }),
    });
    renderWithProviders(<YourDataSection />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/^Downloaded\.$/);
    expect(names).toEqual(["nexus-export-20261024.zip"]);
  });

  it("shows the note after a download in the phone app", async () => {
    stubDownloads();
    window.Telegram = { WebApp: { platform: "android", ready: () => undefined, expand: () => undefined } };
    mockApi({ "GET /me/export": () => new Response("PK", { status: 200, headers: { "Content-Type": "application/zip" } }) });
    renderWithProviders(<YourDataSection />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Downloaded. If the download doesn't start, open Nexus in your browser to download it.");
  });

  it("answers a 429 with a friendly line", async () => {
    mockApi({ "GET /me/export": () => new Response("{}", { status: 429 }) });
    renderWithProviders(<YourDataSection />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in a few minutes");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
