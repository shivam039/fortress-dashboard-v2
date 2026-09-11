# AGENT1A Providers

## Concept

A "provider" is where an agent role's prompt actually gets executed.
AGENT1A recognizes three provider names conceptually:

- `codex` — OpenAI Codex / Codex Cloud
- `anthropic` — Claude (Claude Code, Claude API)
- `xai` — Grok
- `gemini` — Google Gemini

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
difference belongs in a provider adapter (`scripts/agent/providers.js`,
added in AGENT1B) — not in a specialist's role file.

## Current provider status (this repo, as implemented)

| Provider | Mechanism | Status here | Mode |
|---|---|---|---|
| `codex` | Codex Cloud/CLI, invoked interactively in a session like this one | `UNAVAILABLE` — no headless/API mechanism this repo's tooling can drive from a GitHub Actions workflow exists yet | `MANUAL_EXPORT` always |
| `anthropic` | Claude API, would use `ANTHROPIC_API_KEY` | `NOT_CONFIGURED` (no key set in this environment) | `MANUAL_EXPORT` unless a key is added *and* `providers.anthropic.mode: AUTOMATED` is set in config |
| `xai` | Grok API, would use `XAI_API_KEY` | `NOT_CONFIGURED` | `MANUAL_EXPORT` unless a key is added *and* `providers.xai.mode: AUTOMATED` is set in config |
| `gemini` | Google Gemini API, would use `GEMINI_API_KEY` | `NOT_CONFIGURED` | `MANUAL_EXPORT` unless a key is added *and* `providers.gemini.mode: AUTOMATED` is set in config |

**Important:** even with a real API key configured and `mode: AUTOMATED`
set, AGENT1B ships **no actual network call** to any provider —
`scripts/agent/providers.js`'s `executeAgent()` always returns
`executed: false`. Wiring up a real automated call is future work, not
part of AGENT1B (see the "important implementation decision" in the
AGENT1B story: don't force paid automation just to claim it exists).
Until then, every provider is effectively `MANUAL_EXPORT` in practice —
see PHASE 37/USAGE.md's manual-export flow, which is fully functional
today with zero provider credentials.

## Resolution order

For a given agent, `scripts/agent/lib.js`'s `resolveAgentBudget()`:
1. starts from `defaults.provider` / `defaults.model` / `defaults.input_budget` / `defaults.output_budget`
2. overrides with anything set under `agents.<name>` in config

See `config/agents.example.yaml` for the shape.
