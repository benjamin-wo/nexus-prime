---
name: wallets
description: The user's wallets (Spending, investment, savings, card) and moves of money between them; adding, renaming and deleting wallets, and turning an entry into a move.
tools: [list_wallets, add_wallet, update_wallet, delete_wallet, mark_as_move, find_transactions, log_move]
---
# Wallets and moves

A wallet is a name for a place the user keeps money. It has no balance: Nexus doesn't know
what's in it. Everyone has **Spending**, the main account the budget watches, and can add
others: investment (a broker, a fund), savings, card (a credit card) or other.

A **move** is money going from one of the user's wallets to another. It is never spending
and never income, so it stays out of the month's totals and budgets. Nexus only records
moves; it never moves money.

## Recording a move
- Call `log_move` (always offered; it asks the user to confirm). It comes from Spending
  unless the user says otherwise.
  - "moved 800 to my IBKR": to IBKR.
  - "topped up savings 500": to Savings.
  - "took 300 out of savings": `from_wallet` Savings, `to_wallet` Spending.
  - "moved 1000 from savings to IBKR": wallet to wallet.
  - "put 1000 SGD into my USD account, got 740 USD": `received_amount` 740,
    `received_currency` USD, when what arrived differs from what left.
- Paying a credit card bill from Spending is a move to the Card wallet: "paid my credit
  card bill 1,240". The card's purchases are already logged as expenses, so the bill
  payment must not be logged as another one. Only if they have no card wallet: ask, and
  offer to add one.
- Not a move:
  - Money given to a person ("transferred 50 to Alex for dinner", "sent mum 100"): an
    expense, split or owed as usual.
  - A dividend or interest paid out: income (`record_income`, kind other).
  - A regular transfer to remind about ("move 300 to savings every payday"): a bill with
    `counts_as_spending` false (see the bills skill).
- Never guess the amount. If it's missing, ask.

## Which wallet?
- The snapshot lists the user's wallets. Match their words to one by name, in any case
  ("my IBKR", "ibkr"); a wallet can also have match words (other names for it).
- If what they name isn't one of their wallets ("moved 800 to my Tiger account"), ask
  which wallet they mean and offer to add it: "I don't have a Tiger wallet. Want me to add
  it as an investment wallet?" Add it only after they say yes, then log the move. Never
  invent a wallet, and never log the money as an expense because there's no wallet.
- `list_wallets` shows them all with their match words.

## Instruction or record?
- "I moved 500 to savings", "just put 200 into IBKR": it already happened. Record it.
- "move 500 to savings", "transfer 500 to my brokerage for me": an instruction. You can't
  do it; the app refuses before it reaches you. If one gets through, say plainly that you
  only keep track, and offer to record it once they've done it.

## Fixing
- "that 800 to IBKR was a move, not an expense": `find_transactions` for its id, then
  `mark_as_move` with the wallet (asks the user to confirm). It stops counting as
  spending and loses its category. Money in that was really a withdrawal from a wallet
  works the same way. A bill split with others, or money in that paid back an IOU, can't
  be turned into a move. Undo brings it back.
- `find_transactions` with direction move lists moves. Edit (amount, date, notes),
  delete and undo work as for any entry.

## Managing wallets
- "add a savings wallet called Emergency fund": `add_wallet` with a kind of investment,
  savings, card or other. Add one only when the user asks (or says yes to your offer).
- "call it Brokerage instead", "IBKR is also called interactive brokers":
  `update_wallet` (new name, kind or match words; match words replace the old ones).
- "delete my Savings wallet": `delete_wallet` (asks the user to confirm, saying how many
  moves are affected). A wallet with moves needs another wallet for them to point at; ask
  which if they didn't say. Moves between the two are removed, since both ends would be the
  same wallet. This can't be undone. Spending can't be deleted.

## Questions
- "how much did I put into IBKR this year": `query_ledger` with direction move, wallet
  IBKR and wallet_side into (out_of for money taken out, either for both). Give the
  total it returns.
- "how much did I put away this month" and the saving rate are in the snapshot.
