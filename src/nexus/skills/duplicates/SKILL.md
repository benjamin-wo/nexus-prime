---
name: duplicates
description: One payment recorded twice, such as a bank's card alert and the shop's receipt, or a typed entry and the email that followed. Finding and combining them.
tools: [find_duplicates, combine_duplicate_transactions, find_transactions, restore_transaction]
---
# Duplicates

- "any duplicates?", "did that grab get logged twice?": `find_duplicates`. It lists pairs
  with the same amount within a day by a similar merchant, from different places, such
  as a card alert ("Grab* A-7KX…") and the shop's receipt ("Grab Singapore").
- Only call `combine_duplicate_transactions` when the user says a pair is the same
  payment. It keeps the more readable name and deletes the extra, which can be restored
  with `restore_transaction`.
- Two entries the user typed themselves are never offered as duplicates: a second kopi
  is a second kopi.
- An email that looks like a payment already recorded is asked about as "same payment?";
  `answer_email` with `same` adds nothing.
- On the web, the Ledger tags each pair with Merge and Not a duplicate.
