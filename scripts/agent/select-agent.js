#!/usr/bin/env node
'use strict';

/*
 * Resolves an agent name to its provider/model/budget — the automatable
 * half of the Coordinator's classification contract (agents/coordinator.md).
 * Does not classify free-text tasks (that's a model's job, not this
 * script's); it resolves a *given* agent selection to its config.
 *
 * Usage: node scripts/agent/select-agent.js <agent> [path/to/config.yaml]
 * Exit 0 + JSON on stdout = resolved. Exit 1 = unknown agent.
 */

const lib = require('./lib');
const { validateBudget } = require('./validate-budget');

function selectAgent(agentName, config) {
  if (!lib.REQUIRED_AGENTS.includes(agentName)) {
    throw new Error(`unknown agent: "${agentName}" (known: ${lib.REQUIRED_AGENTS.join(', ')})`);
  }
  const resolved = lib.resolveAgentBudget(config, agentName);
  const budgetCheck = validateBudget(config, agentName);
  return {
    agent: agentName,
    provider: resolved.provider,
    model: resolved.model,
    input_budget: resolved.input_budget,
    output_budget: resolved.output_budget,
    production_access: resolved.production_access,
    is_classification_only: lib.CLASSIFICATION_ONLY_AGENTS.has(agentName),
    is_non_implementation: lib.NON_IMPLEMENTATION_AGENTS.has(agentName),
    budget_valid: budgetCheck.ok,
    budget_errors: budgetCheck.errors,
  };
}

function main() {
  const agentName = process.argv[2];
  const configPathArg = process.argv[3];
  if (!agentName) {
    console.error('Usage: node scripts/agent/select-agent.js <agent> [config.yaml]');
    process.exit(1);
  }

  const { config } = lib.loadConfig(configPathArg);
  try {
    const result = selectAgent(agentName, config);
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.budget_valid ? 0 : 1);
  } catch (err) {
    console.error(`FAIL: ${err.message}`);
    process.exit(1);
  }
}

if (require.main === module) main();
module.exports = { selectAgent };
