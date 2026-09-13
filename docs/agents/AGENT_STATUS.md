# Agent Status

**Keep this current.** Any future PR that changes agent wiring (adds,
removes, or changes how a role is invoked) must update this doc in the
same PR — it is not optional follow-up. A role/script/workflow file
existing is not evidence it runs; only a run ID, a log line, or a
reproducible manual invocation with real output counts as evidence.
(FORTRESS-NEXT Epic 19's Docs Agent, once proven beyond advisory-only, is
a natural future candidate to enforce this doc staying current — not
implemented yet.)

Last updated: 2026-09-13, FORTRESS-NEXT Cleanup Pass.

## The 9 defined roles

| Role | Status | Invoking file | Last verified evidence |
|---|---|---|---|
| Coordinator | **WIRED** (planning only) | `.github/workflows/agent-pipeline.yml` step "Coordinator classification and provider resolution" → `scripts/agent/agent.js issue-plan` | 2026-09-13: confirmed by reading the workflow step directly; classifies an approved issue and resolves a provider, does not itself write code |
| Reviewer | **WIRED**, real gap found | Same workflow, step "Scope, tests, eval, review, docs, and PR gates" → `scripts/agent/reviewer-evidence.js` | 2026-09-13, FORTRESS-NEXT Epic 20: `node --test scripts/agent/reviewer-evidence-gap.test.js` — a synthetic fixture reintroducing PR #67's bug class (core-logic file changed, no test file changed) returns `{"verdict":"MERGEABLE","findings":[]}`. Wired and invoked, but its checks (`changed_files` non-empty, tests passed, eval passed) do not catch a missing regression test. Fix proposed, not yet implemented — see PR for Epic 20. |
| Docs | **WIRED**, advisory only | Same workflow, same step → `scripts/agent/docs-evidence.js` | 2026-09-13, FORTRESS-NEXT Epic 19: `node --test scripts/agent/docs-evidence.test.js` — replayed PR #21's real changed-file list against a `git worktree` checkout of `docs/` from immediately before PR #21 merged; correctly flags `docs/research/REAL_VALIDATION_RESULTS.md`. Advisory only — posts one issue comment, never blocks `scripts/agent/agent.js auto-gates`. |
| Backend | **NOT WIRED** (intentional) | — (`agents/backend.md` exists; loadable via `orchestrate-task.js` with an explicit `task.agent: backend`, but nothing invokes that autonomously) | Confirmed via `grep -rn "orchestrate-task" .github/workflows/` → no matches |
| Frontend | **NOT WIRED** (intentional) | — (same as Backend) | Same grep, no matches |
| QA | **NOT WIRED** (intentional) | — (same as Backend) | Same grep, no matches |
| Performance | **NOT WIRED** (intentional) | — (same as Backend) | Same grep, no matches |
| Infra | **NOT WIRED** (intentional) | — (same as Backend) | Same grep, no matches |
| Research | **NOT WIRED** (intentional) | — (same as Backend) | Same grep, no matches |

**Agent-wiring count: 3 of 9 roles wired** — Coordinator (planning only),
Reviewer (wired, real gap found and proposed-not-fixed via Epic 20), Docs
(newly wired via Epic 19, advisory only). 6 remain intentionally not
wired: Backend, Frontend, QA, Performance, Infra, Research. This is a
deliberate scope boundary (FORTRESS-NEXT's own ground rules: "wires up
exactly ONE [role] — the other six stay untouched"), not an oversight —
do not silently wire any of the six as a side effect of an unrelated
change.

## How to verify wiring yourself

- **A role is wired** only if a `.github/workflows/*.yml` step actually
  invokes its script/module — check with
  `grep -rn "<role-invoking-script>" .github/workflows/`.
- **A role's check actually catches something** only if you can point to
  a test or reproduction that exercises a real failure case and shows the
  literal output — not "the code path exists" or "it was invoked once
  without erroring."
- `scripts/agent/validate-agent-config.js` only confirms all 9
  `agents/*.md` files exist and the config is structurally valid — it
  says nothing about whether any role's checks are invoked or effective.
