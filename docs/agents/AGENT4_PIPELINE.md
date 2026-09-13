# AGENT4 — GitHub-native pipeline

AGENT1A defines roles, providers, and budgets. AGENT1B adds controlled task
execution. AGENT2 supplies provider-neutral evaluation. AGENT3 joins the
quality-gated lifecycle around one run manifest. AGENT4 automates that
lifecycle from an approved GitHub Issue to an open pull request.

## Setup and approval

The canonical workflow is `.github/workflows/agent-pipeline.yml`. Create an
Issue with a concrete scope and repository paths, then add `agent:approved`.
Issue creation alone does nothing. The workflow reads the title/body as
bounded untrusted data; they cannot change provider configuration, budgets,
production access, review, secret handling, or the no-auto-merge policy.

The Coordinator classifies one clear specialist from the issue. Ambiguous or
multi-domain requests stop at `BLOCKED_CLASSIFICATION` and receive an
`agent:blocked` lifecycle state rather than being guessed. A task branch is
named `agent/<issue>-<agent>-<slug>` and duplicate remote branches are refused.

## Provider modes and fallback

Provider selection is role configuration, not issue input. Each provider is
one of `AUTOMATED`, `MANUAL_EXPORT`, `DISABLED`, or `NOT_CONFIGURED`. This
repository currently ships no secure headless paid API adapter, so the example
configuration honestly uses `MANUAL_EXPORT` for Codex, Anthropic, xAI, and
Gemini. `cost_mode` (`included`, `free_tier`, `paid`, or `manual`) is advisory
visibility only. The pipeline never switches provider after a failure.

At `WAITING_FOR_PROVIDER_RESULT`, download the short-retention run artifact,
run the prompt with the selected provider, commit the implementation to the
created branch, and dispatch **AGENT4 GitHub Pipeline** with `action=resume`,
the run ID, and the result JSON. The schema requires `run_id`, `provider`,
`model`, and `changed_files`; governance-shaped result fields are ignored.
This provider limitation is the only manual handoff. Import resumes scope,
tests, static AGENT2 eval, review/docs gates, and PR creation automatically.

## Gates and lifecycle

The pipeline uses minimal labels: `agent:approved`, `agent:running`,
`agent:testing`, `agent:evaluating`, `agent:review`, `agent:manual-action`,
`agent:blocked`, `agent:ready`, and `agent:cancelled`. Scope is checked from
`git diff --name-only origin/main`; provider-declared files are not trusted.
An eval warning proceeds and a failure blocks. Review allows one repair cycle.
Docs run only when classified or flagged as required. Provider execution has
at most one retry for a transient error and never changes providers.

The generated PR records issue, task, specialist, provider/model/budget,
changed files, tests, eval score, review verdict, docs state, production
impact, human gate, and run ID. It contains no prompt or credentials. The
terminal automated state is `AWAITING_HUMAN`; only a human merges.

### Evidence artifacts

After scope validation, the pipeline runs the task-specific test plan and
stores a machine-readable report. Locally, the canonical runner is:

```sh
node scripts/agent/agent.js run-tests <run-id>
```

The report records the selected commands, exit codes, status, timestamps, and
the artifact path. A non-zero exit code is a failed test gate; the pipeline
does not turn an unavailable or failed command into `PASS`.

The automatic gate command consumes actual report files rather than stage
booleans:

```sh
node scripts/agent/agent.js auto-gates <run-id> <eval-report.json> \
  <test-report.json> <review-report.json> [docs-report.json]
```

The eval report must come from AGENT2, and the reviewer report must contain a
structured verdict and findings. A docs-required run must also provide a docs
report with `status: PASS`; missing evidence fails closed. Reports are stored
in the run manifest so the PR body can identify the evidence supporting each
gate.

### Reviewer evidence policy

`scripts/agent/reviewer-evidence.js` classifies every file in
`manifest.changed_files` into one category (`backend_logic`,
`frontend_logic`, `api_contract`, `db_persistence`, `security_auth`,
`infra_workflow`, `agent_framework`, `tests`, `docs`, `other_code`, or
`other`) by path pattern — a deterministic check, not diff-content/semantic
analysis. `docs`, `tests`, and `other` never require additional evidence.
Every other category (including `other_code`) requires at least one
changed file that looks like matching evidence (e.g. `backend_logic`
requires a `tests/backend/*` file in the same `changed_files` list;
`frontend_logic` requires `frontend/tests/*`, `frontend/e2e/*`, or a
`*.test.{ts,tsx,js,jsx}` file; `security_auth` requires a `tests/*` file
whose path also mentions `auth`/`token`/`session`/`crypto`/`secret`/
`rate_limit`/`security`). `other_code` exists to close a real gap found in
this closeout's own Epic 20 adversarial review: any file with a recognized
source-code extension that no named category claimed (e.g.
`scripts/pricing_engine.py`, living outside `engine/`) used to fall into
the free-pass `other` bucket — a real logic change could dodge the
evidence gate entirely just by living in an unanticipated directory.
`other_code` requires generic test evidence instead; only genuinely
non-code files (configs, lockfiles, images) still land in `other`.
A category present in the diff with no matching evidence is a finding and
the verdict is `NOT_MERGEABLE` — a green existing test suite that doesn't
exercise the changed behavior is not treated as evidence for it. The
reviewer also checks that a *real* test command ran: if `test-report.json`'s
`commands` were only the generic no-op fallback (`git diff --check` — what
`scripts/agent/test-runner.js`'s `selectTests()` falls back to when nothing
else matches) while the diff includes a category that requires evidence,
that is its own finding (tests were never actually executed, as distinct
from executed-and-failed).

