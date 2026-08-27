---
name: reminders
description: Create, list, and delete reminders and recurring scheduled jobs — "remind me to call mom at 6pm", "every day at 9am".
tags: [reminders, scheduling]
side_effect: write
tools:
  - create_reminder
  - delete_reminder
  - list_my_reminders
---

# Reminders

- One-shot ("remind me at 6pm", "in 20 minutes") → `create_reminder(run_at_iso=...)` in the user's timezone. Recurring ("every day at 9", "weekly on Monday") → `create_reminder(cron=...)`.
- List ("what reminders do I have") → `list_my_reminders`. Delete → confirm which one, then `delete_reminder(job_id)`.
- Always echo the resolved time back ("that's Tue 2 Sep, 18:00 SGT") so the user can catch timezone mistakes.
- NOW in the user's timezone: ask `get_current_time_in_user_tz` if relative times like "tonight" are ambiguous.
