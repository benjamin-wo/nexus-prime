# C1 — Manifest Schema + 4 Migrations (FROZEN)

Frozen before iteration 1. Do not edit while C1 is open.

## Standard

MCP tool definitions, Anthropic `SKILL.md` frontmatter. A stranger with only the manifest routes correctly;
descriptions in the user's phrasing. Each manifest declares:

- `id`
- retrieval-facing `description` (user phrasing, no class names, no module paths)
- typed `input_schema` / output types
- `side_effect` class: `read | write | spend | irreversible`
- `tags` (multi-valued, free-form)
- `preconditions`
- `cost_hint`

Tags are multi-valued and free-form. The manager set is **derived** from manifests and declared nowhere
(no manager enum, no manager class, no manager node).

## Probes

1. 4 manifests complete (email, expenses, routes, recipes; reminders/general additionally allowed).
2. Blind-route 15 replay messages with ONLY manifest content; >= 13 correct.
3. No class names or module paths anywhere in manifest content (loader rejects them).
4. Adding manager `home` is data-only: no enum, class, node, prompt or existing-test edit; demonstrate end to end.
5. `[life, finance]` accepted without arbitration (no conflict error).
6. A tag in one manifest warns at load.

## Fixtures

- Blind-route corpus: `gauntlet/c1/blind-route-15.jsonl` (15 rows from the frozen replay set).
- Probe traces: `gauntlet/c1/probe-traces.jsonl`.
- Loader: `capabilities/registry.py`; manifests: `capabilities/manifests/*.yaml`; tag policy: `config/tag-policy.yaml`.

## Success criteria

All six probes pass with evidence. Existing tests pass unchanged. Every claim carries a trace or measurement.
