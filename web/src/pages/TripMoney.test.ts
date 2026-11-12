import { describe, expect, it } from "vitest";

import type { Balance, BalancePart, Money, SettleResult, ToSplit, TripDetail } from "../api";
import { balanceWords, joinNames, partsTotal, plannedAhead, setAsideText, settleConfirmText, settledText, splitAskText, splitConfirmText, sumByCurrency, toSplitSub, totalOf } from "./TripMoney";
import { balanceAmount } from "./TripStage";

// Made-up people and amounts only. Intl puts a no-break space after the currency code.
const plain = (text: string) => text.replace(/\u00a0/g, " ");
const sgd = (amount: string): Money => ({ amount, currency: "SGD" });
const jpy = (amount: string): Money => ({ amount, currency: "JPY" });
const part = (kind: BalancePart["kind"], amount: Money, extra: Partial<BalancePart> = {}): BalancePart => ({
  kind,
  id: "p1",
  label: null,
  amount,
  home: null,
  on: "2027-04-03",
  ...extra,
});
const balance = (person: string, net: Money | null, extra: Partial<Balance> = {}): Balance => ({
  person,
  direction: net === null ? null : Number(net.amount) > 0 ? "owes_you" : Number(net.amount) < 0 ? "you_owe" : "even",
  net,
  net_by_currency: net === null ? [] : [net],
  owes_you: [],
  you_owe: [],
  ...extra,
});

describe("names", () => {
  it("joins them the way you would say them", () => {
    expect(joinNames([])).toBe("");
    expect(joinNames(["Alex"])).toBe("Alex");
    expect(joinNames(["Alex", "Sam"])).toBe("Alex and Sam");
    expect(joinNames(["Alex", "Sam", "Ben"])).toBe("Alex, Sam and Ben");
  });
});

describe("where you stand with a person", () => {
  it("says who owes whom", () => {
    expect(plain(balanceWords(balance("Alex", sgd("768"))))).toBe("Alex owes you SGD 768.00");
    expect(plain(balanceWords(balance("Sam", sgd("-40"))))).toBe("You owe Sam SGD 40.00");
    expect(plain(balanceWords(balance("Ben", sgd("0"))))).toBe("All square with Ben");
  });

  it("shows each currency when there is no single total", () => {
    const mixed = balance("Alex", null, { net_by_currency: [jpy("4000"), sgd("-20")] });
    expect(plain(balanceWords(mixed))).toBe("Alex owes you JPY 4,000 and you owe Alex SGD 20.00");
    const oneWay = balance("Alex", null, { net_by_currency: [jpy("4000"), sgd("20")] });
    expect(plain(balanceWords(oneWay))).toBe("Alex owes you JPY 4,000 + SGD 20.00");
    expect(plain(balanceWords(balance("Sam", null, { net_by_currency: [jpy("-4000")] })))).toBe("You owe Sam JPY 4,000");
  });

  it("uses the currency amount when a rate is missing but the currency is one", () => {
    const b = balance("Alex", null, { direction: "owes_you", net_by_currency: [jpy("4000")] });
    expect(plain(balanceWords(b))).toBe("Alex owes you JPY 4,000");
  });

  it("formats the net without its sign", () => {
    expect(plain(balanceAmount(balance("Sam", sgd("-40"))))).toBe("SGD 40.00");
    expect(plain(balanceAmount(balance("Alex", sgd("1234.5"))))).toBe("SGD 1,234.50");
    expect(plain(balanceAmount(balance("Alex", null, { net_by_currency: [jpy("-4000"), sgd("20")] })))).toBe("JPY 4,000 + SGD 20.00");
  });
});

