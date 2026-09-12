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
