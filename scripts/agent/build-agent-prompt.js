#!/usr/bin/env node
'use strict';

/*
 * Combines: shared contract (embedded in each agents/*.md) + specialist
 * role file + task payload + resolved budget + repo constraints into one
 * generated prompt. Dry-run only — never calls a model API, never reads
 * process.env, never reads any .env* file. That last part is structural,
 * not a convention: this script has no code path that touches process.env
 * or dotenv-shaped files, so it cannot leak a secret into the generated
 * prompt even by accident.
 *
 * Usage: node scripts/agent/build-agent-prompt.js <agent> <task.yaml> [config.yaml]
 */

const fs = require('fs');
const path = require('path');
const lib = require('./lib');
const { selectAgent } = require('./select-agent');

const REPO_CONSTRAINTS = [
  'Do not broad-audit the repo by default — task-specific files, the recent diff, and directly relevant tests/docs only.',
  'Do not modify files outside the allowed_files scope without a new Coordinator classification.',
  'production_access defaults to false; a task requesting production access requires explicit human approval (see docs/agents/GOVERNANCE.md).',
  'Docs describe current merged reality, not planned behavior.',
];

function loadTask(taskPath) {
  const text = fs.readFileSync(taskPath, 'utf8');
  return lib.parseMiniYaml(text);
}

function buildPrompt({ agentName, roleFileText, task, resolved }) {
  const lines = [];
  lines.push(`# Generated agent prompt: ${agentName}`);
  lines.push('');
  lines.push('## Role contract');
  lines.push(roleFileText.trim());
  lines.push('');
  lines.push('## Task');
  lines.push(`id: ${task.id || '(none)'}`);
  lines.push(`title: ${task.title || '(none)'}`);
  if (task.acceptance_criteria) {
    lines.push(`acceptance_criteria: ${JSON.stringify(task.acceptance_criteria)}`);
  }
  lines.push('');
  lines.push('## Scope');
  lines.push(`allowed_files: ${JSON.stringify(task.allowed_files || [])}`);
  lines.push(`forbidden_files: ${JSON.stringify(task.forbidden_files || [])}`);
  lines.push('');
  lines.push('## Budget');
  lines.push(`provider: ${resolved.provider}`);
  lines.push(`model: ${resolved.model}`);
  lines.push(`input_budget: ${resolved.input_budget}`);
  lines.push(`output_budget: ${resolved.output_budget}`);
  lines.push('');
  lines.push('## Repo constraints');
  for (const c of REPO_CONSTRAINTS) lines.push(`- ${c}`);
  lines.push('');
  lines.push('## Stop condition');
  lines.push('Stop once the task\'s acceptance criteria are met and this role\'s STOP CONDITION is reached — do not expand scope.');
  return lines.join('\n');
}

function main() {
  const [agentName, taskPath, configPathArg] = process.argv.slice(2);
  if (!agentName || !taskPath) {
    console.error('Usage: node scripts/agent/build-agent-prompt.js <agent> <task.yaml> [config.yaml]');
    process.exit(1);
  }

  const { config } = lib.loadConfig(configPathArg);
  let resolved;
  try {
    resolved = selectAgent(agentName, config);
  } catch (err) {
    console.error(`FAIL: ${err.message}`);
    process.exit(1);
  }

  const roleFilePath = path.join(lib.AGENTS_DIR, `${agentName}.md`);
  const roleFileText = fs.readFileSync(roleFilePath, 'utf8');
  const task = loadTask(taskPath);
  const prompt = buildPrompt({ agentName, roleFileText, task, resolved });

  const dryRunSummary = {
    selected_agent: agentName,
    resolved_provider: resolved.provider,
    resolved_model: resolved.model,
    input_budget: resolved.input_budget,
    output_budget: resolved.output_budget,
    allowed_files: task.allowed_files || [],
    requires_human_gate: task.production_access === true || resolved.production_access === true,
  };

  console.log('--- DRY RUN SUMMARY ---');
  console.log(JSON.stringify(dryRunSummary, null, 2));
  console.log('--- GENERATED PROMPT ---');
  console.log(prompt);
  process.exit(0);
}

if (require.main === module) main();
module.exports = { buildPrompt, loadTask };
