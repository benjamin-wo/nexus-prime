import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatDrawer } from "./components/ChatDrawer";
import { mockApi, renderWithProviders } from "./testing";

const HZ = "https://www.hardwarezone.com.sg/tech-news/console-prices";
const XE = "https://www.xe.com/currencyconverter/";
const EX = "https://news.example.com/kaya-evals/latest";

const ANSWER = {
  text: "About 500 SGD, per HardwareZone, 11 May.",
  buttons: [
    [
      { label: "HardwareZone ↗", data: `src:${HZ}` },
      { label: "XE ↗", data: `src:${XE}` },
    ],
    [{ label: "Example Daily ↗", data: `src:${EX}` }],
  ],
};

afterEach(() => vi.restoreAllMocks());

async function ask(reply: unknown) {
  const calls = mockApi({ "POST /chat": () => [reply] });
  renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Message"), "how much is a ps6?");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText(/About 500 SGD/);
  return { user, calls };
}

describe("ChatDrawer source links", () => {
  it("draws a web answer's sources as small link chips, not buttons", async () => {
    await ask(ANSWER);
    const group = screen.getByRole("group", { name: "Sources" });
    const chips = within(group).getAllByRole("link");
    expect(chips.map((c) => c.textContent)).toEqual(["HardwareZone↗", "XE↗", "Example Daily↗"]);
    expect(chips.map((c) => c.getAttribute("href"))).toEqual([HZ, XE, EX]);
    expect(chips.every((c) => c.classList.contains("src-chip") && !c.classList.contains("btn"))).toBe(true);
    expect(chips.every((c) => c.getAttribute("rel") === "noopener noreferrer")).toBe(true);
    // Their names read as the site, without the arrow; no empty row of buttons sits above them.
    expect(screen.getByRole("link", { name: "HardwareZone" })).toBeInTheDocument();
    expect(document.querySelector(".choices")).toBeNull();
    expect(screen.queryByRole("button", { name: /HardwareZone/ })).not.toBeInTheDocument();
  });

  it("opens a source outside the app and never sends it as a button press", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { user, calls } = await ask(ANSWER);
    await user.click(screen.getByRole("link", { name: "XE" }));
    expect(open).toHaveBeenCalledWith(XE, "_blank", "noopener,noreferrer");
    expect(calls.some((c) => c.path === "/chat/press")).toBe(false);
  });

  it("keeps url: links as the big button, and other buttons beside the chips", async () => {
    await ask({
      text: "About 500 SGD, per HardwareZone, 11 May.",
      buttons: [
        [{ label: "Open the trip", data: "url:https://app.example.com/trips/1" }, { label: "Undo", data: "act:undo" }],
        [{ label: "XE ↗", data: `src:${XE}` }],
      ],
    });
    const open = screen.getByRole("link", { name: "Open the trip" });
    expect(open).toHaveClass("btn", "btn-primary");
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Sources" })).getAllByRole("link")).toHaveLength(1);
  });
});
