---
name: daily-briefing
description: Scheduled daily morning briefing of top global news and stock market news — "send me a daily morning summary of news and markets".
tags: [news, scheduling, briefing]
side_effect: write
tools:
  - schedule_daily_briefing
  - send_daily_briefing_now
---

# Daily briefing

- Recurring ask ("daily morning summary of news/markets") → `schedule_daily_briefing`; confirm the 09:00 SGT delivery and that /jobs manages it.
- One-shot ("what's the market news today") → `send_daily_briefing_now` and present the content.
- Only summarize what the search results contain — never invent headlines.
