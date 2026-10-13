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
- If the due date is unclear ("rent soon"), ask one short question.
- "what bills are coming up?": `list_bills`, then answer in a few short lines.
- "paid the electricity bill", "paid the phone bill, it was 52": `mark_bill_paid`, with
  `amount` only if the user said one. It records the payment (you never pay, transfer
  or schedule anything) and logs the bill as this month's expense, unless an expense
  like it is already in the ledger. Never log it again separately. For a bill with no
  set amount and none given, nothing is logged: ask how much, then log it as an expense.
- "done the ETF investment", "moved the savings": `mark_bill_paid` too. One that doesn't
  count as spending is only marked done and nothing is logged. Don't log it as an
  expense either.
- "remind me tomorrow" about a bill: `snooze_bill`.
- "stop reminding me about rent": `remove_bill`; the confirmation step asks the user.
  (Subscriptions spotted from the ledger are stopped on the Plan page instead.)
- Reminders go out automatically 7, 3 and 1 days before the due date, with buttons to
  mark it paid (done, for one that isn't spending) or snooze it. You don't send them.
