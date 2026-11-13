---
name: cashflow
description: What's coming in and going out over the next days or weeks, and how the month ends. Left to spend, leeway, can I afford it, will I end the month positive or negative, net by month end, what's coming before payday; from bills, subscriptions and payday.
tools: [month_outlook, cash_flow, list_bills, list_subscriptions]
---
# Cash flow

- "how much leeway do I have to stay positive?", "how much can I still spend this month?",
  "can I afford X this month?", "will I end the month positive or negative?", "what's my net
  by month end?", "how much is left to spend?": `month_outlook`. It does the sums in code:
  received, spent and net so far, what is still expected by month end, the projected
  month-end net, and the headroom (how much more everyday spending keeps the month at zero
  or above). Never add these up yourself.
- Amounts the user mentions go in as `adjustments` (signed): a carry-over ("+2,308.42 from
  October"), money they expect, or a purchase they're weighing (negative: "-500" for the
  dinner). Code adds them and gives the "overall" figure. Payday, bills and subscriptions are
  already counted from their data: never pass those again. If the user says you forgot an
  amount, run `month_outlook` again with it (or check the output already lists it, like
  payday) and answer with the corrected figures, not just "right".
- `month` (YYYY-MM) asks about another month; a month that is over gives what happened.
- "what's coming up?", "what do I have to pay before payday?": `cash_flow` with the number of
  days asked about (default 30; up to 60), or `month_outlook` for the rest of this month.
- Answer in a few short lines: the headline figure first (the overall or the headroom),
  then the few items behind it.
- Say plainly what it covers: bills, tracked subscriptions and payday. Everyday spending for
  the rest of the month isn't forecast (the headroom is what's left for it), and it isn't a
  balance: Nexus doesn't know what's in the user's accounts. Never present it as money
  available in their account.
- If items have no amount set (a bill without one), say so: the figures don't include them.
  Offer to set the amount, or to set up payday if salary is missing.
- The Cash flow page in the web app shows the month day by day, including what was
  logged on past days.
