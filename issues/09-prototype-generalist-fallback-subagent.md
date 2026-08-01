# 09 - Prototype Generalist Fallback Subagent & Refusal UX

Status: resolved
Label: wayfinder:prototype
Parent: 06-capability-gap-handling-map.md
Blocked by: 08-design-supervisor-fallback-intent-protocol.md

## Question

Can we prototype a `general_subagent` in `orchestrator/subagents.py` and test it against:
1. An unsupported informational prompt (e.g., "What is the capital of France?") -> Answered via general reasoning / search.
2. An unsupported transactional prompt (e.g., "Transfer $100 to Alice") -> Gracefully rejected with a list of available capabilities and an offer to log a feature request.

## Answer & Prototype Specification

1. **`general_subagent` Toolset (`orchestrator/subagents.py`)**:
   - Equip `general_subagent` with a lightweight **Web Search Tool** (search wrapper) and a **DateTime Calculator** (current date/time in user's `ZoneInfo` timezone) so it can accurately answer factual, temporal, and general reasoning questions.
2. **1-Tap Inline Refusal UX (`app/webhook.py`)**:
   - When an unsupported transactional prompt is refused by the supervisor, send a Telegram message:
     *"I don't currently have a capability plugin for that task. Here are the domains I can help you with: 📧 Email, 💰 Expenses, 🗺️ Routes, 🍳 Recipes."*
   - Attach an inline Telegram keyboard button:
     `[ + Log Feature Request (#tag) ]`
   - When the user taps the button, `webhook.py` callback handler invokes `log_capability_request(...)` in `core/audit.py` and edits the message to confirm: *"✅ Logged #tag to our feature wishlist!"*
