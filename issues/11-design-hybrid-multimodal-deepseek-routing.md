# 11 - Design Hybrid Multimodal (Gemini) & Variable-Thinking (DeepSeek v4 Flash) Architecture

Status: resolved
Label: wayfinder:design
Parent: map.md

## Question

How should we configure environment variables in `core/config.py` and architect the LLM routing layer so that:
1. **Multimodal Input/Output Handling** uses **Google Gemini** (natively processing audio/voice notes, photos, documents, and rich output formatting).
2. **Agentic Orchestration & Subagents** use **DeepSeek v4 Flash** as the core reasoning engine.
3. **Variable Thinking Levels** are dynamically applied to DeepSeek v4 Flash based on the complexity of the task being performed?

## Answer & Specification

### 1. Environment & Configuration (`core/config.py` & `.env.example`)
- Replace single-provider dependence with explicit multi-model configuration:
  ```python
  class Settings(BaseSettings):
      google_api_key: Optional[str] = None       # For Gemini Multimodal I/O
      deepseek_api_key: Optional[str] = None     # For DeepSeek v4 Flash Agent Core
      deepseek_base_url: str = "https://api.deepseek.com/v1"
      openai_api_key: Optional[str] = None       # Optional fallback/compatibility
  ```

### 2. Task-Complexity Thinking Tiers (DeepSeek v4 Flash)
We categorize all agentic tasks into three **Thinking Levels** that control DeepSeek v4 Flash's reasoning depth (via `reasoning_effort` or reasoning token budgets):

| Complexity Tier | Thinking Level | Reasoning Tokens / Effort | Target Workloads in Nexus Prime |
| :--- | :--- | :--- | :--- |
| **Low Complexity** | `LOW` | 0–512 tokens (`"low"`) | Basic conversational greetings, 1-tap inline button callback handling, simple supervisor intent routing with clear keywords. |
| **Medium Complexity** | `MEDIUM` | 1024–2048 tokens (`"medium"`) | Standard domain subagents: Email category search & domain tracking, Expense extraction & duplicate checking, Recipe parsing, Route planning. |
| **High Complexity** | `HIGH` | 4096+ tokens (`"high"`) | Multi-step task decomposition, resolving ambiguous capability gaps in `general_subagent`, HITL conflict resolution, and complex constraint synthesis. |

### 3. Hybrid Multimodal I/O Pipeline (Gemini Flash + DeepSeek Core)
- **Input Interception (Gemini Flash)**:
  - When `app/webhook.py` receives a Telegram update with a voice note (`audio/ogg`) or image (`photo`), **Gemini Flash** (`gemini-2.5-flash`) is invoked to transcribe audio, describe images, and extract structured metadata from attachments.
  - The enriched textual and structured payload is passed to the **Supervisor** (running on DeepSeek v4 Flash).
- **Core Orchestration & Domain Execution (DeepSeek v4 Flash)**:
  - The Supervisor evaluates `intent_type` using `ThinkingLevel.LOW` or `ThinkingLevel.MEDIUM`.
  - Specialized domain subagents (`email`, `expenses`, `recipes`, `routes`) execute with `ThinkingLevel.MEDIUM`.
  - Informational fallback and capability gap analysis (`general_subagent`) execute with `ThinkingLevel.HIGH` to synthesize robust workarounds or alternative workflows.
- **Output Handling (Gemini Flash)**:
  - When a response requires multimodal formatting (e.g., visual cards, diagrams, or structured media exports), Gemini Flash formats the final response payload before sending to Telegram.

### 4. LLM Factory Pattern (`core/llm.py`)
- Implement a centralized LLM factory `get_llm(role: str, complexity: str = "MEDIUM")` that returns:
  - `ChatGoogleGenerativeAI(model="gemini-2.5-flash", ...)` when `role == "multimodal_io"`.
  - `ChatOpenAI(model="deepseek-chat", base_url=settings.deepseek_base_url, ...)` configured with appropriate thinking parameters when `role == "agent_core"`.
