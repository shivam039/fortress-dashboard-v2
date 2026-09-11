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
