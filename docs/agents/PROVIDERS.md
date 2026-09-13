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

## Provider truth matrix (LUNA MISSES CLOSEOUT Epic 5)

Four separate, non-collapsible flags per provider — do not report "supported"
from CONFIG_SUPPORTED alone; EXECUTION_SUPPORTED is `NO` for all four,
unconditionally, by design (see above):

| Provider | CONFIG_SUPPORTED | EXECUTION_SUPPORTED | TESTED | PROVEN |
|---|---|---|---|---|
| Codex | YES (accepts `mode: MANUAL_EXPORT/AUTOMATED/DISABLED`) | **NO** — adapter hardcoded `UNAVAILABLE`; requesting `AUTOMATED` resolves to `BLOCKED_PROVIDER`, never runs | YES — `agent1b.test.js`'s `resolveExecutionMode: unavailable provider blocks only when AUTOMATED is requested` | NO — no real execution has ever occurred |
| Claude (`anthropic`) | YES | **NO** — `executeAgent()` never performs a real call even when the adapter reports `SUPPORTED` and mode is `AUTOMATED`; `executed` is always `false` | YES — `agent1b.test.js`'s `resolveExecutionMode: a real credential resolves AUTOMATED only when explicitly configured` and `executeAgent never actually executes, even when AUTOMATED and SUPPORTED` (both added this pass — the `SUPPORTED`-credential path had no test before) | NO |
| Grok (`xai`) | YES | **NO** — same as Claude; not individually re-tested this pass since the mechanism is provider-name-agnostic (`resolveExecutionMode`/`executeAgent` take a config, not per-provider code) | PARTIAL — covered by the same generic logic the Claude tests exercise, no `xai`-specific test | NO |
| Gemini | YES | **NO** — same mechanism | PARTIAL — same as Grok | NO |

**MANUAL_PROVIDER_EXECUTION is the accurate status for every provider
today**, per this program's own framing — not a downgrade to apologize
for, the actual current state. Claiming any provider is "supported" for
autonomous execution because config accepts its name, or because an API
key happens to be set, would be exactly the kind of overclaim this
closeout exists to catch.

## Resolution order

For a given agent, `scripts/agent/lib.js`'s `resolveAgentBudget()`:
1. starts from `defaults.provider` / `defaults.model` / `defaults.input_budget` / `defaults.output_budget`
2. overrides with anything set under `agents.<name>` in config

See `config/agents.example.yaml` for the shape.
