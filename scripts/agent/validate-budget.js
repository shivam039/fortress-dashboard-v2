#!/usr/bin/env node
'use strict';

/*
 * Validates a resolved agent's token budget: positive, and within the
 * config's optional project ceiling (ceilings.max_input_tokens /
 * ceilings.max_output_tokens).
 *
 * Usage: node scripts/agent/validate-budget.js <agent> [path/to/config.yaml]
 * Exit 0 = valid budget. Exit 1 = invalid (see stderr).
 */

const lib = require('./lib');

function validateBudget(config, agentName) {
  const errors = [];
  if (!lib.REQUIRED_AGENTS.includes(agentName)) {
    return { ok: false, errors: [`unknown agent: "${agentName}"`] };
  }

  const resolved = lib.resolveAgentBudget(config, agentName);
  const { input_budget: inputBudget, output_budget: outputBudget } = resolved;

  if (typeof inputBudget !== 'number' || !Number.isFinite(inputBudget)) {
    errors.push('input_budget is missing or not a number');
  } else if (inputBudget <= 0) {
    errors.push(`input_budget must be positive, got ${inputBudget}`);
  }

  if (typeof outputBudget !== 'number' || !Number.isFinite(outputBudget)) {
    errors.push('output_budget is missing or not a number');
  } else if (outputBudget <= 0) {
    errors.push(`output_budget must be positive, got ${outputBudget}`);
  }

  const ceilings = config.ceilings || {};
  if (errors.length === 0) {
    if (typeof ceilings.max_input_tokens === 'number' && inputBudget > ceilings.max_input_tokens) {
      errors.push(`input_budget ${inputBudget} exceeds project ceiling ${ceilings.max_input_tokens}`);
    }
    if (typeof ceilings.max_output_tokens === 'number' && outputBudget > ceilings.max_output_tokens) {
      errors.push(`output_budget ${outputBudget} exceeds project ceiling ${ceilings.max_output_tokens}`);
    }
  }

  return { ok: errors.length === 0, errors, resolved };
}

function main() {
  const agentName = process.argv[2];
  const configPathArg = process.argv[3];
  if (!agentName) {
    console.error('Usage: node scripts/agent/validate-budget.js <agent> [config.yaml]');
    process.exit(1);
  }

  const { config } = lib.loadConfig(configPathArg);
  const result = validateBudget(config, agentName);

  if (!result.ok) {
    console.error(`FAIL: ${agentName}`);
    for (const e of result.errors) console.error(`  - ${e}`);
    process.exit(1);
  }

  console.log(`PASS: ${agentName} — input=${result.resolved.input_budget} output=${result.resolved.output_budget} provider=${result.resolved.provider}`);
  process.exit(0);
}

if (require.main === module) main();
module.exports = { validateBudget };
