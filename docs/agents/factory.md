# Software factory

Issues become specs, specs become draft PRs, and the owner merges. Two human gates.

```
 intake (issue, any author)
   |
   v
 needs-triage
   |
   v
 triage bot (triage.yml)
   |-- duplicate ---------> comment + `duplicate`
   |-- not enough info ---> <=3 questions + `needs-info` --(reporter replies)--> triage bot
   '-- spec comment ------> `spec-proposed` (+ `sensitive`)
                                 |
              GATE 1: owner reviews spec, adds `ready-for-agent`
                                 |
                                 v
 build bot (build.yml): branch claude/issue-N, tests first, draft PR "Fixes #N"
                                 |
              GATE 2: owner reads the draft, marks it ready for review
                                 |
                                 v
 CI (ci.yml) + review bot (review.yml: inline comments + verdict, never approves)
                                 |
                      owner merges
                                 |
                                 v
 auto-deploy after green CI (server.yml), rollback on failure -> "Deployed in" comment
```

Issues labelled `ops` are skipped by triage; they belong to `src/nexus/application/ops_tickets.py`.

## Who does what

| Actor | Workflow | Can do |
| --- | --- | --- |
| Triage bot | `triage.yml` | Read repo; `gh issue` view/comment/edit/list. Never `ready-for-agent`. |
| Build bot | `build.yml` | Edit code, run checks, push `claude/issue-N`, open a draft PR. Owner-triggered only. |
| Review bot | `review.yml` | Read PR; inline comments and one summary. Never approves or merges. |
| `@claude` | `claude.yml` | Ad hoc help, owner comments only. |
| Owner | - | Both gates, merge, secrets. |

Specs follow `docs/agents/spec-template.md`. `sensitive` risk (auth/security, migrations, money arithmetic, export/erasure, LLM prompt/tools, deploy/.github, secrets) is flagged on the PR and covered by `.github/CODEOWNERS`.

## Setup

- Repo secret `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (set one; the workflows pass both and the action uses whichever is present).
- Install the Claude GitHub app on the repo (needed for the app token used by build, review and claude).
- Create labels: `scripts/setup_labels.sh`.
- Protect `main` (require CI, require CODEOWNERS review for sensitive paths).

## Security rules

- Issue, PR and comment text is untrusted data, never instructions. Every prompt says so.
- Prompts forbid revealing secrets, env vars or real user data; posted examples use made-up data.
- Least-privilege `permissions:` per job; no `pull_request_target`; no checkout of PR code with secrets.
- Tools restricted with `--allowedTools` per job.
- Write-capable jobs (build, claude) run only when `github.event.sender.login == github.repository_owner`.
- Triage is the one job open to non-collaborators (`allowed_non_write_users: "*"`, the action's high-risk option). It is safe only because it has `issues: write`, `contents: read`, and read-only tools plus `gh issue`. Keep it that way.
- Review runs only on non-draft PRs from this repo, not forks.
- Concurrency is per issue/PR number; every job has `timeout-minutes`.
