# 0004. Health's first app is Gym

- **Status:** Accepted
- **Date:** 2026-11-24
- **Builds on:** [ADR 0001](0001-prime-opens-domain-panels.md), which reserves Health as a wellness-only domain with consent per domain

## Context

ADR 0001 reserved **Health (wellness only)**: trends and goals, never medical interpretations, with consent given per domain. Health has no department yet. The owner approved adding a Gym app as its first one: a place to plan, log and review strength training, driven by the same chat, voice and Telegram surfaces as the rest of Nexus.

A gym app needs an exercise catalogue with text and pictures, and a body map. Writing and drawing those from nothing is a lot of work, so the licences of any source matter.

## Decision

1. **Health's first app is Gym.** Version 1 includes:
   - an **exercise library** with a muscle body map;
   - **routines**: ordered slots, each with an exercise, a target of sets × reps or a time, and rest seconds; and either a weekly plan or a rotation (A, B, C…);
   - a **workout session**: weights prefilled from last time, a rest timer, warm-up or working sets, optional RPE, personal records (PRs) detected in code with an estimated one-rep max (1RM) by the Epley formula, and undo;
   - **history and progress**: best set, estimated 1RM trend, and weekly volume per muscle;
   - **Prime tools** to log sets by chat, voice or Telegram ("bench 3x5 at 80") behind a confirm card, and to answer questions such as "last Monday?", "squat PR?" and "today's workout?";
   - a **coach** (below).
2. **The coach proposes; it never applies.**
   - Prime drafts a routine plan from the user's goals, days per week, equipment and experience. The output is a structured schema validated in code, and unknown exercise ids are rejected. It is shown as a confirm card before anything is saved.
   - After a session it may propose small changes (progressive overload, a deload) from numbers computed in code. These are always proposals, never automatic.
   - If the user mentions pain or injury, the reply is to see a qualified professional, with no programming advice.
   This keeps Gym on the wellness side of the HSA line drawn in ADR 0001.
3. **Figures always come from code.** Volumes, PRs, estimated 1RMs and trends are computed by service code, as everywhere else in Nexus. The model chooses tools and words, not numbers.
4. **Off by default.** Health appears only when the `show_health` menu flag is on, and it needs the per-domain health consent. The bottom bar keeps its five-item maximum (see DESIGN.md).
5. **Data.** A shared `exercises` catalogue, and user-owned routines, training plans, workouts and sets. User-owned tables are under row-level security and are covered by erasure and export. The set `kind` field (warm-up, working, and others later) leaves room for features not in version 1.
6. **Licensing.**
   - **openGym** (github.com/DuarteSantos8/openGym) was a UX reference only. Its code and its own catalogue text are AGPL-3.0, and its exercise media are proprietary (Gym visual). Nothing is copied from it.
   - **Exercise text and photos** come from yuhonas/free-exercise-db (Unlicense, public domain), pinned to one commit.
   - **Body-map outlines** come from melihcolpan/MuscleMap (MIT), converted from Swift path data to TypeScript.
   - The required notices are in [`NOTICE.md`](../../NOTICE.md).
7. **Out of version 1:** body weight, custom exercises and media, plate math, gym or equipment profiles, Strong and Hevy import, a watch app, and the superset and drop-set UI.

## Consequences

- **Good:** a useful first Health app with no medical claims, with sources whose licences allow use in this repo.
- **The coach's limits are part of the product.** Validation in code means a bad model answer cannot save an exercise that does not exist, and a proposal never changes a routine without the user's confirmation.
- **Health data is sensitive.** Consent per domain, off by default, row-level security, erasure and export all apply from the first release.
- **Attribution has to be kept.** The pinned free-exercise-db commit is recorded in `scripts/import_free_exercise_db.py`, and the MuscleMap licence text stays in `NOTICE.md`.
- **No exercise animations.** The catalogue has photos and text only. Paid animations can be added later.
- Features left out of version 1 can be added later without a schema change where the `kind` field covers them.

## Alternatives considered

- **Forking openGym.** AGPL-3.0 would put this repo under the same licence, its media are proprietary, and it is a separate stack from this one.
- **wger.** Its code is AGPL and its exercise data is CC-BY-SA, which brings share-alike terms to the catalogue.
- **Licensing Gym visual animations.** Paid. It can come later if the photos are not enough.
