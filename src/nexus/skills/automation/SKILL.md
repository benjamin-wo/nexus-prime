---
name: automation
description: Logging expenses automatically from email, only when the user asks how to automate logging.
tools: [connect_email, email_status]
---
# Automatic logging

Only use this when the user asks, e.g. "can you log my expenses automatically?",
"how do I stop typing every expense?", "can you read my receipts from email?". Never
suggest it on your own.

## Connecting Gmail
- Explain in two or three short lines: Nexus reads receipt-like emails (receipts,
  invoices, orders, card alerts) and asks before logging each one. It never logs
  anything without a Confirm.
- Then call `connect_email`. It returns a one-time button that works for 10 minutes.
- Warn them once, plainly: Google will say Nexus isn't verified because it's a private
  app. They tap Advanced, then Go to Nexus, then Allow.
- After they connect, Nexus looks back 30 days and messages them about what it finds.

## Other mail
- Outlook, iCloud or work email can't be connected yet. They can still photograph
  receipts, or type expenses as usual.

## Is it working?
- "is email working?", "why wasn't my Grab receipt logged?": `email_status`, then point
  them to the Email page in the web app, which lists every email checked and what
  happened to it (logged, waiting, not a receipt, no amount found, already logged).
- To disconnect, they use the Email page.
