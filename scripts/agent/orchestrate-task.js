#!/usr/bin/env node
'use strict';

/*
 * AGENT1B pipeline driver (Phases 3, 6, 11, 12, 31, 37).
 *
 * `plan` is the only mode this ships with real behavior for: it runs
 * classification -> budget gate -> provider mode resolution -> branch
 * naming -> prompt build -> run record, and stops at MANUAL_EXPORT
 * (or BLOCKED_BUDGET / BLOCKED_PROVIDER). No specialist "executes"
 * automatically here — see scripts/agent/providers.js and
 * docs/agents/PROVIDERS.md for why, and USAGE.md for the manual flow
 * a human/external agent session follows after `plan`.
 *
 * `apply` is for after a human/external agent has produced a diff on
 * the planned branch: it runs scope-check against what actually
 * changed, then reports pass/fail. It does not run tests itself (task-
 * defined test commands are the caller's responsibility — see
 * docs/agents/USAGE.md) and it never invokes a shell command derived
 * from task/issue text (Phase 29).
 *
 * Usage:
 *   node scripts/agent/orchestrate-task.js plan <task.yaml> [config.yaml]
 *   node scripts/agent/orchestrate-task.js apply <task.yaml> [config.yaml]
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const lib = require('./lib');
const { selectAgent } = require('./select-agent');
const { buildPrompt, loadTask } = require('./build-agent-prompt');
const { resolveExecutionMode } = require('./providers');
const { buildBranchName, sanitizeTaskId } = require('./sanitize');
const { checkScope, getChangedFiles } = require('./scope-check');
const { writeRunRecord } = require('./run-record');
const { canTransition } = require('./lifecycle');

function nowIso() {
  return new Date().toISOString();
}

function branchExists(branchName) {
  try {
    execSync(`git rev-parse --verify ${JSON.stringify(branchName)}`, { stdio: 'ignore' });
    return true;
  } catch (err) {
    return false;
  }
}

function plan(taskPath, configPathArg) {
  const task = loadTask(taskPath);
  const { config } = lib.loadConfig(configPathArg);
  const taskId = sanitizeTaskId(task.id || path.basename(taskPath, '.yaml'));

  // Coordinator classification is reused as-is (agent:auto resolves to
  // the task's declared agent for now — a free-text classifier is out of
  // scope, see agents/coordinator.md's REQUIRED CONTEXT).
  const agentName = task.agent && task.agent !== 'auto' ? task.agent : null;
  if (!agentName) {
    return { state: 'BLOCKED', reason: 'task.agent is "auto" or missing — Coordinator classification into a specific agent is not automated in AGENT1B; set task.agent explicitly.' };
  }
  if (!lib.REQUIRED_AGENTS.includes(agentName)) {
    return { state: 'BLOCKED', reason: `unknown agent: "${agentName}"` };
  }

  let selected;
  try {
    selected = selectAgent(agentName, config);
  } catch (err) {
    return { state: 'BLOCKED', reason: err.message };
  }

  // Task-level overrides (input_budget/output_budget) are validated the
  // same way as config-level ones — an override cannot exceed the
  // project ceiling either (Phase 11, and Phase 28: task content cannot
  // override the ceiling).
  const inputBudget = task.input_budget != null ? task.input_budget : selected.input_budget;
  const outputBudget = task.output_budget != null ? task.output_budget : selected.output_budget;
  const ceilings = config.ceilings || {};
  if (inputBudget <= 0 || outputBudget <= 0) {
    return { state: 'BLOCKED_BUDGET', reason: 'input/output budget must be positive' };
  }
  if (typeof ceilings.max_input_tokens === 'number' && inputBudget > ceilings.max_input_tokens) {
    return { state: 'BLOCKED_BUDGET', reason: `input_budget ${inputBudget} exceeds project ceiling ${ceilings.max_input_tokens}` };
  }
  if (typeof ceilings.max_output_tokens === 'number' && outputBudget > ceilings.max_output_tokens) {
    return { state: 'BLOCKED_BUDGET', reason: `output_budget ${outputBudget} exceeds project ceiling ${ceilings.max_output_tokens}` };
  }

  // production_access: task can only ever LOWER risk, never raise it —
  // it can set false when the resolved agent default is more permissive,
  // but it cannot set true unless the agent's own config already allows
  // it (Phase 28: task/issue content cannot override production_access).
  const productionAccess = task.production_access === true && selected.production_access === true;

  const providerName = task.provider || selected.provider;
  const providerResolution = resolveExecutionMode(providerName, config);

  const issueNumber = task.issue_number || 1; // 1 is a safe placeholder for local dry-run plans with no real issue
  const branch = task.branch_name || buildBranchName({ issueNumber, agent: agentName, slug: task.id || taskId });

  if (branchExists(branch)) {
    return { state: 'BLOCKED', reason: `branch "${branch}" already exists — refusing to duplicate a run (Phase 31 idempotency); resume or delete it first.` };
  }

  const roleFileText = fs.readFileSync(path.join(lib.AGENTS_DIR, `${agentName}.md`), 'utf8');
  const prompt = buildPrompt({ agentName, roleFileText, task, resolved: { ...selected, provider: providerName } });

  const runId = `${taskId}-${Date.now()}`;
  const record = writeRunRecord({
    run_id: runId,
    task_id: task.id || taskId,
    issue: task.issue_number || null,
    agent: agentName,
    provider: providerName,
    model: selected.model,
    input_budget: inputBudget,
    output_budget: outputBudget,
    started: nowIso(),
    finished: null,
    branch,
    files_changed: [],
    tests: null,
    review_verdict: null,
    docs_impact: task.docs_required != null ? task.docs_required : 'auto',
    pr: null,
    final_state: providerResolution.mode === 'BLOCKED_PROVIDER' ? 'BLOCKED' : 'CLASSIFIED',
  }, { topic: `agent1b-plan-${taskId}` });

  if (providerResolution.mode === 'BLOCKED_PROVIDER') {
    return { state: 'BLOCKED_PROVIDER', reason: providerResolution.reason, run_record: record };
  }

  return {
    state: providerResolution.mode === 'AUTOMATED' ? 'RUNNING' : 'MANUAL_EXPORT',
    run_id: runId,
    task_id: task.id || taskId,
    issue_number: task.issue_number || null,
    agent: agentName,
    provider: providerName,
    provider_status: providerResolution.status,
    provider_mode: providerResolution.mode,
    model: selected.model,
    input_budget: inputBudget,
    output_budget: outputBudget,
    production_access: productionAccess,
    branch,
    allowed_files: task.allowed_files || [],
    forbidden_files: task.forbidden_files || [],
    docs_required: task.docs_required != null ? task.docs_required : 'auto',
    human_approval_required: task.human_approval_required !== false,
    run_record: record,
    next_step: providerResolution.mode === 'AUTOMATED'
      ? 'provider execution not implemented in AGENT1B — falls back to manual export until a future story wires up a real call'
      : `create branch "${branch}", run the generated prompt manually in ${providerName}, implement within allowed_files, then run: node scripts/agent/orchestrate-task.js apply ${path.relative(lib.REPO_ROOT, taskPath)}`,
    prompt,
  };
}

function apply(taskPath, configPathArg) {
  const task = loadTask(taskPath);
  const changed = getChangedFiles('main'); // compare against main, not just HEAD, to see the branch's full diff
  const result = checkScope(changed, {
    allowedFiles: task.allowed_files || [],
    forbiddenFiles: task.forbidden_files || [],
  });
  return { state: result.ok ? 'IMPLEMENTED' : 'BLOCKED_SCOPE', changed, ...result };
}

function main() {
  const [mode, taskPath, configPathArg] = process.argv.slice(2);
  if (!mode || !taskPath || !['plan', 'apply'].includes(mode)) {
    console.error('Usage: node scripts/agent/orchestrate-task.js <plan|apply> <task.yaml> [config.yaml]');
    process.exit(1);
  }
  const result = mode === 'plan' ? plan(taskPath, configPathArg) : apply(taskPath, configPathArg);
  const { prompt, ...summary } = result;
  console.log(JSON.stringify(summary, null, 2));
  if (prompt) {
    console.log('\n--- GENERATED PROMPT (manual export) ---\n');
    console.log(prompt);
  }
  const blockedStates = ['BLOCKED', 'BLOCKED_BUDGET', 'BLOCKED_PROVIDER', 'BLOCKED_SCOPE'];
  process.exit(blockedStates.includes(result.state) ? 1 : 0);
}

if (require.main === module) main();
module.exports = { plan, apply, branchExists };
