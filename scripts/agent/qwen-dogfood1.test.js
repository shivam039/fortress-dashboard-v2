const test = require('node:test');
const assert = require('node:assert/strict');
const { TASKS, createPlan, checkProvider, validateResult, scoreTask, fingerprint } = require('./qwen-dogfood1');

test('plan has three balanced, qwen-only bounded tasks', () => {
  const plan = createPlan({ baselineSha: 'abc123' });
  assert.equal(plan.baseline_sha, 'abc123');
  assert.deepEqual(plan.tasks.map((task) => task.id), ['A', 'B', 'C']);
  assert.ok(plan.tasks.every((task) => task.provider === 'qwen_web' && task.repair_limit === 1));
});

test('provider readiness fails closed without credentials and never falls back', async () => {
  const result = await checkProvider({ baseUrl: '', token: '' });
  assert.equal(result.classification, 'QWEN_PROVIDER_UNAVAILABLE');
  assert.equal(result.ready, false);
});

test('provider result governance and scope are measured, not repaired', () => {
  const clean = validateResult({ provider: 'qwen_web', production_access: false, auto_merge: false, changed_files: ['frontend/src/app/paper-trading/page.tsx'] }, 'A');
  assert.equal(clean.scope, 'CLEAN');
  const violation = validateResult({ provider: 'qwen_web', production_access: true, auto_merge: false, changed_files: ['engine/main.py'] }, 'A');
  assert.equal(violation.hard_failure, true);
  assert.equal(violation.scope, 'MAJOR_SCOPE_VIOLATION');
});

test('scoring requires all gates and records rescue as failure', () => {
  assert.deepEqual(scoreTask({ acceptance: true, tests: true }), { score: 25, result: 'FAIL' });
  assert.equal(scoreTask({ acceptance: true, tests: true, scope: 'CLEAN', reviewer: 'MERGEABLE', intervention: 'RESCUE', hallucination: 'NONE' }).result, 'FAIL');
  assert.equal(scoreTask({ acceptance: true, tests: true, scope: 'CLEAN', reviewer: 'MERGEABLE', intervention: 'NONE', hallucination: 'NONE', repository_understanding: true }).result, 'PASS');
});

test('task fingerprints are deterministic', () => assert.equal(fingerprint(TASKS[0]), fingerprint(TASKS[0])));
