# AGENT1B Integration Request

AGENT3 now integrates AGENT2 with AGENT1B through the canonical versioned JSON
run manifest. The evaluator consumes only stable fields and remains independent
of prompt construction and provider adapter internals:

- `run_id`
- `task_id`
- `agent`
- `provider`
- `model`
- `input_budget`
- `output_budget`
- `input_tokens`
- `output_tokens`
- `allowed_files`
- `changed_files`
- `forbidden_files`
- `tests`
- `review_verdict`
- `docs_required`
- `requires_human_gate`
- `production_access`
- `hard_failures`

Provider outputs may be automated, manually imported, or disabled. Static evals
must continue to pass with no API key.

`scripts/agent-eval/run-gate.js` selects only the manifest's `eval_groups`.
Backend runs use backend/security/reviewer; infra uses infra/security/reviewer;
docs uses docs/reviewer; coordinator uses coordinator/security. Changes to the
agent framework select the full static suite. Hard failures always block, while
WARN is intentionally passed to Reviewer as visible evidence.
