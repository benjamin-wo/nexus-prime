# Wayfinder Map: Telegram Personal Assistant Bot Architecture Spec (RFC)

## Destination

A Complete Technical & Functional Architecture Spec (RFC) detailing the bot's extensible 3-layer plugin architecture, LangGraph supervisor-subagent orchestration, Railway PostgreSQL storage, multimodal Telegram webhook I/O, and proactive APScheduler/timezone engine, ready for engineering execution.

## Notes

- **Hosting & Scope**: Single-User Architecture with Multi-User Extensibility (`user_id` scoped data models and modular auth/credentials from day one), deployed on Railway.
- **Orchestration**: Python + LangGraph Supervisor-Subagent Multi-Agent Architecture (`create_agent`, Top-level Supervisor delegating to specialized domain Subagents).
- **Storage & Memory**: Railway Managed PostgreSQL (`PostgresSaver` + SQLModel/SQLAlchemy + `pgvector`).
- **Telegram I/O**: `python-telegram-bot` + Railway Webhook (via FastAPI) + Gemini Flash / Kimi k3 Native Multimodal Support (direct audio/image ingestion).
- **Plugin Architecture**: 3-Layer Architecture (`core/shared_tools` + `capabilities/` plugins + `orchestrator/` Supervisor) with an encrypted credential vault in Postgres.
- **Proactive Scheduling**: `APScheduler` in-process + Conversational Scheduling (`schedule_proactive_task`) + `/run_now` / Dry-Run Testing Engine + Dynamic IANA Timezone Adaptation.

## Decisions so far

<!-- the index — one line per closed ticket: enough to judge relevance, then zoom the link for the detail the ticket holds -->

- [01 - Core Supervisor & Capability Handoff Protocol](file:///Users/benjaminwo/Documents/agent-learn/.scratch/telegram-assistant-bot/issues/01-core-supervisor-protocol.md) — Subgraph handoff via `Command(goto=...)`, HITL confirmations via `interrupt()` + Telegram Inline Buttons, and persistent `thread_id` sessions with automatic pruning.
- [02 - Email Capability & Gmail API Integration](file:///Users/benjaminwo/Documents/agent-learn/.scratch/telegram-assistant-bot/issues/02-email-capability-and-gmail-api.md) — Google OAuth 2.0 with zero-friction smart category search + auto-discovery of tracked bank domains, 2-layer deduplication (`-label:Assistant/Processed` and DB unique index), and Pydantic schema with HITL Telegram clarification on low confidence.
- [03 - Database Schema & Credential Encryption](file:///Users/benjaminwo/Documents/agent-learn/.scratch/telegram-assistant-bot/issues/03-database-schema-and-encryption.md) — Fully user-scoped SQLModel tables (`user_id` foreign keys), symmetric authenticated encryption (`Fernet` / AES-256-GCM via Railway `ENCRYPTION_KEY`), and AsyncSQLModel with `asyncpg` driver and connection pooling.
- [04 - Multimodal Telegram Webhook & Inline Callback Architecture](file:///Users/benjaminwo/Documents/agent-learn/.scratch/telegram-assistant-bot/issues/04-multimodal-telegram-webhook.md) — In-memory Base64 data-URI content blocks for native multimodal processing without disk I/O, and compact 64-byte JSON callback payload for stateless LangGraph checkpoint resumption.
- [05 - Proactive Scheduler & Dynamic Timezone Adaptation Protocol](file:///Users/benjaminwo/Documents/agent-learn/.scratch/telegram-assistant-bot/issues/05-proactive-scheduler-and-timezone.md) — Dynamic Postgres-backed `ScheduledJob` table, 5-Pillar Guardrail System (`lifespan` hook, `misfire_grace_time=3600`, `tzdata` ZoneInfo, dual-registration watchdog, `/run_now`), and dynamic IANA timezone adaptation.

## Not yet specified

- Detailed implementation of individual capability tools (e.g., specific Google Maps APIs for Route Planning, recipe scraping site parsers).
- End-to-end integration test suite and CI/CD pipeline on Railway.
- Future multi-tenant user onboarding flow and Stripe/billing integration.

## Out of scope

- Multi-tenant user login web UI or OAuth callback portal (scope is Telegram-first, single-user with multi-user-ready data models).
- Custom speech-to-text or OCR training (we use Gemini Flash / Kimi k3 native multimodal input).
