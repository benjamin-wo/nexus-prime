import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Holding } from "../api";
import { priceWhen } from "../format";
import { renderWithProviders } from "../testing";
import { HoldingRow } from "./Investment";

// A made-up holding of a made-up stock.
const acme: Holding = {
  symbol: "ACME",
  quantity: "10",
  average_cost: { amount: "150.00", currency: "USD" },
  cost: { amount: "1500.00", currency: "USD" },
  updated_at: "2026-10-20T12:00:00Z",
  price: { amount: "182.40", currency: "USD" },
  price_day: "2026-10-20",
  price_kind: "close",
  price_at: null,
  value: { amount: "1824.00", currency: "USD" },
  gain: { amount: "324.00", currency: "USD" },
  gain_percent: "21.6",
  day_change: null,
  day_percent: null,
  value_home: null,
  earnings: null,
};

function renderRow(position: Holding, kind: Holding["price_kind"] & string) {
  return renderWithProviders(
    <table>
      <tbody>
        <HoldingRow position={position} kind={kind} onChanged={() => {}} />
      </tbody>
    </table>,
  );
}

describe("a holding's price", () => {
  // The phone card is the same markup as the table row, so a caption that is in the row is in
  // the card. The stylesheet hides the common kind's caption on desktop only.
  it("always says when it is from, even when the table's own label says so too", () => {
    renderRow(acme, "close");
    const cell = screen.getByText("182.40", { exact: false }).closest("td") as HTMLElement;
    expect(within(cell).getByText(priceWhen("close", null, "2026-10-20"))).toBeInTheDocument();
    expect(cell.querySelector(".when-common")).not.toBeNull();
  });

  it("says so for a live price", () => {
    renderRow({ ...acme, price_kind: "live", price_at: "2026-10-20T14:42:00Z" }, "close");
    const cell = screen.getByText("182.40", { exact: false }).closest("td") as HTMLElement;
    expect(within(cell).getByText(/^Live · /)).toBeInTheDocument();
    expect(cell.querySelector(".when-common")).toBeNull();
  });

  it("says so for a provisional close", () => {
    renderRow({ ...acme, price_kind: "provisional_close", price_at: "2026-10-20T20:05:00Z" }, "provisional_close");
    const cell = screen.getByText("182.40", { exact: false }).closest("td") as HTMLElement;
    expect(within(cell).getByText(/^Close \(provisional\) · /)).toBeInTheDocument();
  });

  it("has no caption when there is no price yet", () => {
    renderRow({ ...acme, price: null, price_day: null, price_kind: null, value: null }, "close");
    const cell = screen.getByText("—").closest("td") as HTMLElement;
    expect(cell.querySelector(".price-when")).toBeNull();
  });
});
