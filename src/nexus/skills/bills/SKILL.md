---
name: bills
description: Bills to remember, reminders before they're due, snoozing and marking them paid.
tools: [add_bill, list_bills, mark_bill_paid, snooze_bill, remove_bill]
---
# Bills

- "remind me to pay rent 1800 on the 1st every month", "electricity bill due 15 Oct":
  `add_bill`. Work out the next due date as YYYY-MM-DD from today. Default to monthly
  unless the user says otherwise ("once", "every week", "yearly"). Include the amount
  only if the user gave one; never guess it.
- If the due date is unclear ("rent soon"), ask one short question.
- "what bills are coming up?": `list_bills`, then answer in a few short lines.
- "paid the electricity bill": `mark_bill_paid`. This only records it: you never pay,
  transfer or schedule anything, and it doesn't log an expense. If they also want it
  in the ledger, log it as an expense separately.
- "remind me tomorrow" about a bill: `snooze_bill`.
- "stop tracking Netflix": `remove_bill`; the confirmation step asks the user.
- Reminders go out automatically 7, 3 and 1 days before the due date, with buttons to
  mark it paid or snooze it. You don't send them.
