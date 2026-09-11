# Agent Framework Architecture (AGENT1A + AGENT1B)

**AGENT1A** = role/provider/budget definition + dry-run prompt building
(agent contracts, config resolution, prompt generation — no execution).
**AGENT1B** = the controlled execution layer on top: task lifecycle,
approval gate, provider adapters, branch/scope isolation, and PR
creation — still no auto-merge, still no automated production access.

## Flow (current — this is what's actually implemented, see GOVERNANCE.md)

```
GitHub Issue
     ↓
agent:approved label          (explicit human activation — Phase 25)
     ↓
Coordinator                    (classifies, never implements — task.agent
     ↓                          must be set explicitly in AGENT1B; a
     ↓                          free-text classifier is not implemented)
Specialist selection           (scripts/agent/select-agent.js)
     ↓
Provider/model/budget resolution (scripts/agent/providers.js — see
     ↓                            PROVIDERS.md for AUTOMATED/MANUAL_EXPORT/
     ↓                            DISABLED per provider)
Isolated branch (agent/<issue>-<agent>-<slug>)
     ↓
Specialist execution — AUTOMATED where a provider adapter reports
     ↓                  SUPPORTED and is configured for it (none are, by
     ↓                  default, in this repo — see PROVIDERS.md); MANUAL_EXPORT
     ↓                  otherwise: a human/external agent session pastes the
     ↓                  generated prompt into their own provider and returns a diff
Scope validation (scripts/agent/scope-check.js — allowed_files/forbidden_files)
     ↓
Tests (task-defined, or the specialist contract's default set)
     ↓
Reviewer Agent (verdicts, never implements — bounded one correction cycle)
     ↓
Docs Agent if required
     ↓
PR (scripts/agent/pr-body.js — structured summary, no secrets, no full prompt dump)
     ↓
Human merge (mandatory — no auto-merge exists anywhere in this pipeline)
```

AGENT1A alone builds everything up to and including "dry run." AGENT1B
adds the state machine, approval gate, provider adapters, scope
enforcement, run records, and PR body generation described below —
still stopping at MANUAL_EXPORT / human merge unless a provider is
explicitly configured AUTOMATED and its adapter reports SUPPORTED.

## Task lifecycle (AGENT1B, `scripts/agent/lifecycle.js`)

```
CREATED → CLASSIFIED → APPROVED → RUNNING → IMPLEMENTED → TESTING
  → REVIEWING → {DOCS_PENDING →} READY_FOR_PR → PR_OPEN → AWAITING_HUMAN → MERGED
```

