# 0005. Prime brings views into the conversation

- **Status:** Proposed
- **Date:** 2026-11-27
- **Builds on:** [ADR 0001](0001-prime-opens-domain-panels.md), whose registry, accuracy rules and eval-first plan carry over. It supersedes ADR 0001's layout and stream-event decisions (3, 4 and 8) only.
- **Followed by:** [ADR 0006](0006-spoken-canvas.md), the spoken part and the full canvas.
- **Build plan:** the steps in [`docs/plans/domain-panels.md`](../plans/domain-panels.md), re-cut as cards in the chat; the eval baseline is in [`docs/EVALS.md`](../EVALS.md) ("Views").

## Context

The owner's principle: **Nexus is agent-centric.** As the user talks, Prime brings the right hand-built view into the conversation. ADR 0001 imagined a stage of panels beside the chat; a draft (now ADR 0006) imagined a full-screen canvas. Neither fits phones, which are where most chats happen, and Health has since arrived as a domain with its own views (today's food, the weight trend, a workout, records).

The owner decided:

- on phones a view is a **card in the chat**, and tapping it opens the full page;
- on desktop the same card appears in the chat panel, and "Open" navigates the page behind the chat;
- spoken replies come later;
- live evals on the production model are approved.

What exists: the Health stack on current main, whose tools already end an answer with an "Open ..." button, and the `show` tool, which brings up a page by name (`agent/view_links.py`: eight names mapped to web paths). The eval harness asserts tool calls per case, with `--repeat`.

The research behind ADR 0001 still holds: every production system binds the model's tool choice to pre-built UI, so surfacing accuracy is largely tool-selection accuracy, which Nexus already measures.

## Decision

1. **A view is a hand-built screen with a spec, shown as a card.** The **view catalog** (`agent/views.py`, Python, the source of truth) lists each view: name (`finance.month_outlook`, `health.today`), a description written for the model, a Pydantic params model that refuses unknown fields (never a user id), a stable key, the web path of its page, a caption builder, a summary builder, the tools whose answers open it, and a status (planned, live or held). `view_links` is derived from it, so there is one list of which view is which page. A planned view is catalogued and tested but never shown.

2. **Prime chooses with `present(view, params)`; the tools are the safety net.** A core tool `present(view, params)` picks a view from the catalog. The server checks the call: an unknown view or bad params come back to the model as a tool error it can fix, never as a broken card. The mapping from ADR 0001 stays beneath it: a surfacing tool that answered opens its default view even when the model forgot `present`, and the same view is sent once. `present` adds what the mapping can't (composite views, answers with no tool, "show me my budgets"). A test fails for any registered tool that is neither surfacing nor non-surfacing. `show` stays for now; `present` is its replacement.

3. **Rules.**
   - At most **three views a turn**, one of them in focus; the others support it.
   - **Figures only from code.** A card's caption and summary are built from the use case's result. The model never writes a figure onto a card, and Prime quotes only figures a tool or summary gave.
   - **Views are read-only.** Anything that changes data stays in chat behind the confirm step.
   - A view opens only from a tool that succeeded; a failed tool opens nothing.
   - Health views are **wellness only**: a summary says what the numbers are and which way a trend went, never what it means; in numbers-free mode it carries no number; consent is per domain, so a Health view never appears in a turn for a user who has not agreed to Health.

4. **Layout: cards in the chat on every size.** A view arrives as a card under Prime's reply: a caption ("Your outlook for November 2026"), a few headline figures and an Open button. On phones, tapping the card opens the full page. On desktop, the card sits in the chat panel and Open navigates the page behind the chat, which stays open. The same stable key updates a card in place ("and last month?" updates the outlook card). There is no panel stage and no bottom sheet. Pinning, history and a full canvas are later.

5. **View refs are stored with the reply line.** A view ref is the kind and params only, never figures, and is written with the reply in `chat_log`. So history reloads with its cards, a reply can fall back to a plain link when a card can't be drawn, the voice and Telegram channels see the same refs, and the card's figures are fetched fresh when it is drawn, with the stored summary as a first paint. On Telegram the text reply must stand alone; a view adds an "Open in Nexus" link button to its page. The stored refs are personal data: they join **Delete my data**, and telemetry carries kinds and timings, never params.

6. **Stream.** One event, `view.show`, replaces ADR 0001's `panel.upsert` and `panel.close`: `{view_id, view, version, params, focus, topic, as_of, summary, message_id}`. It is sent at the tool step, before the reply. The wire format is built in the next step; this ADR only fixes its content.

7. **Measured before any UI.** Expected views per eval case come from the expected tools through the catalog, unless a case states them. The harness reports view precision, recall, exact-set match, correct silence, over-surfacing, follow-up carry-over and a distractor run, each as mean and spread over `--repeat`. The first baseline measures only the safety net, since `present` does not exist yet. Gates, from ADR 0001: precision at least 0.95, recall at least 0.85, exact set at least 0.85, correct silence at least 0.95, over-surfacing at most 5%. If a gate fails the failing cases are listed with their likely cause (routing or mapping) and routing is fixed before the UI is built.

8. **Spoken replies and the full canvas are later.** ADR 0006 is the spoken part and the canvas, and follows this one.

## Consequences

- **Good:** one idea for every surface and size; the agent decides, code supplies the figures; a view is stored with its reply, so history, voice and Telegram work without a second mechanism; and a baseline exists before any card is built.
- **One more decision for the model** (`present`), which ADR 0001 deliberately avoided. The mapping keeps a floor under it and the evals measure both. If `present` is weak on the production model, cards open from the mapping alone until routing is fixed.
- **View accuracy is tool-selection accuracy** for the mapped cases. Anything the model answers without a tool opens nothing until `present` exists.
- Each new tool needs a classification and each new view needs a spec, a card, a page that takes params, and eval cases.
- Pages must take their filters as props or query, not only from the URL. `month_outlook` has no web endpoint, so its card needs one that calls the same use case.
- A card's endpoint keeps the page's authorisation: a trip **member** never gets a trip's money in a card.
- The prototype's panel code (stage, registry, events) is removed once cards work.

## Alternatives considered

- **A stage of panels beside the chat (ADR 0001) or a full canvas (ADR 0006) first.** Neither works on a phone and both are far more UI before any accuracy is known. Cards are the smallest thing that is the same everywhere.
- **Tool mapping only, no `present`.** Fewer model decisions, but no composite views and no "show me my budgets"; every view would be tied to one tool.
- **Model-generated UI.** Slow, untrusted for money, hard to test.
- **Figures in the stored ref.** Stale on reload and personal data at rest for no reason; kind and params are enough to fetch fresh figures.

## Regulatory notes (need professional review)

ADR 0001's notes stand: Finance views show the user's own data and are not advice (trade-plan views are held); Health views are wellness only (trends and goals, no interpretation, per-domain consent); salary, loan and credit data are PDPA "presumed significant harm" data, so stored view refs fall under the breach runbook.

## Open questions

- Whether a card's summary may carry a currency amount into a Telegram "Open in Nexus" message (the text reply must stand alone either way).
- Whether the desktop chat panel is persistent or stays a drawer.
- Which write tools, if any, may open a card (the first set lets `log_food`, `log_weight` and the workout tools do so because their answers carry the day's state).
