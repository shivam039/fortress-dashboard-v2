# Agent Status

**Keep this current.** Any future PR that changes agent wiring (adds,
removes, or changes how a role is invoked, or how it executes) must update
this doc in the same PR — it is not optional follow-up. A role/script/
workflow file existing is not evidence it runs; only a run ID, a log line,
or a reproducible manual invocation with real output counts as evidence.

This doc distinguishes four separate, non-collapsible concepts per role.
Do not merge them into one "implemented" flag — a role can honestly be
`WIRED=YES, EXECUTABLE=NO` (dispatch works; nothing autonomously produces
its work product), and that is a valid, stable state, not a bug to hide:

- **DEFINED** — `agents/<role>.md` exists and `validate-agent-config.js`
  accepts it.
- **WIRED** — a real, currently-merged workflow step will *dispatch* this
  role from live input (an approved GitHub issue) without a human manually
  invoking a CLI command first.
- **EXECUTABLE** — once dispatched, does this role's own work (writing a
  diff, running a check) happen without a human/external agent manually
  doing it? For the 6 specialist coder roles this means "is there an
  `AUTOMATED` provider adapter" (there is not, for any role — see
  `docs/agents/PROVIDERS.md`); for Reviewer/Docs it means "does the check
  script itself run standalone" (it does).
- **TESTED** — unit/integration test coverage exists for this role's own
  logic (not just that some workflow YAML mentions it).
- **PROVEN_IN_REAL_RUN** — a completed (not necessarily successful) GitHub
  Actions execution of `.github/workflows/agent-pipeline.yml` has actually
  reached this role's code path and produced real output, with a run ID.
  Passing local tests is not this.

Last updated: 2026-09-13, LUNA MISSES CLOSEOUT Epic 2.

## Correction to the prior version of this doc

The 2026-09-13 FORTRESS-NEXT version of this doc claimed Backend, Frontend,
QA, Performance, Infra, and Research were "NOT WIRED (intentional)",
verified by `grep -rn "orchestrate-task" .github/workflows/` returning no
matches. **That verification method was checking the wrong mechanism.**
`orchestrate-task.js` is a separate, `task.yaml`-driven local CLI
(`plan`/`apply`) that is genuinely never invoked by any workflow — but it
is not what `.github/workflows/agent-pipeline.yml` uses to dispatch a role
from a GitHub issue. The real path is `agent.js issue-plan` →
`github-pipeline.js`'s `classifyIssue()`/`classifyRole()`, which has no
special-casing for `docs` at all: it maps issue text to any of 7 roles
(`docs`, `backend`, `frontend`, `qa`, `performance`, `infra`, `research`)
through the same generic regex-classification, branch-creation, prompt-
build (`agents/<role>.md`), and `MANUAL_EXPORT` pause. Verified empirically
by running `node scripts/agent/agent.js issue-plan <synthetic-issue>` with
real trigger words for each role and a valid repository path (see table
below for the exact commands and output) — every one of Backend, Frontend,
Performance, and Infra reached `WAITING_FOR_PROVIDER_RESULT` with the
correct `selected_agent`, `branch`, and `allowed_files`, identically to how
Docs already worked. **This means these 6 roles are WIRED, not unwired** —
the prior claim was itself an unverified/incorrectly-verified claim, which
is exactly the pattern this closeout program exists to catch.

What genuinely does *not* exist for any of the 6 specialist roles — and
did not exist for Docs/Reviewer either until Epic 19/Epic 1 respectively
added a standalone check script — is an `EXECUTABLE` path: something that
autonomously produces the role's actual work product (a code diff) without
a human/external agent session doing it by hand. That is a provider-layer
gap (see Epic 5 / `docs/agents/PROVIDERS.md`: every provider — Codex,
Anthropic, xAI, Gemini — is `MANUAL_EXPORT`, and `codex`'s own adapter
reports hardcoded `UNAVAILABLE`), not a per-role wiring gap. Building an
automated headless execution adapter is explicitly out of scope for this
closeout (`DO NOT OVER-CORRECT` — no new infrastructure).

## The 9 defined roles

