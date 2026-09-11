# AGENT1A Providers

## Concept

A "provider" is where an agent role's prompt actually gets executed.
AGENT1A recognizes three provider names conceptually:

- `codex` — OpenAI Codex / Codex Cloud
- `anthropic` — Claude (Claude Code, Claude API)
- `xai` — Grok

**No provider-specific business logic lives inside `agents/*.md`.** A role
file describes mission/scope/budget only; `config/agents.example.yaml`
(or your real `config/agents.yaml`) says which provider/model actually
runs it. Swapping providers for an agent never requires editing that
agent's role file.

## What AGENT1A does NOT do

AGENT1A does not make real API calls to any of these providers. Every
script in `scripts/agent/` is dry-run only: it resolves config and
renders a prompt string. No API key is read, required, or checked — see
`USAGE.md` step 5 and test #15 in `scripts/agent/agent-system.test.js`
("dry-run works without any API key").

**Do not claim model inference is universally free.** Existing
subscriptions/quotas for Claude / Codex / Grok are what make the
*orchestration* layer (GitHub Actions, Issues, PRs, this repo's scripts)
free — actually running a specialist agent's prompt through a provider
still consumes that provider's own quota/credits, same as using it any
other way. AGENT1A's job is to make that resolution step (which agent,
which provider, which budget) free and inspectable *before* any of that
quota is spent.

## Provider adapter isolation

If Codex, Claude, and Grok differ in execution mechanism (CLI vs. API vs.
SDK, different auth flows, different context-window shapes), that
difference belongs in a provider adapter — not in a specialist's role
file. AGENT1A does not implement provider adapters (that's AGENT1B); this
doc is where their mechanism differences should eventually be documented,
one section per provider, so `agents/*.md` never needs to know about them.

## Resolution order

For a given agent, `scripts/agent/lib.js`'s `resolveAgentBudget()`:
1. starts from `defaults.provider` / `defaults.model` / `defaults.input_budget` / `defaults.output_budget`
2. overrides with anything set under `agents.<name>` in config

See `config/agents.example.yaml` for the shape.
