# 0006. Nexus is a spoken canvas: the user talks, Prime answers aloud and composes the screen

- **Status:** Proposed
- **Date:** 2026-11-17 (drafted); renumbered 2026-11-27
- **Builds on:** [ADR 0005](0005-prime-views.md), which adopts `present`, the view catalog and the tool-to-view safety net for cards in the chat. This ADR was drafted as ADR 0002, before ADR 0005, and is renumbered unchanged except for this header. Where its decisions 3, 4, 5, 7 and 9 describe the view catalog, `present`, the safety net and the stream, ADR 0005 is the settled form. What stays here is the **spoken part** (decisions 1, 2, 6, 10 and 11), which follows ADR 0005, and the full canvas (decisions 7 and 8), which is later.
- **Build plan:** [`docs/plans/spoken-canvas.md`](../plans/spoken-canvas.md)

## Context

ADR 0001 built a chat column beside a stage of tab pages. The prototype (behind `PANELS_ENABLED`) works, but it is the existing app with a chat sidebar that opens pages. The owner wants something else: **talking is the main way in, and Prime decides what the screen shows**, from the conversation. The screen is built from **hand-built views** the owner adds to over time, never from model-generated UI.

What already exists:

- **Speech to text.** `POST /api/chat/voice` takes a recording, transcribes it through OpenRouter (`infra/speech/openrouter.py`, `openai/gpt-4o-mini-transcribe`) and runs the words as a typed turn. Nothing speaks back.
- **The stream.** `POST /api/chat/stream` sends `step`, `panel.upsert`, `replies` and `error`. The reply arrives whole at the end, not token by token.
- **Panel registry** (`agent/panels.py`): tool to panel kind, with every tool classified, and four panels on the web (month outlook, budgets, transactions, trip budget).
- **OpenRouter text to speech.** `POST /api/v1/audio/speech` is OpenAI-compatible and returns mp3 or 24 kHz PCM. Candidate models include `openai/gpt-4o-mini-tts-2025-12-15`, `mistralai/voxtral-mini-tts-2603` and `google/gemini-3.1-flash-tts-preview`, priced per input character.

"Voice" already means something in Nexus: the personality dials (`set_voice`, "How Nexus talks"). This ADR uses **speech**, **spoken** and **talk** for audio, and leaves "voice" to the personality.

## Decision

1. **Tap to talk, spoken replies, desktop first.** The user taps the talk button (or holds Space), speaks, and taps again (or releases). Prime answers aloud in one or two sentences and the canvas shows the detail. Tapping while Prime is speaking stops the speech and, if the turn is still running, stops the turn: the user can always interrupt. Typing stays available, and a mute switch turns spoken replies off (remembered per user). Always-listening, wake words and phones come later, not in this ADR.

2. **Speech runs through Nexus's own agent, not a speech-to-speech model.** The pipeline is speech to text, the existing agent loop with its tools, then text to speech, all through OpenRouter. Realtime speech models (OpenAI Realtime, Gemini Live) were considered and rejected: they would bypass the tools, the confirm step and the eval harness, which is where Nexus's accuracy comes from.

3. **Prime chooses the view with `present`.** A new core tool, `present(view, params, focus=True)`, picks a view from the **view catalog** and fills its params. The server checks the call against the catalog. A view name that doesn't exist, or bad params, comes back to the model as a tool error it can fix, never as a broken screen. Prime may present up to three views in a turn: one focus view and up to two supporting views.

4. **The tools Prime calls are the safety net.** ADR 0001's mapping from tools to views stays. If a turn calls a surfacing tool but not `present`, its default view opens. If `present` names the same view, the server sends it once. A cheap model that forgets `present` still shows the right thing for the common cases, and `present` adds what the mapping can't: composite views, no-tool answers, "show me my budget".

5. **The view catalog is hand-built, and figures always come from code.** A view has a Python spec (name, a description written for the model, a Pydantic params model, a stable key, the use case that fills it, and a code-built summary) and a React component. The canvas fetches a view's data from one endpoint, `GET /api/views/{view}`, which calls the same use case as the tool. The model never puts a figure on screen. Views are made for answers, not copied from tab pages: "can I afford Japan in March?" is one **affordability** view, not two pages side by side. New views are added to the catalog in code and become available to Prime through their spec.

6. **What is said and what is shown are split.** In a spoken turn Prime's reply is the spoken text: one or two sentences, no lists, no emoji, no tables (a spoken style in the prompt, separate from the personality dials, which still set tone). The canvas carries the detail. Every figure in a spoken reply must appear in a tool result or a presented view's summary from the same turn. The eval harness checks this (decision 10), because a wrong number spoken aloud is worse than a wrong number on screen.

7. **The canvas replaces the tabs as the way in.** Desktop is one full-screen canvas: the focus view in the centre, earlier views in a strip to bring back, captions of what was said and what Prime said, and the talk button with its state (idle, listening, transcribing, working with the step label, speaking). There is no tab bar. The existing pages stay reachable from a command menu (⌘K), and a view can link to its page. A focus view replaces the previous one unless the user pinned it. A follow-up ("and April?") updates the same view by its key.

