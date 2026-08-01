# 10 - Design Capability Demand Telemetry Loop (`CapabilityRequestLog`)

Status: resolved
Label: wayfinder:grilling
Parent: 06-capability-gap-handling-map.md
Blocked by: 08-design-supervisor-fallback-intent-protocol.md

## Question

How should we structure the `CapabilityRequestLog` table in `core/models.py` and the telemetry logging helper in `core/audit.py` (or a dedicated `core/telemetry.py`) so that:
1. Whenever a user asks for an unsupported capability (whether an informational query that falls back to `general_subagent` OR an unsupported transactional action refused by guardrails), an entry is automatically persisted with `user_id`, `requested_task`, `intent_type`, `missing_capability_tags` (e.g., `["calendar", "smart_home"]`), and `timestamp`.
2. A new admin command or analytics endpoint `/missing_capabilities` aggregates these records to produce a data-driven leaderboard of requested features for the next version release?

## Answer & Specification

1. **Schema & Helper Placement**:
   - Define `CapabilityRequestLog(SQLModel, table=True)` in `core/models.py` with fields: `id: Optional[int]`, `user_id: int`, `requested_task: str`, `intent_type: str` (`"unsupported_transaction"` vs `"informational_fallback"`), `missing_capability_tags: str` (comma-separated or JSON string of tags), and `created_at: datetime`.
   - Place `async def log_capability_request(...)` in `core/audit.py` alongside `QualityAuditLog` to centralize all LLM-assisted audit and telemetry logging.
2. **Railway Deployment & Log Access Patterns**:
   - **Multi-Tenant vs. Single-Tenant Storage**: Each Railway PostgreSQL database stores the logs for its deployment. In multi-tenant mode, demand across all users is aggregated in one DB; in single-tenant (self-hosted) mode, each user's instance independently stores their personal feature wishlist.
   - **How to Access on Railway**:
     - **In-Chat Telegram Command**: Typing `/missing_capabilities` in chat returns a ranked Top-N Leaderboard showing tag frequency and sample prompts (e.g., `1. #calendar (14x) - e.g. "schedule a meeting"`).
     - **Direct DB Query**: Developers can also inspect the logs via Railway's built-in PostgreSQL Data Explorer or CLI (`railway run psql`).
