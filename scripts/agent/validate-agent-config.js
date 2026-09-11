#!/usr/bin/env node
'use strict';

/*
 * Validates config/agents.(yaml|example.yaml) and the agents/*.md role
 * files: config parses, every required agent role file exists, every
 * configured agent name is known, and providers are recognized (or
 * explicitly flagged as unknown rather than silently accepted).
 *
 * Usage: node scripts/agent/validate-agent-config.js [path/to/config.yaml]
 * Exit 0 = valid. Exit 1 = validation failed (see stderr).
 */

const lib = require('./lib');

function main() {
  const configPathArg = process.argv[2];
  const errors = [];
  const warnings = [];

  let config;
  try {
    const loaded = lib.loadConfig(configPathArg);
    config = loaded.config;
    console.log(`Loaded config: ${loaded.path}`);
  } catch (err) {
    console.error(`FAIL: could not read/parse config: ${err.message}`);
    process.exit(1);
  }

  // 1. All required agent role files must exist.
  for (const name of lib.REQUIRED_AGENTS) {
    if (!lib.agentExists(name)) {
      errors.push(`missing role file: agents/${name}.md`);
    }
  }

  // 2. Every agent named under `agents:` in config must be a known role.
  const configuredAgents = Object.keys(config.agents || {});
  for (const name of configuredAgents) {
    if (!lib.REQUIRED_AGENTS.includes(name)) {
      errors.push(`unknown agent in config: "${name}" (not one of ${lib.REQUIRED_AGENTS.join(', ')})`);
    }
  }

  // 3. Providers must be known, or explicitly flagged.
  for (const name of lib.REQUIRED_AGENTS) {
    const resolved = lib.resolveAgentBudget(config, name);
    if (!resolved.provider) {
      errors.push(`${name}: no provider resolved (set defaults.provider or agents.${name}.provider)`);
    } else if (!lib.KNOWN_PROVIDERS.has(resolved.provider)) {
      warnings.push(`${name}: provider "${resolved.provider}" is not in the known set (${[...lib.KNOWN_PROVIDERS].join(', ')}) — allowed, but double-check it's intentional`);
    }
  }

  if (warnings.length) {
    console.log('Warnings:');
    for (const w of warnings) console.log(`  - ${w}`);
  }

  if (errors.length) {
    console.error('FAIL:');
    for (const e of errors) console.error(`  - ${e}`);
    process.exit(1);
  }

  console.log(`PASS: ${lib.REQUIRED_AGENTS.length} required agent role files present, config structurally valid.`);
  process.exit(0);
}

if (require.main === module) main();
module.exports = { main };
