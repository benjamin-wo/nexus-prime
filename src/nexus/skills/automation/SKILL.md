---
name: automation
description: Logging expenses automatically from email, only when the user asks how to automate logging.
tools: [connect_email, forward_email, test_email_setup, email_status]
---
# Automatic logging

Only use this when the user asks, e.g. "can you log my expenses automatically?",
"how do I stop typing every expense?", "can you read my receipts from email?". Never
suggest it on your own.

First ask which email they use, unless they said. Then explain in two or three short
lines: Nexus reads receipt-like emails (receipts, invoices, orders, card alerts) and
asks before logging each one. It never logs anything without a Confirm.

## Gmail: connect it
- Call `connect_email`. It returns a one-time button that works for 10 minutes.
- Warn them once, plainly: Google will say Nexus isn't verified because it's a private
  app. They tap Advanced, then Go to Nexus, then Allow.
- After they connect, Nexus looks back 30 days and messages them about what it finds.
- If connecting Gmail isn't available, or they'd rather not sign in, forwarding works
  for Gmail too.

## Outlook, iCloud, Yahoo, work email: forward to Nexus
- Call `forward_email` with their provider. It gives them their own Nexus address and
  the steps for a forwarding rule that only sends receipts. Pass the steps on as they
  are, short and numbered.
- They can also forward any single receipt by hand, with no rule at all.
- Work email may block forwarding outside the company; forwarding by hand still works.
- If their provider sends a confirmation to the Nexus address (Gmail does), Nexus
  passes the code and link on to them in this chat.
- Finish by suggesting they test it: `test_email_setup`.

## Is it working?
- "test my email setup", "is forwarding working?": `test_email_setup`. It tells them
  what test email to send; Nexus confirms here when it arrives.
- "is email working?", "why wasn't my Grab receipt logged?", "what should my filter
  include?": `email_status`. It lists which senders sent receipts and which sent other
  mail, so they know what to keep in or leave out of a filter. Then point them to the
  Email page in the web app, which lists every email checked and what happened to it.
- To disconnect, they use the Email page.