| Role | DEFINED | WIRED | EXECUTABLE | TESTED | PROVEN_IN_REAL_RUN |
|---|---|---|---|---|---|
| Coordinator | YES | YES — `agent-pipeline.yml` step "Coordinator classification and provider resolution" → `agent.js issue-plan` → `github-pipeline.js classifyIssue()` | YES — pure deterministic classification, no external dependency | YES — `agent4-pipeline.test.js` (19 tests) | **YES** — issue #39's two real runs (2026-09-12, run IDs `34674828166`, `34674837803`) actually executed Coordinator classification and produced real (blocking) output |
| Reviewer | YES | YES — same workflow, step "Scope, tests, eval, review, docs, and PR gates" → `reviewer-evidence.js` | YES — standalone, deterministic, no human needed to run the check itself | YES — 26 tests (`reviewer-evidence.test.js`, `reviewer-evidence-gap.test.js`, `unified-pipeline-reviewer-gate.test.js`) | **NO** — no completed real run has ever reached this step; both real runs so far (issue #39) failed at Coordinator classification before Reviewer ran |
| Docs | YES | YES — same workflow, same step → `docs-evidence.js` | YES — standalone, deterministic | YES — `docs-evidence.test.js` (8 tests, including a real historical-diff replay) | **NO** — same reason as Reviewer |
| Backend | YES | **YES** (corrected — see above) — `classifyRole()` selects `backend` from issue text identically to `docs`; verified: `echo '{"body":"Update engine/utils/db.py to handle a null case. See tests/backend/test_db.py."}' → issue-plan` → `selected_agent: "backend"`, `state: WAITING_FOR_PROVIDER_RESULT` | **NO** — no automated provider adapter exists (all `MANUAL_EXPORT`); a human/external agent must write the actual diff | PARTIAL — classification/dispatch covered by generic `classifyIssue` tests; no backend-specific dispatch test existed before this pass | **NO** — never reached in a completed real run |
| Frontend | YES | **YES** (corrected) — verified: body mentioning `frontend/src/app/screener/page.tsx` react/component styling → `selected_agent: "frontend"`, `WAITING_FOR_PROVIDER_RESULT` | NO — same provider gap | PARTIAL — same as Backend | **NO** |
| QA | YES | **YES** (corrected, classification mechanism proven) — the `qa` regex (`\b(qa|playwright|end[- ]to[- ]end|test[- ]only)\b`) does fire; a specific attempted verification body was itself ambiguous (matched more than one role) and hit `BLOCKED_CLASSIFICATION`, which is the Coordinator's correct designed behavior for ambiguous text, not a role-wiring failure — not re-verified with an unambiguous body in this pass | NO — same provider gap | PARTIAL | **NO** |
| Performance | YES | **YES** (corrected) — verified: body mentioning `engine/main.py` latency/benchmark regression → `selected_agent: "performance"`, `WAITING_FOR_PROVIDER_RESULT` | NO — same provider gap | PARTIAL | **NO** |
| Infra | YES | **YES** (corrected) — verified: body naming `Dockerfile`/`docker-compose.oracle-production.yml`/`Caddyfile` (after this pass's own root-level-path-detection fix — see the standalone PR) → `selected_agent: "infra"`, `WAITING_FOR_PROVIDER_RESULT`, `risk: HIGH` (production-sensitive terms correctly detected) | NO — same provider gap | PARTIAL | **NO** |
| Research | YES | **YES** (corrected) — the `research` regex fires; a specific verification body ("Research and analysis of docs/research/historical_dataset.md evidence") deliberately routed to `docs` instead per the existing, tested, intentional docs-vs-research disambiguation rule (a concrete `docs/` path is stronger evidence of ownership than generic "research"/"analysis" words) — not a bug, but means this exact fixture doesn't demonstrate `research` dispatch; not re-verified with a research-only body in this pass | NO — same provider gap | PARTIAL | **NO** |

## Agent-wiring count

**9 of 9 roles WIRED for dispatch/classification** (corrected from the
prior "3 of 9"). **3 of 9 roles EXECUTABLE** (Coordinator, Reviewer, Docs —
all three run their own logic standalone with no human in the loop). **0
of 9 roles PROVEN_IN_REAL_RUN** — no completed GitHub Actions execution of
`agent-pipeline.yml` has ever reached past Coordinator classification; the
only two real runs on record (issue #39) both hit `BLOCKED_CLASSIFICATION`
before reaching any further stage. This is the single most important
number in this doc: **every role's real-world execution is presently
unproven**, regardless of how much unit-test coverage or classification
logic exists. Closing that gap is what Epic 17 (Real Agent Canary) is for.

## How to verify wiring yourself

- **A role is WIRED for dispatch** — check whether `classifyRole()` in
  `scripts/agent/github-pipeline.js` has a pattern for it, then confirm
  with a real `node scripts/agent/agent.js issue-plan <issue.json>`
  invocation using an issue body that should trigger it — not a grep for
  an unrelated helper script's name.
- **A role is EXECUTABLE** — can its own logic (a check script, or an
  actual code-writing step) run to completion with zero human input? For
  the 6 specialist roles, this requires an `AUTOMATED` provider adapter,
  which does not exist today for any provider.
- **A role's check actually catches something** — point to a test or
  reproduction that exercises a real failure case and shows the literal
  output, not "the code path exists" or "it was invoked once without
  erroring."
- **A role is PROVEN_IN_REAL_RUN** — cite a specific GitHub Actions run ID
  where that role's code path executed, with what it produced. A passing
  local test suite is not this.
- `scripts/agent/validate-agent-config.js` only confirms all 9
  `agents/*.md` files exist and the config is structurally valid — it says
  nothing about wiring, execution, or proof.
