import { describe, expect, it } from "vitest";

import type { Wallet, WalletKind } from "./api";
import { canPay, keepLast4, payingWallets, walletLabel } from "./wallets";

const wallet = (id: string, kind: WalletKind): Wallet => ({ id, name: id, kind, match_words: [] });

describe("keepLast4", () => {
  it("leaves up to four digits as typed", () => {
    expect(keepLast4("")).toEqual({ value: "", trimmed: false });
    expect(keepLast4("43")).toEqual({ value: "43", trimmed: false });
    expect(keepLast4("4321")).toEqual({ value: "4321", trimmed: false });
  });

  it("keeps the last four of a longer number and says it dropped some", () => {
    expect(keepLast4("000000000004321")).toEqual({ value: "4321", trimmed: true });
    expect(keepLast4("43215")).toEqual({ value: "3215", trimmed: true });
  });

  it("drops spaces, dashes and letters before counting", () => {
    expect(keepLast4("0000 0000 0000 4321")).toEqual({ value: "4321", trimmed: true });
    expect(keepLast4("43-21")).toEqual({ value: "4321", trimmed: false });
    expect(keepLast4("ab12")).toEqual({ value: "12", trimmed: false });
  });
});

describe("walletLabel", () => {
  it("writes a card with its last four digits", () => {
    expect(walletLabel({ name: "Citi PremierMiles", last4: "4321" })).toBe("Citi PremierMiles ·· 4321");
  });

  it("is just the name without them", () => {
    expect(walletLabel({ name: "Cash", last4: null })).toBe("Cash");
    expect(walletLabel({ name: "Main account" })).toBe("Main account");
  });
});

describe("the wallets that can pay", () => {
  const all = [
    wallet("spending", "spending"),
    wallet("invest", "investment"),
    wallet("save", "savings"),
    wallet("cash", "cash"),
    wallet("other", "other"),
    wallet("citi", "card"),
    wallet("dbs", "card"),
  ];

  it("never include investment or savings wallets", () => {
    expect(canPay(wallet("a", "investment"))).toBe(false);
    expect(canPay(wallet("a", "savings"))).toBe(false);
    for (const kind of ["card", "spending", "cash", "other"] as const) expect(canPay(wallet("a", kind))).toBe(true);
  });

  it("list cards first, then Spending, Cash and the others", () => {
    expect(payingWallets(all).map((w) => w.id)).toEqual(["citi", "dbs", "spending", "cash", "other"]);
  });
});
