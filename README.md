# Nexus Prime — Personal Assistant Telegram Bot


A high-performance, single-user **Personal Assistant Telegram Bot** deployed on **Railway** with built-in **multi-user extensibility** from day one. The assistant orchestrates diverse daily tasks—including email expense tracking, route planning, grocery/recipe management, and proactive reminders—through a **3-Layer Plugin Architecture** powered by **LangGraph multi-agent orchestration** and **Gemini Flash / Kimi k3 native multimodal inference**.

## 3-Layer Architecture

1. **Layer 1: Core (`core/`)**:
   - `core/db.py`: AsyncSQLModel + `asyncpg` PostgreSQL engine (`pool_size=5, max_overflow=10`) with automatic SQLite fallback for local development.
   - `core/vault.py`: Symmetric authenticated encryption (`Fernet` / AES-256-GCM) keyed by `ENCRYPTION_KEY` for securing OAuth tokens.
   - `core/scheduler.py`: In-process `APScheduler` engine bound to FastAPI's `lifespan` manager, configured with `misfire_grace_time=3600`, `coalesce=True`, dynamic IANA timezone recalculation, and instant testing triggers (`/run_now`).
   - `core/audit.py`: Background LLM-as-a-Judge quality observability engine evaluating faithfulness and routing efficiency.
   - `core/shared_tools/`: Date/time parsing, coordinate resolver, and global email sender preset library (`email_presets.py`).
2. **Layer 2: Capability Plugins (`capabilities/`)**:
   - `email`: Gmail API integration, smart category queries, `-label:Assistant/Processed` labeling, and bank domain auto-discovery.
   - `expenses`: Pydantic expense extraction, 2-layer deduplication, and Human-in-the-Loop (`confidence < 0.8`) inline confirmation.
   - `routes`: Transit and driving route planning.
   - `recipes`: Recipe scraping and grocery item synchronization (`GroceryItem`).
3. **Layer 3: Orchestration (`orchestrator/`)**:
   - LangGraph multi-agent routing using `Command(goto=...)` subgraph handoffs and `interrupt()` / `Command(resume=...)` for 1-tap inline keyboards (`[✅ Confirm]`, `[✏️ Edit]`, `[❌ Ignore]`).
   - Persistent `thread_id = str(chat_id)` memory with an automatic summarization hook when conversations exceed 25 messages.

## Running Tests

Run the full async pytest suite:

```bash
pytest tests/ -v
```

## Running Locally

Set up environment variables by copying `.env.example`:

```bash
cp .env.example .env
```

Run the FastAPI Uvicorn server locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Documentation & Architecture Specs

- **v1.0 Core Architecture RFC**: [spec.md](file:///Users/benjaminwo/Documents/agent-learn/spec.md)
- **v2.0 Capability-Gap Handling & Telemetry RFC**: [spec-capability-gaps.md](file:///Users/benjaminwo/Documents/agent-learn/spec-capability-gaps.md)
