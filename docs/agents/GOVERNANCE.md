# AGENT1A Governance

## Current status

AGENT1A defines the static architecture (roles, config, scripts, dry-run
prompt building) only. **No specialist agent is wired up to execute live
against this repo yet.** Live execution — an agent actually opening a PR
— is AGENT1B, and AGENT1B may only start once INFRA4 has reached a safe,
observed state (see the INFRA4 story for its own gate).

## Human approval boundaries

The following always require explicit human approval, regardless of which
agent or provider is involved, and regardless of how confident the agent
is:

- production infrastructure modification (Oracle, Docker, Caddy config
  that affects a live deployment)
- scheduler ownership changes (which backend GitHub Actions targets)
- secret changes / rotation
- DNS changes
- DB migrations with destructive potential
- paper-trading semantics changes
- scoring changes
- resource deletion (images, volumes, services, Render/Oracle instances)
- auto-merge of any PR

These remain gated even after AGENT1B exists. Nothing in AGENT1A or its
planned successor changes this list without a separate, explicit decision.

## Infra Agent — special restriction

`agents/infra.md` is defined but must not be invoked for live execution
against production during AGENT1A/INFRA4. `config/agents.example.yaml`
sets `agents.infra.production_access: false`, and
`scripts/agent/validate-budget.js` / `select-agent.js` surface this value
so any future orchestration layer can check it before allowing infra
actions.

## Review policy

- Coordinator classifies; it does not implement.
- Reviewer evaluates mergeability; it does not implement.
- A specialist's PR requires a Reviewer verdict of `MERGEABLE` (or
  `MERGEABLE_WITH_MINOR_FIXES` with the fixes applied) before human merge.
  `NOT_MERGEABLE` blocks merge.
- Any task with `requires_human_gate: true` (from Coordinator's
  classification, or because it touches the human-approval list above)
  needs a human sign-off regardless of Reviewer's verdict.

## Docs policy

- Docs describe current merged reality, not planned behavior (see
  `agents/docs.md`).
- Every task declares `docs_required: true/false/auto`. If `auto`,
  Coordinator or Reviewer determines docs impact during classification/
  review.
- Docs Agent touches only the documentation relevant to the changed area
  — not a full README rewrite per change.

## Merge policy

No automatic merging exists or is planned to exist without a human in
the loop for the foreseeable future. AGENT1A's dry-run mode exists
specifically so the whole pipeline (task → classify → resolve → build
prompt → validate scope) can be exercised and trusted *before* any real
execution or merge capability is added.

## AGENT1B: execution governance

### Activation gate

`agent-task.yml` only runs for a `workflow_dispatch` naming an issue
that carries the `agent:approved` label (checked as a workflow step
before anything else runs). Issue creation alone never triggers
anything — see ARCHITECTURE.md's label table.

### Prompt-injection boundary

Generated prompts (`build-agent-prompt.js`) place the role contract and
repo constraints *before* task content, and task content is never
concatenated into a shell command, file path, or workflow expression —
`sanitize.js` strips anything unsafe out of branch names/task IDs
before they touch git. Task/issue content cannot raise
`production_access` above what the target agent's own config allows
(`orchestrate-task.js`'s `plan()` computes it as `task.production_access
&& agentConfig.production_access`, never `task.production_access`
alone), and cannot exceed the configured token ceiling — both enforced
in code, not by asking the model nicely.

### No arbitrary execution

The orchestrator never does `eval()` or shell-executes model output.
`scope-check.js` only ever runs `git diff --name-only` (a fixed,
non-interpolated command) and pattern-matches its output; test
execution is the task's own declared commands, run by the human/CI
step following USAGE.md, not by the orchestrator itself.

### Idempotency and concurrency

`orchestrate-task.js plan()` refuses to run if the target branch
already exists (Phase 31). `agent-task.yml` sets
`concurrency: { group: agent-task-<issue>, cancel-in-progress: false }`
so two runs for the same issue can't race (Phase 32).

### Cancellation

Removing `agent:approved` (or adding `agent:cancelled`) stops future
runs from activating; an in-flight GitHub Actions run can be cancelled
normally. The branch, any diff on it, and the run record under
`.agent-room/sessions/` are never auto-deleted — they stay available
for diagnosis (Phase 33).

### GitHub permissions

`agent-validate.yml`: `contents: read` only. `agent-task.yml`:
`contents: read` + `issues: write` (to comment the plan summary) — no
`pull-requests: write` yet, since AGENT1B's shipped workflow only plans
(no automated diff exists to open a PR from). Neither workflow requests
`write-all` or any broader permission.
