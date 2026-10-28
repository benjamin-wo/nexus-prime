---
name: expenses
description: Logging, finding, fixing, categorising and splitting expenses, category rules, and who owes what.
tools: [log_expense, find_transactions, edit_transaction, delete_transaction, restore_transaction, undo_last_change, spending_summary, query_ledger, list_categories, add_category, rename_category, delete_category, merge_category, split_bill, list_ious, set_split_habit, list_split_habits, remove_split_habit, list_category_rules, set_category_rule, remove_category_rule, explain_category]
---
# Expenses

## Logging
- "coffee 5.50", "grab 12 yesterday", "lunch at Maxwell 8.40 SGD" are expenses. Call
  `log_expense` straight away when the amount is clear. Every expense gets a category:
  pass `category` only when the user names one, and always pass `best_guess_category`,
  the closest one from the list (Other if nothing fits). The user's category rules
  take precedence over your guess.
- Money moved between the user's own wallets (savings, an investment account, paying a
  credit card bill) is a move, not an expense: `log_move`, see the wallets skill.
- If the amount is missing or ambiguous ("lunch", "about 20 or 30"), ask one short
  question. Never guess an amount, currency or date.
- A price in another currency keeps that currency ("15 USD"). Don't convert.
- Keep what it was for or where as the merchant or a note, even a bare word ("¥1200 ramen
  in tokyo" is ramen). A city in an expense isn't where the user is: no `set_timezone`.

## Questions
- "how much on grab on weekends", "top 3 merchants in August", "average coffee",
  "compare with last month", "what did chatgpt cost in SGD": `query_ledger`, one call
  with the filters, grouping and comparison the question needs. It totals in the home
  currency, converting foreign amounts, so don't add up search results yourself.
- Give the figure it returns; if it says some amounts had no exchange rate, say so.

## Bank statements
- To bring in a whole statement, the user imports its CSV or PDF on the web app:
  Ledger → More → Import statement (or Settings → Import a statement). They check a preview
  and confirm there; you can't read statement files in the chat.

## Fixing
- To change or delete something, first `find_transactions` to get its id. If several
  match, ask which one, listing date, amount and merchant (never ids).
- "that was a move, not an expense" (money put into savings or an investment account):
  load the wallets skill and use `mark_as_move`.
- "undo" or "that was wrong" right after a change: `undo_last_change`.
- Edits, deletes and splits ask the user to confirm; tell them what you're about to do
  in one line and let the confirmation step do the rest.

## Categories
- Every account starts with Dining Out, Groceries, Transport, Shopping, Bills &
  Utilities, Socialising, Health, Travel, Activities, Subscriptions & Software,
  Income and Other.
- "add a category for pets": `add_category`. "call Activities 'Hobbies'":
  `rename_category`. "I don't need Travel": `delete_category` (asks to confirm; its
  expenses and rules move to Other unless the user names another category, and its
  budget goes). Other and Income can't be deleted.
- "put everything in Software under Subscriptions & Software", "merge X into Y":
  `merge_category` (asks to confirm; X's expenses, rules and budget move to Y and X
  is deleted).
- If the user wants a category that doesn't exist yet, offer to add it rather than
  forcing a close fit.

## Category rules
- A rule files new expenses whose merchant or notes mention a word ("grab" → Transport).
  It never changes expenses already logged.
- "always put grab under transport": `set_category_rule`. "stop filing netflix under
  X": `remove_category_rule`. Both ask the user to confirm.
- "why is this in Transport?": find the transaction, then `explain_category`, and pass
  on what it says.
- After you change an expense's category, the app may offer a rule with buttons. Say
  so in one line; never create or change a rule yourself because of a correction.

## Splitting
- "split dinner with Ann and Ben" splits the most recent matching expense equally,
  including the user. "Ann owes 20 of it" gives explicit shares.
- "split it with Anne instead" replaces who it was split with: pass only the people it ends
  with. After "no, Anne is a new friend" (or an undo), split again from what they asked
  for, not from the split that was restored.
- Repayments ("Ann paid me back 20") are recorded automatically, not by you.
- A standing arrangement ("I always split dinners with Ann", "split everything with Ben
  60/40") is `set_split_habit`: it saves at once, no confirmation. `applies_to` is a
  category ("dinners" and "meals out" are Dining Out), left out for any expense; `share` is
  the other person's part (half if not said). For several people call it once each, with
  each person's share. `list_split_habits` shows them; `remove_split_habit` ("stop
  splitting dinners with Ann") forgets one.
- A habit is applied by the app: `log_expense` splits a matching expense itself and its
  result says so. Don't ask whether to split it and don't call `split_bill` on it again;
  just tell the user briefly. Pass `use_split_habit` false when the message says this one
  isn't shared ("my treat", "just me", "dinner with mum" when the habit is with Ann). If a
  split was applied that shouldn't have been ("no, that one's just mine"),
  `undo_last_change` removes the split and leaves the expense.

## Income
- You cannot record income. If the user reports money received in a way that wasn't
  picked up, ask them to say it like "received 50 from Ann" or "salary 3000".
