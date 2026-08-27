---
name: email
description: Search the user's connected Gmail/Outlook for receipts, bills, bank alerts, or recent messages; provide mailbox connection links.
tags: [mail, inbox, receipts]
side_effect: read
tools:
  - search_my_email
  - get_email_connection_status
  - sweep_email_for_expenses
  - disconnect_email
---

# Email

- "check my email / latest email / did you see X's email" → `search_my_email` (latest=true for "newest", otherwise pass the query).
- Summarize from exactly the returned sender/subject/date lines. NEVER invent a sender, subject, or amount not present in the results.
- "connect my email / set up Gmail" or any email task failing because no mailbox is connected → `get_email_connection_status` and relay the links.
- Finding a receipt is an email search, not an expense log — only log via the expenses skill when the user asks to log it or an expense-scan flow produced it.
