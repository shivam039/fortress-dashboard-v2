# Agent Framework Usage (AGENT1A + AGENT1B)

## 1. Define a task

Create `.agent-tasks/<task-id>.yaml`:

```yaml
id: my-task-001
title: "Short description"
agent: backend            # one of: coordinator, backend, frontend, qa,
                           # performance, infra, research, docs, reviewer
priority: low              # low | medium | high
allowed_files: [path/to/file.py]
forbidden_files: []
input_budget: 9000          # optional — overrides config's resolved default
output_budget: 3000         # optional
acceptance_criteria: [criterion one, criterion two]
dependencies: []
production_access: false    # keep false unless the task genuinely needs it
docs_required: false        # false | true | auto
```

See `.agent-tasks/example-task.yaml` for a working fixture.

## 2. Validate the config and role files

```
node scripts/agent/validate-agent-config.js
```

Checks: all 9 required `agents/*.md` files exist, every agent named in
`config/agents.yaml` (or `.example.yaml` if no real config exists yet) is
a known role, and providers are recognized or flagged.

## 3. Validate a budget

```
node scripts/agent/validate-budget.js backend
```

Checks: positive input/output budgets, within any configured project
ceiling (`ceilings.max_input_tokens` / `max_output_tokens`).

## 4. Resolve an agent

```
node scripts/agent/select-agent.js backend
```

Prints the resolved `{provider, model, input_budget, output_budget,
production_access, is_classification_only, is_non_implementation,
budget_valid}` as JSON.

## 5. Dry-run a prompt

```
node scripts/agent/build-agent-prompt.js backend .agent-tasks/example-task.yaml
```

Prints a `DRY RUN SUMMARY` (selected agent, resolved provider/model,
budgets, allowed files, `requires_human_gate`) followed by the full
generated prompt (role contract + task + budget + repo constraints). No
model API is called. No API key is required — see PROVIDERS.md.

## 6. Run the tests

```
node --test scripts/agent/agent-system.test.js
```

## Config resolution order

`scripts/agent/lib.js`'s `loadConfig()` looks for `config/agents.yaml`
first (a real, gitignored config); if that doesn't exist, it falls back
to the committed `config/agents.example.yaml`. Any script accepts an
explicit config path as its last argument to override this.

## Custom config

Copy `config/agents.example.yaml` to `config/agents.yaml` and edit
per-agent `provider`/`model`/budgets. Do not commit `config/agents.yaml`
if it contains anything account-specific.

## AGENT1B: running the controlled execution pipeline

### 1. Author a task and get it approved

Create `.agent-tasks/<task-id>.yaml` (same schema as above, plus
AGENT1B fields: `issue_number`, `branch_name` override, `risk`,
`human_approval_required`). Open/link a GitHub Issue for it, assign an
`agent:<name>` label, and once ready, add `agent:approved` — this is
the explicit activation signal (see ARCHITECTURE.md's label table).
Nothing runs from issue creation alone.

### 2. Plan

```
node scripts/agent/orchestrate-task.js plan .agent-tasks/<task-id>.yaml
```

Runs: classification (task's own `agent:` field — a free-text
Coordinator classifier is not implemented in AGENT1B, a human sets
this) → budget gate (`BLOCKED_BUDGET` if invalid/over-ceiling) →
provider mode resolution (`BLOCKED_PROVIDER` if AUTOMATED was
requested but unavailable) → idempotency check (`BLOCKED` if the
target branch already exists) → branch naming → prompt build → a run
record under `.agent-room/sessions/`. Prints the full generated
prompt for manual export unless a provider is configured `AUTOMATED`.

In GitHub Actions, this is `agent-task.yml` (`workflow_dispatch` with
the issue number + task file, gated on the `agent:approved` label) —
it uploads the prompt as an artifact and comments a plan summary
(never the full prompt) on the issue.

### 3. Implement (manually, in current AGENT1B — see PROVIDERS.md)

Create the branch the plan output named, paste the generated prompt
into whichever provider you're actually using, implement within
`allowed_files`, and commit to that branch.

### 4. Validate scope

```
node scripts/agent/orchestrate-task.js apply .agent-tasks/<task-id>.yaml
```

Compares the branch's actual `git diff --name-only` against
`allowed_files`/`forbidden_files`. `BLOCKED_SCOPE` if anything is out
of bounds — this is a hard stop, not a warning.

### 5. Tests, Reviewer, Docs, PR

Run the task-defined tests (or the specialist's contract default set —
see the relevant `agents/<name>.md`'s TEST EXPECTATIONS). Build a
Reviewer prompt the same way (`build-agent-prompt.js reviewer ...`) and
get its verdict manually. If `docs_required` is `true` (or Reviewer
flags docs impact), do the same for the `docs` agent. Then open the PR
using `scripts/agent/pr-body.js` for the body template.

### 6. Human merges

There is no auto-merge path anywhere in this pipeline (see
GOVERNANCE.md). The PR sits `AWAITING_HUMAN` until a person merges it.

## AGENT3: one resumable, quality-gated run

AGENT3 composes the AGENT1B execution controls and AGENT2 evaluator; it does
not add roles or call a paid provider. Start a canonical run with:

```bash
node scripts/agent/agent.js plan .agent-tasks/<task-id>.yaml
```

For `MANUAL_EXPORT`, the output names the provider/model and prompt artifact,
the required JSON response shape, and the exact import/resume commands. A
minimal response is:

```json
{"run_id":"<same-run-id>","provider":"codex","model":"<configured-model>","changed_files":["docs/example.md"],"summary":"Implemented the approved task."}
```

Treat that file as untrusted. Import and resume the **same** run:

```bash
node scripts/agent/agent.js import-result <run-id> result.json
node scripts/agent/agent.js resume <run-id>
```

The importer rejects a wrong run/provider/model, checks scope, limits file
size, stores a hash, and ignores attempts to alter production access, scope,
budgets, review, human-gate, or merge policy. Record externally executed test
results rather than putting task-authored shell commands into the pipeline:

```bash
node scripts/agent/agent.js tests <run-id> tests-report.json
node scripts/agent-eval/run-gate.js .agent-room/sessions/<run-id>.manifest.json eval-report.json
node scripts/agent/agent.js eval <run-id> eval-report.json
node scripts/agent/agent.js review <run-id> MERGEABLE
node scripts/agent/agent.js docs <run-id> pass   # only when required
node scripts/agent/agent.js pr-ready <run-id>
```

`EVAL_WARN` continues to Reviewer with the warning visible. `EVAL_FAIL` and
every hard safety failure stop at `BLOCKED_EVAL`; Reviewer cannot override it.
Reviewer may request one focused repair using the same provider. A second
failure blocks for a human, and provider switching is never automatic.

PR readiness requires scope PASS, tests PASS, eval PASS/WARN, an acceptable
review verdict, satisfied docs, and a valid human gate. The final state is
always `AWAITING_HUMAN`; this CLI has no merge command.

Provider recommendations are advisory and require five evaluated samples per
role/provider:

```bash
node scripts/agent/agent.js recommend-provider backend quality-records.json
```

Token efficiency is calculated only when real input and output usage is
available. Missing usage is left null, and safety failures invalidate an
efficiency claim. Recommendations never rewrite provider configuration.