describe("splitting everything", () => {
  const cost = (amount: string | null) => ({ home: amount === null ? null : sgd(amount) });

  it("totals the costs in the home currency", () => {
    expect(totalOf([cost("1000.10"), cost("1139.90")], "SGD")).toEqual({ total: sgd("2140"), unrated: 0 });
    expect(totalOf([cost("10"), cost(null)], "SGD").unrated).toBe(1);
  });

  it("asks with the count, the total and the names", () => {
    const six = ["300", "300", "300", "300", "300", "640"].map(cost);
    expect(plain(splitConfirmText(six, ["Alex", "Sam"], "SGD"))).toBe("Split 6 costs (SGD 2,140.00) evenly with Alex and Sam?");
    expect(plain(splitConfirmText([cost("90")], ["Alex"], "SGD"))).toBe("Split 1 cost (SGD 90.00) evenly with Alex?");
  });

  it("says what it could not count", () => {
    expect(plain(splitConfirmText([cost("90"), cost(null)], ["Alex"], "SGD"))).toBe(
      "Split 2 costs (SGD 90.00, not counting 1 cost with no exchange rate yet) evenly with Alex?",
    );
    expect(plain(splitConfirmText([cost(null)], ["Alex"], "SGD"))).toBe("Split 1 cost evenly with Alex?");
  });
});

describe("the question in the To do card", () => {
  const cost = (amount: string | null) => ({ home: amount === null ? null : sgd(amount) });
  const item = (title: string | null, amount: string | null): ToSplit => ({
    transaction_id: title ?? "x",
    day: "2027-04-02",
    counterparty: title,
    category: null,
    amount: sgd(amount ?? "0"),
    home: amount === null ? null : sgd(amount),
  });

  it("adds each share to the question", () => {
    expect(plain(splitAskText([cost("300"), cost("312.4")], ["Alex"], "SGD"))).toBe("Split 2 costs (SGD 612.40) evenly with Alex? Each share is SGD 306.20.");
    expect(plain(splitAskText([cost("100")], ["Alex", "Sam"], "SGD"))).toBe("Split 1 cost (SGD 100.00) evenly with Alex and Sam? Each share is about SGD 33.33.");
  });

  it("leaves the share out when a cost has no exchange rate yet", () => {
    expect(plain(splitAskText([cost("90"), cost(null)], ["Alex"], "SGD"))).toBe(
      "Split 2 costs (SGD 90.00, not counting 1 cost with no exchange rate yet) evenly with Alex?",
    );
  });

  it("names the first three costs under the count, and how many more", () => {
    const some = [item("Wi-Fi", "12.40"), item("teamLab", "300"), item("Ryokan deposit", "300")];
    expect(plain(toSplitSub(some, "SGD"))).toBe("SGD 612.40 · Wi-Fi, teamLab, Ryokan deposit");
    expect(plain(toSplitSub([...some, item(null, "20"), item("Taxi", "5")], "SGD"))).toBe("SGD 637.40 · Wi-Fi, teamLab, Ryokan deposit and 2 more");
    expect(plain(toSplitSub([item("Wi-Fi", null)], "SGD"))).toBe("Wi-Fi");
  });
});

describe("what is planned and not spent yet", () => {
  const detail = (planned: Record<string, Money>, spent: [string, string][], bookings: object[] = []) =>
    ({
      trip: { planned },
      spending: { spent: sgd("0"), categories: spent.map(([name, amount]) => ({ name, planned: null, spent: sgd(amount) })) },
      bookings,
    }) as unknown as TripDetail;

  it("is each planned cost less what is already spent in it", () => {
    expect(plannedAhead(detail({ "Dining Out": sgd("600"), Tours: sgd("200") }, [["dining out", "150"]]))).toBe(650);
  });

  it("never counts a category that is over its plan as negative", () => {
    expect(plannedAhead(detail({ Tours: sgd("200") }, [["Tours", "250"]]))).toBe(0);
  });

  it("takes off a booking for it that is not logged yet", () => {
    const hotel = { scheduled: true, logged: false, cost: sgd("500"), category: "Stay" };
    expect(plannedAhead(detail({ Stay: sgd("800") }, [], [hotel, { ...hotel, logged: true }]))).toBe(300);
  });
});

