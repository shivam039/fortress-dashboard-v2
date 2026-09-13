#!/usr/bin/env node
'use strict';

/*
 * FORTRESS-NEXT Epic 20: proves (does not fix) a real gap in
 * reviewer-evidence.js. Run with:
 *   node --test scripts/agent/reviewer-evidence-gap.test.js
 *
 * reviewer-evidence.js has been reported as "the one specialist role with
 * a real pipeline hook" but had never actually been shown to catch
 * anything - only shown to exist and be invoked. This test constructs a
 * synthetic fixture that reintroduces the exact bug class fixed in PR #67
 * (fix(research): anchor scanner returns to scan date, commit e38d076):
 * backtest_top_picks() originally used `latest = float(data.iloc[-1])`
 * (the CURRENT/latest price) as the baseline for a forward return
 * measured FROM a past scan date, instead of anchoring to the scan-date
 * candle itself - silently measuring the wrong window. PR #67's fix
 * (_anchored_forward_return()) shipped with a real regression test
 * (tests/backend/test_stock_scanner_backtest.py).
 *
 * This fixture represents a hypothetical follow-up diff that reverts to
 * the pre-#67 latest-price baseline inside engine/stock_scanner/logic.py,
 * with NO regression test change - a real diff would still pass the
 * existing test suite (nothing in it exercises the reintroduced bug,
 * same as before PR #67 existed) and would plausibly pass static eval
 * too, since neither performs semantic/diff-content analysis.
 *
 * Result, as of this test: reviewer-evidence.js's createReview() ONLY
 * checks (a) changed_files is non-empty, (b) testReport.status === 'PASS',
 * (c) evalReport.status in [PASS, WARN] with no hard_failures. It never
 * reads the diff content, so it has no way to notice "a function that
 * used to anchor to a point-in-time value now doesn't, and no test
 * changed alongside it." It returns MERGEABLE.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createReview } = require('./reviewer-evidence');

test('KNOWN GAP: reviewer-evidence.js passes a diff reintroducing the PR #67 bug class with no new test', () => {
  // Synthetic fixture: the diff only touches the scanner logic file (the
  // exact file PR #67 fixed), reverting its baseline back to "latest
  // price" - no test file is part of changed_files, mirroring a
  // regression that would silently reintroduce the bug PR #67 fixed.
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
  // anchoring fix" either.
  const evalReport = { status: 'PASS', hard_failures: [] };

  const result = createReview({ manifest, testReport, evalReport, artifactDir: require('os').tmpdir() });

  // This assertion documents the GAP, not a spec we want to keep: it
  // currently passes when a P0 review process arguably should not have.
  // If reviewer-evidence.js is later taught to require a test-file change
  // alongside changed core-logic files (the proposal below), THIS
  // ASSERTION SHOULD FLIP to 'NOT_MERGEABLE' and this test should be
  // updated accordingly - do not "fix" this test by asserting the
  // opposite without also fixing reviewer-evidence.js itself.
  assert.equal(result.verdict, 'MERGEABLE');
  assert.deepEqual(result.findings, []);

  // --- Proposed fix (NOT implemented here, pending review) ---
  // reviewer-evidence.js could additionally require: for any changed file
  // matching a configurable "core logic" allowlist/pattern (e.g.
  // engine/**/logic.py, engine/**/scoring.py), at least one changed file
  // in manifest.changed_files must be a test file (tests/**/test_*.py)
  // that imports or references a symbol touched in that logic file's
  // diff - or, as a cheaper first pass, simply: any changed
  // engine/**/logic.py file requires a corresponding tests/backend/*
  // change somewhere in the same manifest.changed_files, else push a
  // finding ('Core logic file changed with no corresponding test file
  // change') and verdict NOT_MERGEABLE. This would have caught this
  // fixture (logic.py changed, no tests/backend/* entry in changed_files)
  // without needing real diff-content parsing.
});
