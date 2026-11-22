import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button, ButtonLink, buttonClass, Chip, ChipGroup, Figure, Row, RowList, Section, Tabs } from ".";

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

describe("Tabs", () => {
  const items = [
    { to: "/accounting", label: "Overview", end: true },
    { to: "/accounting/ledger", label: "Ledger" },
    { to: "/accounting/budgets", label: "Budgets" },
  ];

  it("is a nav named by its label; only the current tab has aria-current=page", () => {
    render(
      <MemoryRouter initialEntries={["/accounting/ledger"]}>
        <Tabs label="Money pages" items={items} />
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Money pages" });
    expect(nav).toHaveClass("dept-tabs");
    const ledger = screen.getByRole("link", { name: "Ledger" });
    expect(ledger).toHaveAttribute("aria-current", "page");
    expect(ledger).toHaveClass("dept-tab", "active");
    // Overview is `end`: it is not current on a page under it.
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Budgets" })).not.toHaveAttribute("aria-current");
  });
});

describe("Section", () => {
  it("is a region labelled by its heading, with one action and a soft body", () => {
    render(
      <Section id="for-today" title="For today" action={<Button variant="text">See all 8</Button>} className="extra">
        <p>Body</p>
      </Section>,
    );
    const region = screen.getByRole("region", { name: "For today" });
    expect(region).toHaveAttribute("aria-labelledby", "for-today");
    expect(screen.getByRole("heading", { level: 2, name: "For today" })).toHaveAttribute("id", "for-today");
    expect(screen.getByRole("button", { name: "See all 8" })).toBeInTheDocument();
    const body = screen.getByText("Body").parentElement;
    expect(body).toHaveClass("card", "extra");
  });
});

describe("Row", () => {
  it("shows the title, sub-line and trailing figure; `to` makes the row one link, actions stay outside it", () => {
    render(
      <MemoryRouter>
        <RowList aria-label="Latest">
          <Row title="Corner bakery" sub="Food · Thursday" trailing="12.40" />
          <Row
            title="Weekly groceries"
            sub="Thursday"
            trailing="86.15"
            to="/accounting/ledger"
            actions={<Button size="sm">Split</Button>}
          />
        </RowList>
      </MemoryRouter>,
    );
    const list = screen.getByRole("list", { name: "Latest" });
    expect(list).toHaveClass("row-list");
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(screen.getByText("12.40")).toHaveClass("row-trailing");
    expect(screen.getByText("Food · Thursday")).toHaveClass("row-sub");
    expect(screen.queryAllByRole("link")).toHaveLength(1);
    const link = screen.getByRole("link", { name: /Weekly groceries/ });
    expect(link).toHaveAttribute("href", "/accounting/ledger");
    expect(link).toHaveTextContent("86.15");
    const split = screen.getByRole("button", { name: "Split" });
    expect(link).not.toContainElement(split);
    expect(rows[1]).toContainElement(split);
  });

  it("with onClick is a button", async () => {
    const onClick = vi.fn();
    render(<Row title="Look at this" trailing="Look" onClick={onClick} />);
    const button = screen.getByRole("button", { name: /Look at this/ });
    expect(button).toHaveAttribute("type", "button");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("Figure", () => {
  const motion = (reduce: boolean) =>
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: reduce && query.includes("prefers-reduced-motion"),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    );
  /** An IntersectionObserver that sees its element at once. */
  const seen = () =>
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(private cb: (e: { isIntersecting: boolean }[]) => void) {}
        observe() {
          this.cb([{ isIntersecting: true }]);
        }
        disconnect() {}
      },
    );

  afterEach(() => vi.unstubAllGlobals());

  it("shows the label, the value and the extra line, as .tile (large) or .mini-tile (small)", () => {
    render(
      <>
        <Figure label="Spent" value="SGD 1,357.40" extra="42% of the budget" data-testid="lg" />
        <Figure size="sm" label="A usual month" value="2,140.00" data-testid="sm" />
      </>,
    );
    expect(screen.getByTestId("lg")).toHaveClass("tile");
    expect(screen.getByTestId("lg")).toHaveTextContent("SpentSGD 1,357.4042% of the budget");
    expect(screen.getByText("SGD 1,357.40")).toBeInTheDocument();
    expect(screen.getByTestId("sm")).toHaveClass("mini-tile");
    expect(screen.getByText("2,140.00").parentElement).toHaveClass("mini-value");
  });

  it("counts up from zero the first time it is seen", () => {
    motion(false);
    seen();
    let frame: FrameRequestCallback | undefined;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      frame = cb;
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
    render(<Figure label="Spent" value="SGD 1,357.40" />);
    expect(screen.getByText("SGD 0.00")).toBeInTheDocument();
    act(() => frame?.(performance.now() + 10_000));
    expect(screen.getByText("SGD 1,357.40")).toBeInTheDocument();
  });

  it("with reduced motion shows the final value at once", () => {
    motion(true);
    seen();
    const raf = vi.fn();
    vi.stubGlobal("requestAnimationFrame", raf);
    render(<Figure label="Spent" value="SGD 1,357.40" />);
    expect(screen.getByText("SGD 1,357.40")).toBeInTheDocument();
    expect(raf).not.toHaveBeenCalled();
  });
});