Any state may move to `FAILED`, `BLOCKED`, or `CANCELLED`. `FAILED` may
re-enter `RUNNING` exactly once (bounded retry, `MAX_IMPLEMENTATION_ATTEMPTS=2`
enforced by the caller's loop, not the state machine itself).
`REVIEWING` may return to `RUNNING` for one correction cycle before a
second `NOT_MERGEABLE` verdict becomes `BLOCKED` (human intervention).
`BLOCKED`, `MERGED`, `CANCELLED` are terminal. No database — state lives
in the GitHub Issue (labels/comments) and run records under
`.agent-room/sessions/`.

## Issue labels (Phase 5)

| Label | Meaning |
|---|---|
| `agent:backend` / `agent:frontend` / `agent:qa` / `agent:performance` / `agent:infra` / `agent:research` / `agent:docs` | which specialist a human has assigned (Coordinator's free-text classification is not automated in AGENT1B — a human sets this) |
| `agent:approved` | explicit activation signal — required before `agent-task.yml` will plan the task (Phase 25) |
| `agent:running` | plan/execution in progress |
| `agent:review` | in the Reviewer step |
| `agent:blocked` | needs human intervention (scope/budget/provider/review block) |
| `agent:ready` | `READY_FOR_PR` / PR opened, awaiting human merge |
| `docs-required` | task's `docs_required` is `true` (or Reviewer determined it during `auto`) |
| `human-gate` | task touches something on GOVERNANCE.md's human-approval list |

Not a full label-per-state vocabulary by design (Phase 5: "do not create
dozens of labels") — the run record and issue comments carry the
fine-grained state.

## Agent roles and ownership

| Agent | Owns | Never |
|---|---|---|
| coordinator | classification, specialist selection | implementation |
| backend | FastAPI, DB helpers, API contracts, job lifecycle | frontend UX, deploy infra, scoring |
| frontend | Next.js/React, UI, frontend API integration | scoring, deploy infra |
| qa | Playwright, smoke/regression tests, fixtures | changing product behavior to pass tests |
| performance | profiling, benchmarking, targeted perf fixes | changing semantics for speed |
| infra | Oracle/Docker/Caddy, deploy workflows | live production execution (disabled in AGENT1A) |
| research | evidence analysis, methodology, reproducibility | production trading policy |
| docs | README/docs/runbooks, current-reality accuracy | implementation code |
| reviewer | mergeability verdict | implementation |

Full contracts: `agents/<name>.md`. Every role file declares the same
fields (NAME, MISSION, OWNS, MAY READ, MAY MODIFY, MUST NOT MODIFY,
token budgets, REQUIRED CONTEXT, EXPECTED DELIVERABLE, TEST EXPECTATIONS,
ESCALATION CONDITIONS, STOP CONDITION, REVIEW EXPECTATIONS) — see any
`agents/*.md` for the shared contract shape.

## Provider separation

`agents/*.md` never name a provider (no "You are Claude/Codex/Grok").
Provider + model + budget are resolved separately via
`config/agents.example.yaml` and `scripts/agent/select-agent.js`. See
`docs/agents/PROVIDERS.md`.

## Relationship to `.agent-room/`

This repo already has session-level agent conventions in `.agent-room/`
(`coordination/handoff-protocol.md`, `coordination/scope-boundaries.md`,
`coordination/session-log-format.md`, `guardrails.json`). AGENT1A does not
replace these — it adds a *role* layer on top. A specialist agent working
under this framework should still follow `.agent-room/coordination/*` for
handoff and logging, and respect `.agent-room/guardrails.json`'s protected
paths.

## Pipeline components

- `agents/*.md` — role contracts (this doc's table above)
- `config/agents.example.yaml` — provider/model/budget resolution
- `.agent-tasks/*.yaml` — task definitions (schema in USAGE.md)
- `scripts/agent/lib.js` — shared config/YAML-subset parsing helpers
- `scripts/agent/validate-agent-config.js` — config + role file validation
- `scripts/agent/validate-budget.js` — per-agent budget validation
- `scripts/agent/select-agent.js` — resolve an agent to provider/model/budget
- `scripts/agent/build-agent-prompt.js` — combine contract + task + budget into a prompt (dry run only)
- `.github/workflows/agent-validate.yml` — validate-only CI, safe during INFRA4

AGENT1B additions:

- `scripts/agent/lifecycle.js` — task state machine (states/transitions above)
- `scripts/agent/providers.js` — provider adapters (SUPPORTED/NOT_CONFIGURED/UNAVAILABLE) + execution-mode resolution (AUTOMATED/MANUAL_EXPORT/DISABLED/BLOCKED_PROVIDER)
- `scripts/agent/sanitize.js` — branch-name/task-id/path sanitization for untrusted Issue content
- `scripts/agent/scope-check.js` — validates actual changed files against `allowed_files`/`forbidden_files`
- `scripts/agent/run-record.js` — writes audit records to `.agent-room/sessions/`
- `scripts/agent/pr-body.js` — structured PR body template
- `scripts/agent/orchestrate-task.js` — the pipeline driver (`plan` and `apply` modes — see USAGE.md)
- `.github/workflows/agent-task.yml` — approval-gated plan-only workflow (Phase 24-26)
