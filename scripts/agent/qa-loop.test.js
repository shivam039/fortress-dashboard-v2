const test = require('node:test');
const assert = require('node:assert/strict');
const { createLoop, advanceLoop, buildPRBody } = require('./qa-loop');

const finding = (overrides = {}) => ({ finding_id: 'F-1', run_id: 'R-1', environment: 'staging', surface: 'Scanner', scenario: 'stale route renders', status: 'FAIL', severity: 'QA3', observed: 'HTTP 500 from handler', expected: 'page renders', route: '/screener', evidence: { message: 'safe' }, ...overrides });

test('controlled E2E demo triages, gates, and reaches PR only after all gates', () => {
  let loop = createLoop(finding());
  assert.equal(loop.state, 'WAITING_APPROVAL');
  for (const event of ['approve', 'implementation_complete', 'tests_pass', 'qa_pass', 'eval_pass', 'review_pass']) loop = advanceLoop(loop, event);
  assert.equal(loop.state, 'READY_FOR_PR');
  assert.equal(loop.auto_merge, false);
  assert.match(buildPRBody(finding(), loop), /Manual merge/);
});

test('financial semantics block automatic product decisions', () => {
  const loop = createLoop(finding({ scenario: 'Oracle BUY score implies quantity', observed: 'wrong allocation' }));
  assert.equal(loop.classification, 'HUMAN_PRODUCT_DECISION_REQUIRED');
  assert.equal(loop.state, 'AWAITING_HUMAN');
});

test('duplicate findings reuse the canonical open task', () => {
  const first = createLoop(finding());
  const second = createLoop(finding({ finding_id: 'F-2' }), [{ id: 'TASK-1', fingerprint: first.fingerprint, state: first.state }]);
  assert.equal(second.duplicate, true);
  assert.equal(second.canonical_id, 'TASK-1');
});

test('production mutations are human gated', () => {
  const loop = createLoop(finding({ environment: 'production', action_class: 'SAFE_TEST_MUTATION' }));
  assert.equal(loop.classification, 'HUMAN_GATED_PRODUCTION_CHANGE');
  assert.equal(loop.state, 'AWAITING_HUMAN');
});

test('one bounded repair cycle cannot recurse', () => {
  let loop = createLoop(finding());
  loop = advanceLoop(loop, 'approve');
  loop = advanceLoop(loop, 'implementation_complete');
  loop = advanceLoop(loop, 'tests_fail');
  loop = advanceLoop(loop, 'implementation_complete');
  loop = advanceLoop(loop, 'tests_fail');
  assert.equal(loop.state, 'BLOCKED_TESTS');
  assert.equal(loop.repair_cycles, 1);
});
