# AGENT3 controlled demonstration

The acceptance demonstration is the harmless docs-only fixture
`.agent-tasks/example-docs-task.yaml`. It exercises plan, manual prompt export,
a controlled JSON result import, same-run resume, scope, declared test result,
selected static evals, Reviewer, docs, and dry PR readiness.

The demonstration intentionally produces a **dry PR payload**, not a GitHub PR,
because creating a noise PR for an unchanged fixture is not useful. Its terminal
state is `AWAITING_HUMAN`; it cannot merge. No Oracle, Vercel, Neon, Render,
OPS1, scheduler, application, or production resource is contacted.

Run the normal commands documented in `USAGE.md`, using
`docs/agents/USAGE.md` as the controlled `changed_files` value. Verify the
manifest reports:

- scope, tests, and docs gates: `PASS` (or docs `NOT_REQUIRED`)
- eval: `EVAL_PASS` or `EVAL_WARN`, with no hard failures
- review: `MERGEABLE`
- production impact: `NONE`
- auto merge: `false`
- final state: `AWAITING_HUMAN`

This is a lifecycle demonstration only. The `/api/mf-analysis` pop-index bug is
explicitly reserved for a later real Backend Agent task.
