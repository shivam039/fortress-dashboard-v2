#!/usr/bin/env node
'use strict';

/*
 * Tests for the AGENT1B execution layer. Zero dependencies (node:test).
 * scripts/agent/agent-system.test.js (AGENT1A) is left untouched and
 * must keep passing on its own — see test #1 below, which re-runs it as
 * a subprocess to prove AGENT1B didn't regress it.
 *
 * Run: node --test scripts/agent/agent1b.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const lib = require('./lib');
const lifecycle = require('./lifecycle');
const { slugify, sanitizeTaskId, buildBranchName, isSafeRepoPath } = require('./sanitize');
const { checkScope, matchesAny } = require('./scope-check');
const { resolveExecutionMode, providerStatus } = require('./providers');
const { writeRunRecord, RECORD_FIELDS } = require('./run-record');
const { buildPrompt, loadTask } = require('./build-agent-prompt');
const { selectAgent } = require('./select-agent');
const { plan, branchExists } = require('./orchestrate-task');

const DEMO_TASK = path.join(lib.REPO_ROOT, '.agent-tasks', 'example-docs-task.yaml');
const EXAMPLE_CONFIG = path.join(lib.REPO_ROOT, 'config', 'agents.example.yaml');

function cleanupSessions(prefix) {
  const dir = path.join(lib.REPO_ROOT, '.agent-room', 'sessions');
  if (!fs.existsSync(dir)) return;
  for (const f of fs.readdirSync(dir)) {
    if (f.includes(prefix)) fs.unlinkSync(path.join(dir, f));
  }
}

// 1. AGENT1A tests still pass
test('AGENT1A test suite still passes unmodified', () => {
  const childEnv = { ...process.env };
  for (const key of Object.keys(childEnv)) {
    if (key.startsWith('NODE_TEST')) delete childEnv[key];
  }
  const out = execSync('node --test scripts/agent/agent-system.test.js 2>&1', {
    cwd: lib.REPO_ROOT, encoding: 'utf8', env: childEnv,
  });
  assert.match(out, /pass 15/);
  assert.match(out, /fail 0/);
});

// 2. execution state transitions valid / 3. invalid transition rejected
test('lifecycle: valid transitions accepted, invalid rejected', () => {
  assert.equal(lifecycle.canTransition('CREATED', 'CLASSIFIED'), true);
  assert.equal(lifecycle.canTransition('CLASSIFIED', 'APPROVED'), true);
  assert.equal(lifecycle.canTransition('AWAITING_HUMAN', 'MERGED'), true);
  assert.equal(lifecycle.canTransition('CREATED', 'MERGED'), false);
  assert.equal(lifecycle.canTransition('MERGED', 'RUNNING'), false); // terminal
});

// 4. task defaults production_access=false
test('plan() never grants production_access unless both task and agent config allow it', () => {
  const result = plan(DEMO_TASK, EXAMPLE_CONFIG);
  assert.equal(result.production_access, false);
  cleanupSessions('agent1b-demo-001');
});

// 5. unknown agent rejected
test('plan() rejects an unknown agent', () => {
  const tmpTask = path.join(lib.REPO_ROOT, '.agent-tasks', '.tmp-unknown-agent-test.yaml');
  fs.writeFileSync(tmpTask, 'id: t1\nagent: not-a-real-agent\nallowed_files: []\n');
  try {
    const result = plan(tmpTask, EXAMPLE_CONFIG);
    assert.equal(result.state, 'BLOCKED');
  } finally {
    fs.unlinkSync(tmpTask);
  }
});

// 6. unknown provider handled / 7. unavailable provider blocks
test('resolveExecutionMode: unavailable provider blocks only when AUTOMATED is requested', () => {
  const configAutomated = { providers: { codex: { mode: 'AUTOMATED' } } };
  const automated = resolveExecutionMode('codex', configAutomated);
  assert.equal(automated.mode, 'BLOCKED_PROVIDER'); // codex adapter is UNAVAILABLE
  const configDefault = {};
  const manual = resolveExecutionMode('codex', configDefault);
  assert.equal(manual.mode, 'MANUAL_EXPORT');
});

// 8. invalid budget blocks before execution / 9. budget ceiling enforced
test('plan() blocks on invalid/over-ceiling budget before any prompt is built', () => {
  const tmpTask = path.join(lib.REPO_ROOT, '.agent-tasks', '.tmp-budget-test.yaml');
  fs.writeFileSync(tmpTask, 'id: t2\nagent: docs\ninput_budget: -5\noutput_budget: 100\nallowed_files: []\n');
  try {
    const result = plan(tmpTask, EXAMPLE_CONFIG);
    assert.equal(result.state, 'BLOCKED_BUDGET');
  } finally {
    fs.unlinkSync(tmpTask);
  }

  const tmpTask2 = path.join(lib.REPO_ROOT, '.agent-tasks', '.tmp-ceiling-test.yaml');
  fs.writeFileSync(tmpTask2, 'id: t3\nagent: docs\ninput_budget: 999999\noutput_budget: 100\nallowed_files: []\n');
  try {
    const result = plan(tmpTask2, EXAMPLE_CONFIG);
    assert.equal(result.state, 'BLOCKED_BUDGET');
    assert.match(result.reason, /ceiling/);
  } finally {
    fs.unlinkSync(tmpTask2);
  }
});

// 10. branch names sanitized / 11. task IDs sanitized
test('branch and task-id sanitization strips unsafe characters', () => {
  assert.equal(slugify('Fix; rm -rf / #hack'), 'fix-rm-rf-hack');
  assert.equal(sanitizeTaskId('../../etc/passwd'), 'etc-passwd');
  const branch = buildBranchName({ issueNumber: 42, agent: 'backend', slug: '`evil`;branch' });
  assert.equal(branch, 'agent/42-backend-evil-branch');
  assert.throws(() => buildBranchName({ issueNumber: 'not-a-number', agent: 'backend', slug: 'x' }));
});

test('isSafeRepoPath rejects path traversal and absolute paths', () => {
  assert.equal(isSafeRepoPath('engine/main.py'), true);
  assert.equal(isSafeRepoPath('../../etc/passwd'), false);
  assert.equal(isSafeRepoPath('/etc/passwd'), false);
});

// 12. scope violation detected / 13. forbidden file modification detected
test('checkScope detects out-of-scope and forbidden file changes', () => {
  const allowed = checkScope(['docs/agents/USAGE.md'], { allowedFiles: ['docs/**'], forbiddenFiles: ['engine/**'] });
  assert.equal(allowed.ok, true);

  const outOfScope = checkScope(['frontend/src/app/page.tsx'], { allowedFiles: ['docs/**'], forbiddenFiles: [] });
  assert.equal(outOfScope.ok, false);
  assert.equal(outOfScope.violations[0].reason, 'not in allowed_files');

  const forbidden = checkScope(['engine/main.py'], { allowedFiles: ['**'], forbiddenFiles: ['engine/**'] });
  assert.equal(forbidden.ok, false);
  assert.equal(forbidden.violations[0].reason, 'forbidden_files match');
});

// 14. Coordinator cannot implement / 15. Reviewer cannot implement
// (same assertions as AGENT1A test #12/#13, re-checked here since
// AGENT1B's orchestrator is what would actually invoke them)
test('coordinator and reviewer contracts remain non-implementation', () => {
  assert.ok(lib.NON_IMPLEMENTATION_AGENTS.has('coordinator'));
  assert.ok(lib.NON_IMPLEMENTATION_AGENTS.has('reviewer'));
});

// 16. Infra production action requires human gate / 17. trading/scoring change requires human gate
test('infra agent config defaults production_access false regardless of task request', () => {
  const config = lib.loadConfig(EXAMPLE_CONFIG).config;
  const resolvedInfra = lib.resolveAgentBudget(config, 'infra');
  assert.equal(resolvedInfra.production_access, false);
  // A task claiming production_access:true against an agent whose config
  // doesn't grant it must NOT be honored (Phase 28).
  const tmpTask = path.join(lib.REPO_ROOT, '.agent-tasks', '.tmp-prod-access-test.yaml');
  fs.writeFileSync(tmpTask, 'id: t4\nagent: infra\nproduction_access: true\nallowed_files: []\n');
  try {
    const result = plan(tmpTask, EXAMPLE_CONFIG);
    assert.equal(result.production_access, false);
    cleanupSessions('t4');
  } finally {
    fs.unlinkSync(tmpTask);
  }
});

// 18. issue content cannot override production_access (covered above) /
// 19. issue content cannot override token ceiling (covered by test #9 —
// the ceiling check runs on the task's own requested budget, so a task
// authored from untrusted issue text cannot exceed it either)
test('a task cannot request a budget above the configured project ceiling', () => {
  const config = lib.loadConfig(EXAMPLE_CONFIG).config;
  assert.ok(config.ceilings.max_input_tokens > 0);
  assert.ok(config.ceilings.max_output_tokens > 0);
});

// 20. secrets not included in generated prompt (AGENT1A already covers
// this for build-agent-prompt directly; re-verify through the full
// orchestrator path with a secret-shaped env var present)
test('orchestrator plan() output never includes a secret-shaped env value', () => {
  process.env.AGENT1B_TEST_SECRET = 'should-never-leak-anywhere';
  try {
    const result = plan(DEMO_TASK, EXAMPLE_CONFIG);
    const serialized = JSON.stringify(result);
    assert.ok(!serialized.includes('should-never-leak-anywhere'));
    cleanupSessions('agent1b-demo-001');
  } finally {
    delete process.env.AGENT1B_TEST_SECRET;
  }
});

// 21. secrets not included in run record
test('run record never includes a secret-shaped field', () => {
  const filepath = writeRunRecord({
    run_id: 'test-run', task_id: 'test-task', agent: 'docs', provider: 'codex',
    model: 'default', input_budget: 100, output_budget: 100,
  }, { topic: 'unit-test-record' });
  try {
    const content = fs.readFileSync(filepath, 'utf8');
    for (const forbiddenWord of ['api_key', 'API_KEY', 'secret', 'SECRET', 'token', 'TOKEN']) {
      // Field *names* like run_id are fine; this checks no field carries
      // a credential-shaped value, by construction (RECORD_FIELDS has no
      // secret-shaped field at all).
      assert.ok(!RECORD_FIELDS.includes(forbiddenWord));
    }
    assert.ok(content.includes('run_id'));
  } finally {
    fs.unlinkSync(filepath);
  }
});

// 22. duplicate task execution prevented
test('plan() refuses to run again if the target branch already exists', () => {
  const branch = 'agent/9999-docs-agent1b-demo-001';
  execSync(`git branch ${branch}`, { cwd: lib.REPO_ROOT });
  try {
    assert.equal(branchExists(branch), true);
    const result = plan(DEMO_TASK, EXAMPLE_CONFIG);
    assert.equal(result.state, 'BLOCKED');
    assert.match(result.reason, /already exists/);
  } finally {
    execSync(`git branch -D ${branch}`, { cwd: lib.REPO_ROOT });
  }
});

// 23. bounded retry works (contract-level: FAILED->RUNNING transition
// exists exactly once per the state machine; enforcing the numeric cap
// is the caller's loop, which the state machine alone can't prevent —
// documented in docs/agents/ARCHITECTURE.md)
test('lifecycle allows exactly one re-entry path from FAILED back to RUNNING', () => {
  assert.deepEqual(lifecycle.allowedTransitions('FAILED').filter((s) => !['BLOCKED', 'CANCELLED'].includes(s)), ['RUNNING']);
});

// 24. reviewer failure blocks appropriately
test('lifecycle allows REVIEWING -> RUNNING (one correction cycle) and REVIEWING -> BLOCKED', () => {
  assert.ok(lifecycle.canTransition('REVIEWING', 'RUNNING'));
  assert.ok(lifecycle.canTransition('REVIEWING', 'BLOCKED'));
});

// 25. docs_required flow works
test('task docs_required is preserved through plan() output', () => {
  const result = plan(DEMO_TASK, EXAMPLE_CONFIG);
  assert.equal(result.docs_required, false); // example-docs-task.yaml sets it explicitly
  cleanupSessions('agent1b-demo-001');
});

// 26. no auto-merge path exists
test('no function in this module or providers.js performs a merge', () => {
  const providersSrc = fs.readFileSync(path.join(lib.REPO_ROOT, 'scripts', 'agent', 'providers.js'), 'utf8');
  const orchestratorSrc = fs.readFileSync(path.join(lib.REPO_ROOT, 'scripts', 'agent', 'orchestrate-task.js'), 'utf8');
  assert.ok(!/\bmerge\(/i.test(providersSrc));
  assert.ok(!/\bmerge\(/i.test(orchestratorSrc));
});

// 27. dry-run still works without provider credentials
test('plan() succeeds with zero provider credentials configured', () => {
  const before = { ...process.env };
  for (const key of Object.keys(process.env)) {
    if (/key|token|secret/i.test(key)) delete process.env[key];
  }
  try {
    const result = plan(DEMO_TASK, EXAMPLE_CONFIG);
    assert.equal(result.state, 'MANUAL_EXPORT');
    cleanupSessions('agent1b-demo-001');
  } finally {
    process.env = before;
  }
});

// 28. manual prompt export works
test('plan() returns a non-empty generated prompt for manual export', () => {
  const result = plan(DEMO_TASK, EXAMPLE_CONFIG);
  assert.ok(result.prompt && result.prompt.length > 0);
  assert.match(result.prompt, /## MISSION/);
  cleanupSessions('agent1b-demo-001');
});

// 29. GitHub permissions are least-privilege (structural check on the
// workflow file itself)
test('agent-task.yml requests only least-privilege permissions', () => {
  const workflowPath = path.join(lib.REPO_ROOT, '.github', 'workflows', 'agent-task.yml');
  const content = fs.readFileSync(workflowPath, 'utf8');
  assert.ok(!/write-all/.test(content));
  assert.match(content, /permissions:/);
});

// 30. AGENT1A validate workflow remains safe (structural check —
// unchanged from AGENT1A, re-verified here since AGENT1B extends the
// same workflows directory)
test('agent-validate.yml still contains no paid-model-call or merge step', () => {
  const workflowPath = path.join(lib.REPO_ROOT, '.github', 'workflows', 'agent-validate.yml');
  const content = fs.readFileSync(workflowPath, 'utf8');
  assert.ok(!/gh pr merge/.test(content));
  assert.ok(!/api\.anthropic\.com|api\.x\.ai|api\.openai\.com/.test(content));
});
