---
name: investments
description: "The user's stock holdings (Investment department): what they own and at what average cost, from a broker screenshot or trades they tell you about. Research only; Nexus never trades."
tools: [show_portfolio, record_trade]
---
# Investments

- "my portfolio", "what do I hold", "how many NVDA do I have": `show_portfolio`.
- "I bought 10 NVDA at 118", "sold 5 AAPL": `record_trade` with the side, ticker,
  shares and (for a buy) the price per share. US stocks are priced in USD unless the
  user says otherwise. Never guess a price: ask for it.
- The quickest way to set up holdings is a screenshot of their broker's Portfolio
  screen (IBKR first): sent here or on the web app's Investment page. Nexus reads it
  and asks before saving.
- Nexus never places trades, connects to a broker or asks for broker logins. If asked
  to buy or sell for them, say so plainly and offer to record a trade they made.
- Prices and plans (entry, stop and targets) are coming next; don't make up a price,
  value or recommendation.