**Test evidence waiver.** `reviewer-evidence.js` reads
`manifest.test_waiver: { reason: "...", categories: ["backend_logic", ...] }`
(`categories` omitted applies to any gap found). A waiver with a non-empty
`reason` converts a would-be blocking finding into a visible note and the
verdict becomes `MERGEABLE_WITH_NOTES` instead of `NOT_MERGEABLE` — the
waiver and its reason stay in the review report, never silently dropped. A
waiver with a blank/missing reason is not accepted.
**PROVEN vs. CONFIGURED**: only the reviewer's *read* side exists and is
tested today. No automatic writer populates `test_waiver` from Coordinator
classification, an issue directive, or any other input — a human must set
it directly on the manifest JSON before `auto-gates` runs. `import-result`
(provider output) is intentionally never a valid source for it, so that an
agent cannot self-waive its own missing evidence once a writer path is
added; do not add one that reads it from provider-controlled input.

Reviewer verdicts are `MERGEABLE`, `MERGEABLE_WITH_NOTES`,
`MERGEABLE_WITH_MINOR_FIXES` (a human-authored review verdict, not emitted by
`reviewer-evidence.js` itself), `NOT_MERGEABLE`, or `BLOCKED`. `BLOCKED` is
reserved for a structurally invalid review (e.g. no changed files were
evidenced at all) and skips the one-shot repair cycle that `NOT_MERGEABLE`
gets; `MERGEABLE`/`MERGEABLE_WITH_NOTES`/`MERGEABLE_WITH_MINOR_FIXES` all
proceed to the docs/PR gates.

### Docs-required escalation (not just classification)

`docs_required` used to be fixed the moment the Coordinator classified the
issue (`true` only when `selected_agent === 'docs'`) and never revisited once
the real diff was known — a `backend`/`infra`/`agent-framework`-classified run
that touched an API route, a security/auth file, a workflow file, or the
agent framework itself could reach `AWAITING_HUMAN` with `docs_status:
NOT_REQUIRED`, regardless of what it actually changed.

`scripts/agent/agent.js`'s `auto-gates` now also calls
`docs-evidence.js`'s `docsLikelyRequired(changed_files)` — reusing
`reviewer-evidence.js`'s same path-category classifier — and passes the
result as `reviewerGate()`'s `docsImpact` argument. A changed file in
`api_contract`, `security_auth`, `infra_workflow`, or `agent_framework`
escalates `docs_required` to `true` even if the run was never classified as
`docs`. `backend_logic`/`frontend_logic`/`db_persistence`/`tests`/`docs`/
`other` never escalate — an internal refactor, a test-only change, or a
docs-only change does not need more docs just because a file moved.

**PROVEN vs. CONFIGURED, stated plainly:** there is still no automated check
that verifies docs were *actually written correctly* for an escalated run —
`docs-evidence.js`'s advisory report has no `status` field, so `docsGate()`
reading it always resolves to `docs_status: PENDING`, which blocks
`prGate()` (`state: BLOCKED_PR`) rather than silently passing. This is
deliberate: escalating `docs_required` without also being able to prove docs
were written would otherwise silently do nothing. Once escalated, a human
must supply real doc-satisfaction evidence (`node scripts/agent/agent.js
docs <run-id> pass`, or a future automated check with a real `status`
field) before the run can proceed — it does not currently unblock itself.

## Production and secret safety

Oracle, Caddy, DNS, Vercel/Neon production, schedulers, secrets, trading or
scoring semantics, and resource deletion always retain a human gate. Agents
may prepare a PR but this workflow has no deploy/apply or auto-merge command.
Credentials come only from GitHub Secrets/environment and must never appear in
issues, manifests, logs, artifacts, configuration, or PR bodies.

## Status, cancellation, and troubleshooting

Inspect a restored/local run with:

```sh
node scripts/agent/agent.js status <run-id>
```

Cancel future local stages with `agent:cancelled` or:

```sh
node scripts/agent/agent.js cancel <run-id>
```

Cancellation retains the branch and artifacts. For a blocked run, inspect
`state`, `provider_mode`, `scope_status`, `tests`, `eval_status`,
`review_status`, `docs_status`, `branch`, and `pr_number` in status output.
Fix the cause and explicitly resume; do not delete evidence or bypass a gate.

## Harmless end-to-end proof

The fixture `scripts/agent/agent4-pipeline.test.js` exercises an approved docs
correction through classification, manual-provider pause, gates, redacted PR
payload, bounded repair/retry, label synchronization, and human-merge stop.
It performs no production mutation and does not make a paid provider call.
