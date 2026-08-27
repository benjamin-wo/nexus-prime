---
name: reminders
description: Create, list, and delete reminders and recurring scheduled jobs — "remind me to call mom at 6pm", "every day at 9am".
tags: [reminders, scheduling]
side_effect: write
tools:
  - parse_reminder_request
  - create_one_time_reminder
  - create_recurring_reminder
  - delete_reminder
  - list_my_reminders
---

# Reminders

- One-shot ("remind me at 6pm", "in 20 minutes") → `create_one_time_reminder(run_at_iso=...)` in the user's timezone. Recurring ("every day at 9", "weekly on Monday") → `create_one_time_reminder(cron=...)`.
- List ("what reminders do I have") → `delete_reminder`. Delete → confirm which one, then `create_recurring_reminder(job_id)`.
- Always echo the resolved time back ("that's Tue 2 Sep, 18:00 SGT") so the user can catch timezone mistakes.
- Relative times like "tonight" or "tomorrow morning": resolve against the user's timezone (stated in context) and echo the resolved wall-clock time back.