describe("adding up", () => {
  it("sums per currency", () => {
    expect(sumByCurrency([jpy("1000"), sgd("10.10"), jpy("500"), sgd("0.20")])).toEqual([jpy("1500"), sgd("10.3")]);
    expect(partsTotal([part("iou", sgd("5")), part("iou", sgd("7"))])).toEqual([sgd("12")]);
  });
});

describe("marking someone settled", () => {
  it("says what it records when they owe you", () => {
    const b = balance("Alex", sgd("768"), { owes_you: [part("iou", sgd("500")), part("iou", sgd("268"))] });
    expect(plain(settleConfirmText(b, true))).toBe("This records that Alex paid you back SGD 768.00. Nexus doesn't move any money.");
  });

  it("says what it records when you owe them, with or without your share as spent", () => {
    const b = balance("Sam", sgd("-40"), { you_owe: [part("payment", sgd("40"))] });
    expect(plain(settleConfirmText(b, true))).toBe("This records that you paid Sam SGD 40.00 and counts it as spent. Nexus doesn't move any money.");
    expect(plain(settleConfirmText(b, false))).toBe(
      "This marks the SGD 40.00 you owe Sam as paid, without adding it to what you've spent. Nexus doesn't move any money.",
    );
  });

  it("covers both ways at once", () => {
    const b = balance("Alex", sgd("728"), { owes_you: [part("iou", sgd("768"))], you_owe: [part("payment", sgd("40"))] });
    expect(plain(settleConfirmText(b, true))).toBe(
      "This records that Alex paid you back SGD 768.00. It also records that you paid Alex SGD 40.00 and counts it as spent. Nexus doesn't move any money.",
    );
  });

  it("says what was recorded", () => {
    const result: SettleResult = { person: "Alex", ious_repaid: 2, payments_settled: 1, income: [sgd("768")], expenses: [sgd("40")] };
    expect(plain(settledText(result))).toBe(
      "Settled with Alex: 2 IOUs from Alex marked paid back, SGD 768.00 recorded as money in; 1 payment you owed Alex marked paid, SGD 40.00 recorded as spent.",
    );
    expect(plain(settledText({ ...result, ious_repaid: 0, income: [], expenses: [] }))).toBe(
      "Settled with Alex: 1 payment you owed Alex marked paid, nothing added to what you've spent.",
    );
    expect(plain(settledText({ person: "Ben", ious_repaid: 0, payments_settled: 0, income: [], expenses: [] }))).toBe("Nothing was left to settle with Ben.");
  });
});

describe("the set-aside sentence", () => {
  const plan = (saved: Money | null, by_start: Money | null, paydays_left = 3) => ({ per_payday: sgd("500"), saved, by_start, paydays_left });

  it("gives what's saved so far and what it comes to by the trip", () => {
    expect(plain(setAsideText(plan(sgd("100"), sgd("1600")), "25 Oct"))).toBe(
      "SGD 500.00 each payday: about SGD 100.00 so far, SGD 1,600.00 by the trip (3 paydays left, next 25 Oct).",
    );
  });

  it("leaves out the saved clause when nothing is saved yet", () => {
    expect(plain(setAsideText(plan(sgd("0"), sgd("1500")), "25 Oct"))).toBe("SGD 500.00 each payday: SGD 1,500.00 by the trip (3 paydays left, next 25 Oct).");
    expect(plain(setAsideText(plan(null, sgd("1500")), null))).toBe("SGD 500.00 each payday: SGD 1,500.00 by the trip (3 paydays left).");
  });

  it("leaves out the by-the-trip clause when it is missing", () => {
    expect(plain(setAsideText(plan(sgd("100"), null, 1), "25 Oct"))).toBe("SGD 500.00 each payday: about SGD 100.00 so far (1 payday left, next 25 Oct).");
  });

  it("is just the amount and the paydays when there is neither", () => {
    expect(plain(setAsideText(plan(sgd("0"), null), "25 Oct"))).toBe("SGD 500.00 each payday (3 paydays left, next 25 Oct).");
  });
});
