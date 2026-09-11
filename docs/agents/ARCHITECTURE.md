# AGENT1A Architecture

## Flow (target, not yet live — see GOVERNANCE.md)

```
GitHub Issue / manual dispatch
        ↓
Coordinator          (classifies, never implements)
        ↓
specialist agent      (backend/frontend/qa/performance/infra/research/docs)
        ↓
PR
        ↓
tests
        ↓
Reviewer Agent        (verdicts, never implements)
        ↓
Docs Agent if required
        ↓
Human merge
```

AGENT1A builds everything up to and including "dry run" — it does not wire
up live model calls or automatic PR creation. That's AGENT1B.

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
