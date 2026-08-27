---
name: whiteboard-planning
description: Planning boards for trips, events, projects — "plan a trip to Bali 3rd-6th Sept", "what's on my Tokyo board", "pin this to my board".
tags: [planning, whiteboard, trip]
side_effect: write
tools:
  - list_my_boards
  - summarize_board
  - new_board
  - pin_to_board
---

# Whiteboard planning

- A plan statement with destination/dates/details → decompose it YOURSELF into cards: `new_board` (if none matches) then `pin_to_board` per entity (hotel, flight, activity, booking status). Echo each card added.
- Follow-ups on an active plan ("and add a beach day") → `pin_to_board` to the last-touched board (the tools track it).
- "what's on my X board" → `summarize_board(board_ref=X)`. "my boards" → `list_my_boards`.
- Ask at most ONE follow-up question when a critical detail (dates, destination) is missing; otherwise build with what you have and mark unknowns as 💭 Idea.
- Research gaps: use the web-research skill, then pin findings as a Research note.
