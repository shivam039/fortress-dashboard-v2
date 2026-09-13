#!/usr/bin/env node
'use strict';

/*
 * FORTRESS "LUNA MISSES CLOSEOUT" Epic 1: unified-pipeline.js is the
 * module actually wired into agent.js's `auto-gates` command (the real
 * GH Actions path), but had no test file of its own before this one.
 * Covers only what this closeout touched: reviewerGate()/prGate()'s
 * verdict handling, including the two new verdicts reviewer-evidence.js
 * now emits (MERGEABLE_WITH_NOTES, BLOCKED) - not a full re-test of the
 * whole module.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { reviewerGate, prGate, createManifest, MANIFEST_FIELDS } = require('./unified-pipeline');

const BASE_MANIFEST = { docs_required: false, repair_count: 0, scope_status: 'PASS',
  tests: { status: 'PASS' }, eval_status: 'EVAL_PASS', eval_hard_failures: [], human_gate_status: 'VALID' };

test('reviewerGate: MERGEABLE proceeds to PR_GATE_PENDING when docs are not required', () => {
  const result = reviewerGate(BASE_MANIFEST, { verdict: 'MERGEABLE' });
  assert.equal(result.state, 'PR_GATE_PENDING');
  assert.equal(result.review_status, 'MERGEABLE');
});

test('reviewerGate: MERGEABLE_WITH_NOTES proceeds the same as MERGEABLE (a visible, non-blocking waiver)', () => {
  const result = reviewerGate(BASE_MANIFEST, { verdict: 'MERGEABLE_WITH_NOTES' });
  assert.equal(result.state, 'PR_GATE_PENDING');
  assert.equal(result.review_status, 'MERGEABLE_WITH_NOTES');
});

test('reviewerGate: NOT_MERGEABLE enters one repair attempt, then BLOCKED on a second failure', () => {
  const first = reviewerGate(BASE_MANIFEST, { verdict: 'NOT_MERGEABLE' });
  assert.equal(first.state, 'REPAIR_PENDING');
  assert.equal(first.repair_count, 1);

  const second = reviewerGate({ ...BASE_MANIFEST, repair_count: 1 }, { verdict: 'NOT_MERGEABLE' });
  assert.equal(second.state, 'BLOCKED');
});

test('reviewerGate: BLOCKED verdict short-circuits to BLOCKED without a repair attempt', () => {
  const result = reviewerGate(BASE_MANIFEST, { verdict: 'BLOCKED' });
  assert.equal(result.state, 'BLOCKED');
  assert.equal(result.repair_count, 0); // no repair attempt spent, unlike NOT_MERGEABLE
});

test('reviewerGate: an unrecognized verdict string still throws (governance stays closed by default)', () => {
  assert.throws(() => reviewerGate(BASE_MANIFEST, { verdict: 'LOOKS_FINE_TO_ME' }), /invalid reviewer verdict/);
});

test('prGate: MERGEABLE_WITH_NOTES is treated as review-ok, same as MERGEABLE_WITH_MINOR_FIXES', () => {
  const manifest = { ...BASE_MANIFEST, review_status: 'MERGEABLE_WITH_NOTES', docs_status: 'NOT_REQUIRED' };
  const result = prGate(manifest);
  assert.equal(result.state, 'AWAITING_HUMAN');
  assert.equal(result.auto_merge, false);
});

test('prGate: a BLOCKED review_status never reaches AWAITING_HUMAN', () => {
  const manifest = { ...BASE_MANIFEST, review_status: 'BLOCKED', docs_status: 'NOT_REQUIRED' };
  const result = prGate(manifest);
  assert.equal(result.state, 'BLOCKED_PR');
});

test('test_waiver is a real manifest field, not silently stripped by the save/pick allowlist', () => {
  assert.ok(MANIFEST_FIELDS.includes('test_waiver'));
  const manifest = createManifest({
    run_id: 'r1', task_id: 't1', agent: 'backend', provider_mode: 'MANUAL_EXPORT',
    test_waiver: { reason: 'hand-set for this test', categories: ['backend_logic'] },
  });
  assert.deepEqual(manifest.test_waiver, { reason: 'hand-set for this test', categories: ['backend_logic'] });
});

test('test_waiver defaults to null when not provided', () => {
  const manifest = createManifest({ run_id: 'r2', task_id: 't2', agent: 'docs', provider_mode: 'MANUAL_EXPORT' });
  assert.equal(manifest.test_waiver, null);
});
