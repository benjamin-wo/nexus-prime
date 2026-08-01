# 02 - Email Capability & Gmail API Integration

Status: resolved
Type: grilling

## Question

What exact Gmail API search queries, OAuth scope/token refresh flow, and Pydantic extraction schema should we specify for `capabilities/email` to guarantee reliable bank expense parsing without prompt overflow?

## Answer

1. **Authentication & Scopes**: Use Google OAuth 2.0 with an encrypted refresh token in PostgreSQL. Require `gmail.readonly` (to search/read) and `gmail.modify` (to tag processed emails).
2. **Search & Deduplication**: Use a zero-friction smart query (`(category:primary OR category:updates) + financial keywords -label:Assistant/Processed newer_than:7d`), combined with global bank presets (`email_presets.py`) and auto-discovery of user bank domains into `user_profile.tracked_banks`. Use 2-layer deduplication: Gmail label `-label:Assistant/Processed` and PostgreSQL `UNIQUE(source_message_id)`.
3. **Extraction & Ambiguity Handling**: Use a strict Pydantic `ExtractedExpense` schema with a `confidence` score (0.0 to 1.0) and `needs_clarification` boolean. High-confidence extractions log silently; ambiguous extractions send an interactive Telegram message with Inline Keyboard buttons (`[✅ Confirm]` / `[✏️ Edit]` / `[❌ Ignore]`).
