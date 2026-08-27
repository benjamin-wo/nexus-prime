---
name: expenses
description: Log and query the user's money — "spent $12 at Starbucks", "how much did I spend on food this week", income like "Loren paid me $13".
tags: [finance, spending, income, budget]
side_effect: write
tools:
  - log_expense
  - log_income
  - query_transactions
  - split_bill_expense
  - extract_expense_from_text
---

# Expenses & income

## Logging
- For clear spending statements call `log_expense` directly (confidence 0.95).
- If the amount or merchant is ambiguous, ask ONE short clarifying question first — never guess an amount.
- Incoming money ("salary", "paid me back", "refund") → `log_income`, category salary/repayment/reimbursement/claim.
- Never log a transaction the user did not clearly state. Never invent amounts.

## Queries
- "how much did I spend..." → `query_transactions` with `categories`/`since_date`/`until_date` filters. Reply with the totals line first, then itemized rows (max ~10) and the count.
- Suggest "/split $60 with Alice and Bob" when the user mentions splitting a bill with friends.
- Big recurring totals → mention they can see the full ledger in the cockpit (/dashboard).
