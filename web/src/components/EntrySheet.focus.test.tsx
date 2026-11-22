import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { EntrySheet } from "./EntrySheet";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
  preferences: { track_cards: false },
};

describe("EntrySheet focus", () => {
  it("puts the cursor in Amount, and returns focus to the button that opened it on close", () => {
    mockApi({ "GET /categories": () => [], "GET /wallets": () => [], "GET /transactions/suggestions": () => [] });
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { unmount } = renderWithProviders(<EntrySheet me={me} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Log money out" })).toBeTruthy();
    expect(screen.getByLabelText("Amount")).toHaveFocus();
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });
});
