# 04 - Multimodal Telegram Webhook & Inline Callback Architecture

Status: resolved
Type: grilling
Blocked by: 01

## Question

How should the FastAPI webhook endpoint format incoming `.ogg` audio bytes and `.jpg` receipt images for Gemini Flash / Kimi k3, and how should Telegram inline keyboard buttons (`[Confirm]` / `[Cancel]`) map to LangGraph `interrupt_before` resume checkpoints?

## Answer

1. **Multimodal Attachment Formatting**: Download Telegram voice notes (`.ogg`) and photo attachments (`.jpg`/`.png`) directly into memory (`io.BytesIO`) and construct standard LangChain `HumanMessage` Base64 content blocks (`{"type": "image_url", "image_url": {"url": "data:..."}}`). This enables native multimodal inference in Gemini Flash / Kimi k3 without temporary filesystem storage.
2. **Telegram Callback Query & Checkpoint Resumption**: Encode confirmation button actions compactly inside Telegram's 64-byte `callback_data` limit (`{"a": "confirm", "t": "chat_id"}`). The FastAPI webhook answers the callback query immediately and resumes the paused LangGraph checkpoint statelessly via `graph.ainvoke(Command(resume={"action": "confirm"}), config=...)`.
