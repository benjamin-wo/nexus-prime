---
name: memory
description: Remember and recall personal facts — loyalty points/miles balances ("I have 12000 DBS points", "what are my points balances?").
tags: [memory, knowledge]
side_effect: write
tools:
  - record_points_balance
  - query_my_points_balances
---

# Personal memory (points & miles)

- A balance statement ("I have 12000 DBS points", "my Citibank miles is 45000, expiring 2027-01") → `record_points_balance`. Re-saving the same issuer+program updates it — say "updated" not "saved a new one".
- Recall ("what are my points/miles?") → `query_my_points_balances`; include expiry warnings when close.
- Only store facts the user stated. Never guess balances or expiry dates.
