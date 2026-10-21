import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Menu } from "./Menu";

function menu(onSelect = vi.fn()) {
  render(
    <MemoryRouter>
      <button type="button">Elsewhere</button>
      <Menu
        label="More"
        items={[
          { key: "a", label: "Go to a page", to: "/page" },
          { key: "b", label: "Do something", onSelect },
          { key: "c", label: "Get a file", href: "/file.csv", download: true },
        ]}
      />
    </MemoryRouter>,
  );
  return onSelect;
}

describe("a menu button", () => {
  it("opens on the button, focuses the first item, and moves with the arrow keys", async () => {
    menu();
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(items[1]).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    expect(items[2]).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(items[0]).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(items[2]).toHaveFocus();
  });

  it("runs an action item and closes", async () => {
    const onSelect = menu();
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Do something" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Tab and on a press outside, and a second press on the button closes it too", async () => {
    menu();
    const button = screen.getByRole("button", { name: "More" });
    await userEvent.click(button);
    await userEvent.keyboard("{Tab}");
    expect(screen.queryByRole("menu")).toBeNull();
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("button", { name: "Elsewhere" }));
    expect(screen.queryByRole("menu")).toBeNull();
    await userEvent.click(button);
    await userEvent.click(button);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});
