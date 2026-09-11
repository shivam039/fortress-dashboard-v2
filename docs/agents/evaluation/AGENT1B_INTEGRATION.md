# AGENT1B Integration Request

AGENT2 does not modify AGENT1B-owned execution files. When AGENT1B is ready,
the evaluator can consume run records if they expose these stable fields:

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
