import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Button, ButtonLink, buttonClass, Chip, ChipGroup } from ".";

describe("Button", () => {
  it.each([
    [undefined, "btn"],
    ["primary", "btn btn-primary"],
    ["secondary", "btn btn-soft"],
    ["text", "btn btn-ghost"],
    ["danger", "btn btn-danger"],
  ] as const)("variant %s gives %s", (variant, cls) => {
    render(<Button variant={variant}>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("class", cls);
  });

  it("adds the size, the full width and the caller's class, in that order", () => {
    expect(buttonClass({ variant: "primary", size: "sm", full: true, className: "chat-action" })).toBe(
      "btn btn-primary btn-small btn-full chat-action",
    );
    expect(buttonClass({ size: "md" })).toBe("btn");
  });

  it("is type=button unless told otherwise, and passes native props and the ref through", async () => {
    const onClick = vi.fn();
    const ref = createRef<HTMLButtonElement>();
    const { rerender } = render(
      <Button ref={ref} aria-label="Close chat" onClick={onClick}>
        ×
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Close chat" });
    expect(button).toHaveAttribute("type", "button");
    expect(ref.current).toBe(button);
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
    rerender(<Button type="submit">Send</Button>);
    expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute("type", "submit");
  });
});

describe("ButtonLink", () => {
  it("with `to` is a router link that looks like a button", () => {
    render(
      <MemoryRouter>
        <ButtonLink variant="secondary" size="sm" to="/accounting/budgets">
          Set a budget
        </ButtonLink>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Set a budget" });
    expect(link).toHaveAttribute("href", "/accounting/budgets");
    expect(link).toHaveAttribute("class", "btn btn-soft btn-small");
  });

  it("with `href` is a plain link", () => {
    render(
      <ButtonLink href="https://example.com/receipt" target="_blank" rel="noopener noreferrer">
        View receipt
      </ButtonLink>,
    );
    const link = screen.getByRole("link", { name: "View receipt" });
    expect(link).toHaveAttribute("href", "https://example.com/receipt");
    expect(link).toHaveAttribute("class", "btn");
  });
});

describe("Chip", () => {
  it("is a type=button pill; `pressed` sets aria-pressed, and leaving it out sets none", () => {
    render(
      <ChipGroup aria-label="Days shown">
        <Chip pressed>7 days</Chip>
        <Chip pressed={false}>30 days</Chip>
        <Chip className="extra">Ask</Chip>
      </ChipGroup>,
    );
    const group = screen.getByRole("group", { name: "Days shown" });
    expect(group).toHaveClass("chips");
    const on = screen.getByRole("button", { name: "7 days" });
    expect(on).toHaveAttribute("type", "button");
    expect(on).toHaveAttribute("aria-pressed", "true");
    expect(on).toHaveClass("chip-btn");
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "false");
    const plain = screen.getByRole("button", { name: "Ask" });
    expect(plain).not.toHaveAttribute("aria-pressed");
    expect(plain).toHaveAttribute("class", "chip-btn extra");
  });

  it("with `to` is a link, current when pressed", () => {
    render(
      <MemoryRouter>
        <Chip to="/accounting/budgets" pressed>
          Budgets
        </Chip>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Budgets" });
    expect(link).toHaveAttribute("href", "/accounting/budgets");
    expect(link).toHaveAttribute("aria-current", "true");
    expect(link).toHaveClass("chip-btn");
  });

  it("a group can be a radiogroup named by a label elsewhere", () => {
    render(
      <>
        <span id="show-label">Show</span>
        <ChipGroup role="radiogroup" aria-labelledby="show-label" />
      </>,
    );
    expect(screen.getByRole("radiogroup", { name: "Show" })).toBeInTheDocument();
  });
});
