# AGENT1A Usage

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
