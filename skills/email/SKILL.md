---
name: email
description: Search the user's connected Gmail/Outlook for receipts, bills, bank alerts, or recent messages; connect or log in to a mailbox (Gmail/Outlook OAuth links); provide mailbox connection links.
tags: [mail, inbox, receipts]
side_effect: read
tools:
  - search_my_email
  - get_email_connection_status
  - sweep_email_for_expenses
  - disconnect_email
  - update_email_presets
  - get_email_presets
---

# Email

- "check my email / latest email / did you see X's email" → `search_my_email` (latest=true for "newest", otherwise pass the query).
- Summarize from exactly the returned sender/subject/date lines. NEVER invent a sender, subject, or amount not present in the results.
- **Mailbox login/connection is YOUR job — always route it through the tool.** "connect my email / set up Gmail / link Gmail / log in to Gmail / why can't you see my email" — or ANY email task failing because a mailbox isn't connected — → call `get_email_connection_status`, then relay its links verbatim. The tool output already contains the user's personalized one-time URL (e.g. `https://…/auth/gmail?user_id=<their id>`); do NOT invent or reformat the URL, and do not answer from memory.
- When relaying a connection link, also tell the user: open it in a browser (desktop or phone), sign in with the account that receives their receipts, grant BOTH requested permissions, and if Google shows a "hasn't verified this app" warning, choose Advanced → Go to (app name). The link only works in a browser — Telegram's in-app webview may block it, so advise opening it outside the chat if it fails there.
- After the user says they've connected (or on the next email task), re-check with `get_email_connection_status` to confirm, then retry the original request.
- Finding a receipt is an email search, not an expense log — only log via the expenses skill when the user asks to log it or an expense-scan flow produced it.
- The `sweep_email_for_expenses` tool runs periodically on a schedule. It uses a **Jev** classifier (OpenRouter Decisions API, model configured via `JEV_MODEL`) as a cheap pre-filter, then the chat model extracts a ≤50-word `description` stored in the transaction `notes`. The LLM's `is_transaction` flag is the final gate — non-transaction emails (promotions, newsletters, statements) are silently skipped and tagged as processed.
