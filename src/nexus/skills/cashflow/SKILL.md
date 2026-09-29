---
name: cashflow
description: What's coming in and going out over the next days or weeks, from bills, subscriptions and payday.
tools: [cash_flow, list_bills, list_subscriptions]
---
# Cash flow

- "what's coming up?", "what do I have to pay before payday?", "can I afford X this
  month?": `cash_flow` with the number of days asked about (default 30; up to 60).
- Answer in a few short lines: the next few items, then the expected net.
- Say plainly what it covers: bills, tracked subscriptions and payday. Everyday
  spending isn't in it, and it isn't a balance: Nexus doesn't know what's in the
  user's accounts. Never present it as money available.
- If items have no amount set (a bill without one), say so. Offer to set the amount,
  or to set up payday if salary is missing.
- The Cash flow page in the web app shows the month day by day, including what was
  logged on past days.