8. **Views can act, behind the confirm step.** A write Prime proposes ("set dining to 400") shows as a **confirm card** on the canvas. The user says "yes" or taps Confirm. This uses the existing confirm step; nothing is written without it. ADR 0001's read-only rule is lifted for confirm cards only. Views themselves stay read-only in the first version.

9. **Stream protocol.** The `panel.*` events are renamed and extended:
   - `heard` `{text}`: the transcript, sent as soon as speech to text returns, so the caption shows before Prime has answered.
   - `view.show` `{view_id, view, version, params, focus, topic, as_of, summary, message_id}`: the same stable-id upsert as ADR 0001's `panel.upsert`, plus `focus` and a code-built `summary`.
   - `view.close` `{view_id}`.
   - `confirm` `{confirm_id, action, summary}`: a write waiting for the user.
   - `step`, `replies` and `error` stay. Spoken audio is not on the stream: the client sends each sentence of the reply to `POST /api/speech` and plays the audio in order, so muting, replay and the text-only stream all stay simple.

10. **Measured before it ships.** The eval harness gets expected views per case (from expected tools through the mapping, or stated), and reports view precision, recall, exact-set match and correct silence, as ADR 0001 planned. It adds: `present` validity (calls that the catalog refused), **spoken brevity** (at most two sentences and 45 words in a spoken turn, a proposal) and **spoken grounding** (every figure in the reply is in the turn's tool results or view summaries). The existing voice-clip evals (`evals/clips.py`) cover speech to text. Gates are in the build plan.

11. **Speech cost and privacy.** Text to speech is billed per character and joins `costs` as its own feature, with a daily character cap per user (a proposal: 20,000) and a smaller one for demo accounts. Audio is never stored or logged, and neither are transcripts in logs, as today. Spoken replies say figures aloud, so the mute switch is one tap and remembered.

## Consequences

- **Good:** the app feels like talking to someone who puts the right thing in front of you. Views are made for answers, so the owner can grow the product one view at a time. The accuracy rules from ADR 0001 (hand-built UI, figures from code, eval-first) carry over unchanged.
- **One more decision for the model.** `present` is what ADR 0001 avoided. The tool-to-view mapping keeps a floor under it, and the evals measure both. If `present` accuracy on the production model is poor, the canvas runs on the mapping alone until routing is fixed.
- **Latency is now felt.** A spoken turn waits for transcription, the agent, then speech. Views open at the tool step, before the reply, so the screen moves first. Speaking starts on the first sentence. Streaming the reply token by token is a later step that would let speech start before the reply is finished.
- **The panel code is renamed, not thrown away.** `agent/panels.py` becomes the view catalog, the four panels become views, and `PanelStage`, the docked chat column and `PANELS_ENABLED` are removed once the canvas works, behind a new `CANVAS_ENABLED` setting.
- **Tabs become secondary.** Dashboard and tab pages stay for now (Telegram's Mini App and phones still use them) but stop being the desktop home when the canvas is on.
- Each new tool still needs a classification, and each new view needs a spec, a component, an endpoint case and eval cases.
- The open views (ids, params, pinned) go back with each turn so "close that" and "and April?" resolve. They are personal data: a per-user table with row-level security, included in **Delete my data**.

## Alternatives considered

- **Speech-to-speech realtime models.** Lowest latency and most natural turn-taking, but they bypass Nexus's tools, confirm step and evals, and cost more per minute. Possible later as the speech layer only, if they can call Nexus's tools.
- **Model-generated UI** (the model writes components or a UI schema). Rejected again: slow, untrusted for money, hard to test. The catalog gets most of the flexibility with none of that.
- **Only the tool-to-view mapping, no `present`.** Fewer model decisions, but it can't compose (affordability), can't answer "show me", and ties every view to one tool.
- **A dedicated speech vendor** (ElevenLabs, Cartesia). More natural voices. The owner chose OpenRouter to keep one key and one bill; the speech adapter is a port, so a vendor can be swapped in later.
- **Always listening.** More magical, but it needs voice activity detection, echo cancellation and a privacy story. Tap to talk first.

## Regulatory notes (need professional review)

ADR 0001's notes stand (MAS advice line, HSA wellness-only, PDPA). Speech adds:

- **Spoken advice.** A sentence spoken by Nexus carries more weight than a table. The spoken style must stay factual ("you'd have about 1,400 left") and never advise products or trades. Trade-plan views stay held.
- **Overheard data.** Speaking salary or balances aloud is a disclosure risk in shared spaces. Mute is easy to reach, and a later setting may keep figures off speech entirely.

## Open questions

- Which OpenRouter speech model and voice. The plan has a listening test before one is picked.
- Should the canvas greet the user with a short briefing (bills due, a flight tomorrow) when it opens, spoken only on tap? Planned for Phase 4.
- When phones come, is the canvas the same app, or the Telegram Mini App with speech?
