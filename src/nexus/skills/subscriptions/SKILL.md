---
name: subscriptions
description: Recurring payments and subscriptions spotted in the ledger, their prices and monthly total.
tools: [list_subscriptions]
---
# Subscriptions

- "what subscriptions do I have?", "how much do I spend on subscriptions?", "did Netflix
  go up?": `list_subscriptions`, then answer in a few short lines.
- Nexus spots them itself: when the same merchant charges a similar amount weekly,
  monthly or yearly three times in a row, it asks the user once (Track it / No). Nothing
  is tracked without a yes, and a no isn't asked again.
- Once tracked, Nexus says when the price changes. It never cancels anything: cancelling
  is done with the provider.
- To stop tracking one, or answer a waiting question, point them to the Subscriptions
  card on the Plan page.
- A bill they want reminding about before it's due is different: that's the bills skill.
