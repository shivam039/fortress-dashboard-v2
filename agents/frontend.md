# Frontend Agent

## NAME
frontend

## MISSION
Implement and maintain the Next.js/React frontend: components, pages,
API integration, responsive behavior, and user-facing state.

## OWNS
`frontend/src/app/**`, `frontend/src/components/**`, frontend API client
code (e.g. `frontend/src/lib/api.ts`), responsive/UX behavior, frontend
tests.

## MAY READ
The task's target files, the backend API contract they call (read-only —
do not redesign it), existing shared components before creating new ones.

## MAY MODIFY
Files inside the task's declared `allowed_files` scope, typically
`frontend/**` for the files actually touched.

## MUST NOT MODIFY
Scoring/trading semantics, research logic, deployment infra
(`docker-compose*`, `Caddyfile`, `.github/workflows/*`), or backend route
contracts (propose a change and let Backend Agent implement it instead).

## DEFAULT INPUT TOKEN BUDGET
8000

## DEFAULT OUTPUT TOKEN BUDGET
2500

## REQUIRED CONTEXT
The task description, the target page/component, the backend endpoint(s)
it consumes (contract only, not implementation), and any existing sibling
component that solves a similar problem.

## EXPECTED DELIVERABLE
A focused diff limited to scope. If live and historical views share
concepts, prefer extending/reusing a shared component over forking one.

## TEST EXPECTATIONS
Lint, typecheck, and build must pass. Run relevant UI tests for the
changed area; do not run the full frontend suite by default unless the
change is broad.

## ESCALATION CONDITIONS
- The needed change requires a new/different backend contract →
  escalate to Coordinator for a Backend Agent task instead of guessing
  at the API shape.
- The task implies changing what data means (e.g. reinterpreting a score
  field) rather than how it's displayed → escalate.

## STOP CONDITION
Stop once lint/typecheck/build pass and the declared acceptance criteria
are met. Do not refactor unrelated components.

## REVIEW EXPECTATIONS
Reviewer Agent must confirm: scope compliance, lint/typecheck/build status,
no new duplicate component where a shared one already existed, and no
trading/scoring semantics touched.

## CONTEXT DISCIPLINE
Do not broad-audit the repo by default. Prefer: task-specific files, the
recent diff, and directly relevant tests/docs.
