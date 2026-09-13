#!/usr/bin/env node
'use strict';

/*
 * FORTRESS "LUNA MISSES CLOSEOUT" Epic 1 (was FORTRESS-NEXT Epic 20's
 * P0 finding): this test used to PROVE a real gap in reviewer-evidence.js
 * and deliberately did not fix it. That gap is now fixed - see
 * reviewer-evidence.js's evidenceGaps()/EVIDENCE_REQUIREMENTS. This file
 * is kept, per the closeout's explicit instruction not to delete or
 * weaken the regression test that proved the gap, only to fix the
 * underlying behavior and flip this assertion.
 *
 * Run with: node --test scripts/agent/reviewer-evidence-gap.test.js
 *
 * Background: reviewer-evidence.js was reported as "the one specialist
 * role with a real pipeline hook" but had never actually been shown to
 * catch anything - only shown to exist and be invoked. This fixture
 * reintroduces the exact bug class fixed in PR #67 (fix(research):
 * anchor scanner returns to scan date, commit e38d076):
 * backtest_top_picks() originally used `latest = float(data.iloc[-1])`
 * (the CURRENT/latest price) as the baseline for a forward return
 * measured FROM a past scan date, instead of anchoring to the scan-date
 * candle itself - silently measuring the wrong window. PR #67's fix
 * (_anchored_forward_return()) shipped with a real regression test
 * (tests/backend/test_stock_scanner_backtest.py).
 *
 * The fixture models a hypothetical follow-up diff that reverts to the
 * pre-#67 latest-price baseline inside engine/stock_scanner/logic.py,
 * with NO regression test change - a real diff would still pass the
 * existing test suite (nothing in it exercises the reintroduced bug,
 * same as before PR #67 existed) and would plausibly pass static eval
 * too, since neither performs semantic/diff-content analysis. That is
 * exactly why the fix does NOT rely on diff-content parsing either: it
 * classifies engine/stock_scanner/logic.py as 'backend_logic' and
 * requires at least one tests/backend/* file in the same changed-file
 * list - absent here, so it now finds the gap.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createReview } = require('./reviewer-evidence');

test('FIXED: reviewer-evidence.js now blocks a diff reintroducing the PR #67 bug class with no new test', () => {
  const manifest = {
    run_id: 'epic20-fixture-pr67-regression',
    changed_files: ['engine/stock_scanner/logic.py'],
    production_impact: 'MEDIUM',
    docs_required: false,
  };
  // The existing test suite still passes: nothing in it exercises the
  // reintroduced latest-price-as-baseline bug, exactly as was true before
  // PR #67 added test_stock_scanner_backtest.py in the same diff as its fix.
  const testReport = { status: 'PASS' };
  // Static eval has no semantic understanding of "this diff removed an
  // anchoring fix" either - the fix does not depend on eval catching this.
  const evalReport = { status: 'PASS', hard_failures: [] };

  const result = createReview({ manifest, testReport, evalReport, artifactDir: require('os').tmpdir() });

  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(
    result.findings.some((f) => f.includes('backend_logic') && f.includes('backend test evidence')),
    `expected a backend_logic evidence-gap finding, got: ${JSON.stringify(result.findings)}`
  );
});

test('the same fixture becomes eligible for MERGEABLE once matching test evidence is added', () => {
  // This is what PR #67's REAL diff looked like: the logic file change
  // plus its own new regression test in the same changed-file list.
  const manifest = {
    run_id: 'epic20-fixture-pr67-fixed',
    changed_files: ['engine/stock_scanner/logic.py', 'tests/backend/test_stock_scanner_backtest.py'],
    production_impact: 'MEDIUM',
    docs_required: false,
  };
  const testReport = { status: 'PASS', commands: ['pytest -q'] };
  const evalReport = { status: 'PASS', hard_failures: [] };

  const result = createReview({ manifest, testReport, evalReport, artifactDir: require('os').tmpdir() });

  assert.equal(result.verdict, 'MERGEABLE');
  assert.deepEqual(result.findings, []);
});
