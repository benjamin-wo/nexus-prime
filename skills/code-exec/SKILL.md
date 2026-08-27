---
name: code-exec
description: Run short Python snippets in an isolated sandbox for calculations, data crunching, spend-autopsy math.
tags: [code, sandbox, compute]
side_effect: write
tools:
  - run_python_code
---

# Code execution (kernel-gated)

- For non-trivial math or data processing the ledger tools can't do → `run_python_code`.
- The `code` argument is the ONLY executable input; pass user data via `data` (never concatenate user text into code).
- Keep snippets short; hard output limits apply. Never attempt network access from the sandbox.
