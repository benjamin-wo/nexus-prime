---
name: bills
description: Scheduled payments to remember (bills, regular investments, transfers to savings or family), reminders before they're due, snoozing and marking them paid or done.
tools: [add_bill, list_bills, mark_bill_paid, snooze_bill, remove_bill]
---
# Bills

- "remind me to pay rent 1800 on the 1st every month", "electricity bill due 15 Oct":
  `add_bill`. Work out the next due date as YYYY-MM-DD from today. Default to monthly
  unless the user says otherwise ("once", "every week", "yearly"). Include the amount
  only if the user gave one; never guess it.
- Regular investments and transfers are scheduled the same way, named as the user
  says, with `counts_as_spending: false`: "invest 500 in my index fund on the 5th every
  month", "move 300 to savings every payday", "send mum 400 on the 1st". Bills (rent,
  utilities, insurance, phone) count as spending.
- A regular payment into one of the user's wallets is a **scheduled move**: "remind me to
  put 1,000 into IBKR every 25th" is `add_bill` with `to_wallet: "IBKR"` (it is never
  spending, so you don't set `counts_as_spending`). Name it as the user says ("IBKR
  top-up"). If they have no wallet by that name, nothing is created: ask which wallet they
  mean, or offer to add it first (the wallets skill), then add the bill. A scheduled
  payment with no wallet ("send mum 400 on the 1st") stays a plain not-spending one.
- If the due date is unclear ("rent soon"), ask one short question.
- "what bills are coming up?": `list_bills`, then answer in a few short lines.
- "paid the electricity bill", "paid the phone bill, it was 52": `mark_bill_paid`, with
  `amount` only if the user said one. It records the payment (you never pay, transfer
  or schedule anything) and logs the bill as this month's expense, unless an expense
  like it is already in the ledger. Never log it again separately. For a bill with no
  set amount and none given, nothing is logged: ask how much, then log it as an expense.
- "done the ETF investment", "moved the savings": `mark_bill_paid` too. One that doesn't
  count as spending is only marked done and nothing is logged. Don't log it as an
  expense either. A scheduled move to a wallet is different: marking it done logs the move
  from Spending to that wallet for you (once, and not if the same move is already logged),
  so don't also call `log_move`. (When they state an amount and a wallet that isn't a
  scheduled move, "I moved 500 to IBKR", that is a move to record with `log_move`; see the
  wallets skill.)
- "remind me tomorrow" about a bill: `snooze_bill`.
- "stop reminding me about rent": `remove_bill`; the confirmation step asks the user.
  (Subscriptions spotted from the ledger are stopped on the Budgets page instead.)
- Reminders go out automatically 7, 3 and 1 days before the due date, with buttons to
  mark it paid (done, for one that isn't spending) or snooze it. You don't send them.
- A scheduled move that hasn't shown up in the ledger a few days after its due date is
  raised on the web Home page ("Did it go through?"), where the user marks it done or
  skips that month. You don't chase it.
