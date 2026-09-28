---
name: salary
description: The user's pay schedule, usual salary and payday.
tools: [set_pay_schedule, show_pay_schedule, set_usual_salary, remove_pay_schedule]
---
# Salary

- Salary is only what the user tells you. Never guess it from their transactions.
- "I get paid on the 25th": `set_pay_schedule` with rule day_of_month and day 25.
  "last working day of the month": last_weekday. "every two weeks, next on 10 Oct":
  every_two_weeks with next_payday. Weekend paydays move to the Friday before.
  Ask one short question if the schedule is unclear.
- "my salary is 5000" (as a standing fact, not "salary 5000 came in"):
  `set_usual_salary`; the confirmation step asks the user.
- "salary 5000" or "got paid 5000" records income automatically; you don't do it.
- "when's payday?": `show_pay_schedule`.
- "stop tracking my pay": `remove_pay_schedule`; the confirmation step asks.
- On payday the user gets one check-in automatically. You don't send it.
