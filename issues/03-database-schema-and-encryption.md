# 03 - Database Schema & Credential Encryption

Status: resolved
Type: grilling

## Question

What exact SQLModel database tables (`user_profile`, `expense_transactions`, `grocery_items`, `user_credentials`) and field types should be defined in Postgres, and how should user OAuth tokens be encrypted at rest?

## Answer

1. **Table Design & Scoping**: Use fully user-scoped SQLModel tables (`UserProfile`, `ExpenseTransaction`, `GroceryItem`, `UserCredential`) with an explicit `user_id: int` indexed column and foreign keys to `UserProfile.user_id`. This ensures zero schema migrations are needed for future multi-user support.
2. **Credential Encryption**: Protect OAuth tokens and secrets in `UserCredential.encrypted_token_payload` using symmetric authenticated encryption (`Fernet` / AES-256-GCM via Python's `cryptography` library) keyed by a Railway runtime `ENCRYPTION_KEY` secret.
3. **Async Connection & ORM Engine**: Connect to Railway Managed PostgreSQL using AsyncSQLModel with the `asyncpg` driver (`postgresql+asyncpg://`) and an asynchronous connection pool (`pool_size=5, max_overflow=10`, `pool_pre_ping=True`) to prevent event-loop blocking.
