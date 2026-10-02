---
name: updates
description: How often the user hears from Nexus on Telegram about their transactions.
tools: [transaction_updates]
---
# Updates

- "tell me about each transaction", "just a daily summary", "stop the updates":
  `transaction_updates` with the choice they made. With no choice, it shows the
  current setting.
- The choices are each one as it happens, hourly, 3 times a day, end of day (the
  default) or off.
- The end-of-day summary goes at 9pm unless the user picks a time: "send my summary at
  11:59pm", "daily summary at 7am" is `transaction_updates` with frequency daily and
  `at` as 24-hour HH:MM (23:59, 07:00). It goes at that time even late at night,
  because they chose it. The other choices have fixed times that can't be changed.
