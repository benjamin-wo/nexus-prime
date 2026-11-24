import { describe, expect, it } from "vitest";

import { checkInKey, checkInSeen, contactHref, markCheckInSeen, reasonText, REASON_TEXT } from "./safety";

describe("safety words and links", () => {
  it("links an email, and a number as a call", () => {
    expect(contactHref("eatingdisorders@sgh.com.sg")).toBe("mailto:eatingdisorders@sgh.com.sg");
    expect(contactHref("1767, or WhatsApp 9151 1767")).toBe("tel:1767");
    expect(contactHref("6294 4050")).toBe("tel:62944050");
    expect(contactHref("Ask at the front desk")).toBeNull();
  });

  it("words every reason code the server has, with none empty but ok", () => {
    expect(reasonText("ed_history")).toMatch(/eating-disorder history/);
    expect(reasonText("something_new")).toBe("");
    for (const [code, text] of Object.entries(REASON_TEXT)) expect(text !== "" || code === "ok").toBe(true);
  });

  it("remembers a seen check-in", () => {
    const key = checkInKey({ suspended: true, signposts: [], new_signals: ["b", "a"], check_in: "x" }, "2026-11-24");
    expect(key).toBe("2026-11-24:a,b");
    expect(checkInSeen(key)).toBe(false);
    markCheckInSeen(key);
    expect(checkInSeen(key)).toBe(true);
  });
});
