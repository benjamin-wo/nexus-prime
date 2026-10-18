import { describe, expect, it } from "vitest";

import { formatMoney, formatRange, formatWholeMoney, formatWithHome } from "./format";

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
