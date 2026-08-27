---
name: bug-logging
description: Log bugs the user notices ("log it as a bug", "there's an issue with the cockpit") into the GitHub issue backlog.
tags: [bug, issue]
side_effect: write
tools:
  - log_bug_report
---

# Bug logging

- When the user reports something broken and asks to log it → `log_bug_report` with their own words (strip the "can you log it as a bug" framing).
- Confirm with the issue URL when GitHub sync is configured; otherwise confirm it was recorded locally.
- If the user is just describing a problem without asking to log it, acknowledge and ask if they want it filed.
