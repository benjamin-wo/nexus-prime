# Nexus Prime Domain & Architecture Glossary

This document records the Ubiquitous Language and Architectural Seams for `nexus-prime` (a 3-Layer Personal Assistant Bot).

## Core Architectural Modules & Seams

### 1. Ingress Layer
- **TelegramIngress**: A deep adapter module (`app/ingress.py`) that encapsulates all Telegram Bot API concerns.
  - **Responsibilities**:
    - Verifies incoming webhook payloads and normalizes user/chat IDs.
    - Resolves or provisions the `UserProfile` in PostgreSQL.
    - Directly executes all deterministic slash commands (`/jobs`, `/timezone`, `/missing_capabilities`, `/run_now`) without invoking LangGraph.
    - Handles inline keyboard button callback resumption (`Command(resume=...)`) and telemetry feature request tagging (`log_req:<tag>`).
    - Normalizes conversational prompts and multimodal media attachments into a clean `AssistantState` dictionary before handing off across the seam to LangGraph.
  - **The Seam**: Isolates Telegram Bot API payload structure and administrative slash commands from the core domain AI orchestrator.
