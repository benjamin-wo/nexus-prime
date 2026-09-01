---
name: expenses
description: Log and query the user's money — "spent $12 at Starbucks", "how much did I spend on food this week", income like "Loren paid me $13".
tags: [finance, spending, income, budget]
side_effect: write
tools:
  - process_extracted_expense
  - record_incoming_money
  - query_transactions
  - split_bill_expense
  - extract_expense_from_text
  - get_user_expenses
  - delete_expense
  - log_expenses_from_emails
---

# Expenses & income

## Logging
- For clear spending statements call `process_extracted_expense` directly (confidence 0.95).
- If the amount or merchant is ambiguous, ask ONE short clarifying question first — never guess an amount.
- Incoming money ("salary", "paid me back", "refund") → `record_incoming_money`, category salary/repayment/reimbursement/claim.
- Never log a transaction the user did not clearly state. Never invent amounts.

## Deleting
- "delete/remove [merchant] expense" → find it with `get_user_expenses` (or `query_transactions`), then call `delete_expense` with the matching id.
- Deletion is permanent; never delete a transaction the user did not clearly identify.
- Also remove the entry from your reply on the dashboard/ledger — the delete takes effect immediately.

## Queries
- "how much did I spend..." → `query_transactions` with `categories`/`since_date`/`until_date` filters. Reply with the totals line first, then itemized rows (max ~10) and the count.
- Suggest "/split $60 with Alice and Bob" when the user mentions splitting a bill with friends.
- Big recurring totals → mention they can see the full ledger in the cockpit (/dashboard).
