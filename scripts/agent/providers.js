#!/usr/bin/env node
'use strict';

/*
 * Provider adapter interface (AGENT1B, Phase 7-9, 34-36).
 *
 * Each adapter reports one of three states — never silently falls back:
 *   SUPPORTED     — a real execution mechanism is configured and usable
 *   NOT_CONFIGURED — the mechanism could exist but required config/secret
 *                    is missing (e.g. an env var isn't set)
 *   UNAVAILABLE    — no automated execution mechanism exists in this
 *                    environment/tooling at all (mode is always
 *                    MANUAL_EXPORT for this provider)
 *
 * Execution mode is separate from status: a provider can be NOT_CONFIGURED
 * today and SUPPORTED tomorrow (someone sets a secret) without any code
 * change here — only the env var needs to appear. No specialist role file
 * (agents/*.md) references any of this; providers are resolved entirely
 * through config + environment, never through prompt content (Phase 28 —
 * a task/issue can never flip a provider into AUTOMATED mode).
 *
 * IMPORTANT: adapters never make a real API call here. executeAgent()
 * only resolves the mode and, for AUTOMATED providers, returns a
 * "not implemented" result rather than performing paid inference — see
 * docs/agents/PROVIDERS.md "What AGENT1B does NOT do".
 */

const ADAPTERS = {
  codex: {
    name: 'codex',
    // Codex Cloud/CLI execution in this environment is invoked
    // interactively (this very session), not via a portable API key GitHub
    // Actions could hold — there is no documented free/available mechanism
    // to drive it headlessly from a workflow today. UNAVAILABLE, not
    // NOT_CONFIGURED: no amount of env-var configuration changes this
        // without a different, currently-unimplemented integration.
    status() {
      return 'UNAVAILABLE';
    },
  },
  anthropic: {
    name: 'anthropic',
    // Would use ANTHROPIC_API_KEY via the Claude API if configured. Not
    // wired to a real call in AGENT1B (see module docstring) — reports
    // NOT_CONFIGURED/SUPPORTED based purely on the secret's presence so a
    // future execution step can be added without touching role files.
    status() {
      return process.env.ANTHROPIC_API_KEY ? 'SUPPORTED' : 'NOT_CONFIGURED';
    },
  },
  xai: {
    name: 'xai',
    status() {
      return process.env.XAI_API_KEY ? 'SUPPORTED' : 'NOT_CONFIGURED';
    },
  },
  gemini: {
    name: 'gemini',
    status() {
      return process.env.GEMINI_API_KEY ? 'SUPPORTED' : 'NOT_CONFIGURED';
    },
  },
};

function providerStatus(providerName) {
  const adapter = ADAPTERS[providerName];
  if (!adapter) return 'UNAVAILABLE';
  return adapter.status();
}

// A provider only ever executes AUTOMATED if its adapter reports SUPPORTED
// *and* config explicitly opts it into automated mode (config/agents.yaml's
// `providers.<name>.mode: AUTOMATED`). Everything else is MANUAL_EXPORT.
// This function never falls back to a different provider — see Phase 34.
function resolveExecutionMode(providerName, config) {
  const providerConfig = (config.providers && config.providers[providerName]) || {};
  const configuredMode = providerConfig.mode; // AUTOMATED | MANUAL_EXPORT | DISABLED
  const status = providerStatus(providerName);

  if (configuredMode === 'DISABLED') {
    return { mode: 'DISABLED', status, reason: 'provider disabled in config' };
  }
  if (configuredMode === 'AUTOMATED') {
    if (status === 'SUPPORTED') {
      return { mode: 'AUTOMATED', status, reason: 'credentials present, automated mode configured' };
    }
    return { mode: 'BLOCKED_PROVIDER', status, reason: `provider requested AUTOMATED but is ${status}` };
  }
  // Default (no explicit mode, or explicit MANUAL_EXPORT): always safe.
  return { mode: 'MANUAL_EXPORT', status, reason: 'no automated execution configured or available' };
}

// Execution entry point. Only ever performs a real call for a provider
// resolved to AUTOMATED — and even then, AGENT1B ships no real call (no
// provider adapter here contains network/API code), so this always
// returns a MANUAL_EXPORT-shaped result until a future story adds one.
// This function intentionally contains no eval() / shell-exec of model
// output (Phase 29) — it only returns the resolved plan.
function executeAgent({ provider, model, prompt, inputBudget, outputBudget, config }) {
  const resolved = resolveExecutionMode(provider, config || {});
  return {
    provider,
    model,
    mode: resolved.mode,
    status: resolved.status,
    reason: resolved.reason,
    // AGENT1B ships no automated inference call; AUTOMATED here always
    // means "the plan says this *could* run automatically," not that it
    // did. A human/external session pastes `prompt` into the provider
    // manually and returns a diff for the orchestrator to validate.
    executed: false,
    prompt_ref: prompt ? 'provided' : 'missing',
    input_budget: inputBudget,
    output_budget: outputBudget,
  };
}

module.exports = { ADAPTERS, providerStatus, resolveExecutionMode, executeAgent };
