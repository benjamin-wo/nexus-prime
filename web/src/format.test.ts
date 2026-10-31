import { describe, expect, it } from "vitest";

import { formatClock, formatMoney, formatRange, formatWholeMoney, formatWithHome, priceWhen, txName } from "./format";

// Intl puts a no-break space after the currency code.
const plain = (text: string) => text.replace(/ /g, " ");
const money = (amount: string, currency = "SGD") => ({ amount, currency });

describe("formatRange", () => {
  it("writes the currency once with an en dash and no spaces", () => {
    expect(plain(formatRange(money("90"), money("120.5")))).toBe("SGD 90.00–120.50");
  });

  it("drops the decimals for whole figures", () => {
    expect(plain(formatRange(money("4602"), money("6760"), { whole: true }))).toBe("SGD 4,602–6,760");
    expect(plain(formatRange(money("2000", "JPY"), money("3000", "JPY"), { whole: true }))).toBe("JPY 2,000–3,000");
  });

  it("shows one amount when both ends are the same", () => {
    expect(plain(formatRange(money("500"), money("500")))).toBe("SGD 500.00");
    expect(plain(formatRange(money("500"), money("500.4"), { whole: true }))).toBe("SGD 500");
  });

  it("writes each amount in full when the currencies differ", () => {
    expect(plain(formatRange(money("90"), money("70", "USD")))).toBe("SGD 90.00 – USD 70.00");
  });
});

describe("formatWithHome", () => {
  it("follows a foreign amount with its home amount", () => {
    expect(plain(formatWithHome(money("2000", "JPY"), money("18")))).toBe("JPY 2,000 · SGD 18.00");
  });

  it("is just the amount in the home currency", () => {
    expect(plain(formatWithHome(money("818"), money("818")))).toBe("SGD 818.00");
  });

  it("is just the amount when there is no home figure", () => {
    expect(plain(formatWithHome(money("2000", "JPY"), null))).toBe("JPY 2,000");
    expect(plain(formatWithHome(money("2000", "JPY"), undefined))).toBe("JPY 2,000");
  });
});

describe("formatWholeMoney", () => {
  it("leaves the decimals off", () => {
    expect(plain(formatWholeMoney(money("6760")))).toBe("SGD 6,760");
    expect(plain(formatMoney(money("818")))).toBe("SGD 818.00");
  });
});

describe("priceWhen", () => {
  const SGT = "Asia/Singapore";

  it("writes a clock time lowercase and tight, in the given timezone", () => {
    expect(formatClock("2026-10-19T14:42:00Z", SGT)).toBe("10:42pm");
    expect(formatClock("2026-10-19T20:00:00Z", SGT)).toBe("4:00am");
    expect(formatClock("2026-10-19T14:42:00Z", "America/New_York")).toBe("10:42am");
  });

  it("labels a live price with its time", () => {
    expect(priceWhen("live", "2026-10-19T14:42:00Z", "2026-10-19", SGT)).toBe("Live · 10:42pm");
  });

  it("labels a provisional close with the time of the last price", () => {
    expect(priceWhen("provisional_close", "2026-10-19T20:00:00Z", "2026-10-19", SGT)).toBe("Close (provisional) · 4:00am");
  });

  it("labels an official close with its trading day, whatever the timezone", () => {
    expect(priceWhen("close", null, "2026-10-16", "Pacific/Auckland")).toMatch(/^Close of Fri,? (16 Oct|Oct 16)$/);
  });

  it("falls back to the plain words when the time or day is missing", () => {
    expect(priceWhen("live", null, null)).toBe("Live");
    expect(priceWhen("provisional_close", null, null)).toBe("Close (provisional)");
    expect(priceWhen("close", null, null)).toBe("Close");
    expect(priceWhen(null, null, null)).toBe("Close");
  });
});

describe("txName", () => {
  const base = { counterparty: null, direction: "out" as const, notes: null, from_wallet: null, to_wallet: null };

  it("prefers the counterparty", () => {
    expect(txName({ ...base, counterparty: "Acme Pte Ltd", direction: "in", notes: "Salary" })).toBe("Acme Pte Ltd");
  });

  it("calls money in noted Salary a salary, and other money in income", () => {
    expect(txName({ ...base, direction: "in", notes: "Salary" })).toBe("Salary");
    expect(txName({ ...base, direction: "in", notes: "Bonus" })).toBe("Income");
    expect(txName({ ...base, direction: "in" })).toBe("Income");
  });

  it("keeps the move label and No merchant for spending", () => {
    const to = { id: "w", name: "IBKR", kind: "investment" as const };
    expect(txName({ ...base, direction: "move", to_wallet: to })).toBe("→ IBKR");
    expect(txName({ ...base, notes: "Salary" })).toBe("No merchant");
  });
});
