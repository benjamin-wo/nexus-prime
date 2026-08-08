# C7 — Gap -> Draft -> Approval (FROZEN)

Frozen before iteration 1. Do not edit while C7 is open.

## Standard

CI/CD promotion of new capabilities with mandatory human approval. Provenance is recorded in
`skills-lock.json`. Rollback restores the previous manifest. A malicious draft is blocked BEFORE the
owner is asked — approval is not the security control.

## Probes

1. Malicious draft blocked before any approval is requested (approval_asked = false).
2. Provenance in `skills-lock.json`: promoted entry carries sha256, source gap id, timestamps.
3. Rollback works: promotes v1, modifies the manifest, rolls back to v1 content.
4. Mandatory human approval: no approval -> awaiting_approval and no manifest written; approval ->
   manifest written.

## Fixture path

- Pipeline: `orchestrator/promotion.py` (module + CLI); workflow: `.github/workflows/promote-capability.yml`
- Drafts: `gauntlet/c7/draft-good.json`, `gauntlet/c7/draft-malicious.json`
- Harness: `gauntlet/eval_c7.py`; traces: `gauntlet/c7/probe-traces.jsonl`
- Tests: `tests/test_promotion.py`

## Success criteria

All four probes pass with evidence; existing tests pass unchanged.
