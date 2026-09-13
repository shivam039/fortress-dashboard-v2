#!/usr/bin/env node
'use strict';

/*
 * FORTRESS "LUNA MISSES CLOSEOUT" Epic 1: Reviewer evidence-policy tests.
 * Run with: node --test scripts/agent/reviewer-evidence.test.js
 *
 * Covers the 8 required scenarios plus the category classifier and the
 * "only a no-op diff check ran" detector. See reviewer-evidence-gap.test.js
 * for the real historical PR #67 regression proof (kept separately since
 * it documents a specific, real, previously-proven gap).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('os');

const { createReview, classifyFile, evidenceGaps, onlyTrivialTestRan } = require('./reviewer-evidence');

const TMP = os.tmpdir();
const PASS_TESTS = { status: 'PASS', commands: ['pytest -q'] };
const PASS_EVAL = { status: 'PASS', hard_failures: [] };

function review(overrides) {
  return createReview({
    manifest: { run_id: `t-${Math.random().toString(36).slice(2)}`, production_impact: 'NONE', docs_required: false, ...overrides.manifest },
    testReport: overrides.testReport || PASS_TESTS,
    evalReport: overrides.evalReport || PASS_EVAL,
    artifactDir: TMP,
  });
}

// ── Category classifier ──────────────────────────────────────────────

test('classifyFile: backend logic, frontend logic, api contract, db, security, agent, infra, docs, tests', () => {
  assert.equal(classifyFile('engine/stock_scanner/logic.py'), 'backend_logic');
  assert.equal(classifyFile('frontend/src/app/screener/page.tsx'), 'frontend_logic');
  assert.equal(classifyFile('engine/routers/paper_trading.py'), 'api_contract');
  assert.equal(classifyFile('engine/utils/db.py'), 'db_persistence');
  assert.equal(classifyFile('engine/auth_utils.py'), 'security_auth');
  assert.equal(classifyFile('engine/utils/security_config.py'), 'security_auth');
  assert.equal(classifyFile('scripts/agent/reviewer-evidence.js'), 'agent_framework');
  assert.equal(classifyFile('.github/workflows/research-evidence-archive.yml'), 'infra_workflow');
  assert.equal(classifyFile('docs/agents/AGENT_STATUS.md'), 'docs');
  assert.equal(classifyFile('tests/backend/test_options_provider.py'), 'tests');
  assert.equal(classifyFile('package.json'), 'other');
});

// ── 1. backend production logic changed + no relevant test evidence ──

test('1. backend logic changed with no backend test evidence -> NOT_MERGEABLE', () => {
  const result = review({ manifest: { changed_files: ['engine/stock_scanner/logic.py'] } });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(result.findings.some((f) => f.includes('backend_logic')));
});

// ── 2. backend logic + relevant test added + tests pass -> MERGEABLE ─

test('2. backend logic changed with matching backend test evidence -> MERGEABLE', () => {
  const result = review({
    manifest: { changed_files: ['engine/stock_scanner/logic.py', 'tests/backend/test_stock_scanner_backtest.py'] },
  });
  assert.equal(result.verdict, 'MERGEABLE');
  assert.deepEqual(result.findings, []);
});

// ── 3. frontend behavior + no frontend evidence -> NOT_MERGEABLE ─────

test('3. frontend logic changed with no frontend evidence -> NOT_MERGEABLE', () => {
  const result = review({ manifest: { changed_files: ['frontend/src/app/screener/page.tsx'] } });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(result.findings.some((f) => f.includes('frontend_logic')));
});

test('3b. frontend logic changed with matching frontend E2E evidence -> MERGEABLE', () => {
  const result = review({
    manifest: { changed_files: ['frontend/src/app/screener/page.tsx', 'frontend/e2e/stock-screener.spec.ts'] },
  });
  assert.equal(result.verdict, 'MERGEABLE');
});

// ── 4. docs-only -> no unnecessary test requirement ──────────────────

test('4. docs-only change requires no test evidence -> MERGEABLE', () => {
  const result = review({ manifest: { changed_files: ['docs/agents/AGENT_STATUS.md'] } });
  assert.equal(result.verdict, 'MERGEABLE');
  assert.deepEqual(result.findings, []);
});

// ── 5. security/auth change + no focused evidence -> NOT_MERGEABLE ───

test('5. security/auth change with no focused security test evidence -> NOT_MERGEABLE', () => {
  const result = review({ manifest: { changed_files: ['engine/utils/security_config.py'] } });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(result.findings.some((f) => f.includes('security_auth')));
});

test('5b. security/auth change with a focused security test present -> MERGEABLE', () => {
  const result = review({
    manifest: { changed_files: ['engine/utils/security_config.py', 'tests/backend/test_security_config.py'] },
  });
  assert.equal(result.verdict, 'MERGEABLE');
});

// ── 6. legitimate explicit waiver -> accepted but visible ────────────

test('6. an explicit test_waiver accepts a gap but keeps it visible as a note', () => {
  const result = review({
    manifest: {
      changed_files: ['engine/stock_scanner/logic.py'],
      test_waiver: { reason: 'Pure refactor; equivalence proven by existing golden-file test run manually.', categories: ['backend_logic'] },
    },
  });
  assert.equal(result.verdict, 'MERGEABLE_WITH_NOTES');
  assert.deepEqual(result.findings, []);
  assert.ok(result.notes.some((n) => n.includes('backend_logic') && n.includes('Pure refactor')));
});

test('6b. a waiver with no reason text is not accepted (still NOT_MERGEABLE)', () => {
  const result = review({
    manifest: { changed_files: ['engine/stock_scanner/logic.py'], test_waiver: { reason: '   ' } },
  });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
});

// ── 7. failed tests -> NOT_MERGEABLE ──────────────────────────────────

test('7. failed tests block regardless of file categories -> NOT_MERGEABLE', () => {
  const result = review({
    manifest: { changed_files: ['docs/agents/AGENT_STATUS.md'] },
    testReport: { status: 'FAIL', commands: ['pytest -q'] },
  });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(result.findings.includes('Task tests did not pass.'));
});

// ── 8. missing required test execution -> NOT_MERGEABLE ──────────────

test('8. only a no-op diff-check ran for a category requiring evidence -> NOT_MERGEABLE', () => {
  const result = review({
    manifest: { changed_files: ['engine/stock_scanner/logic.py', 'tests/backend/test_stock_scanner_backtest.py'] },
    testReport: { status: 'PASS', commands: ['git diff --check'] },
  });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(result.findings.some((f) => f.includes('no-op diff check')));
});

test('8b. a no-op diff-check for a docs-only change is fine -> MERGEABLE', () => {
  const result = review({
    manifest: { changed_files: ['docs/agents/AGENT_STATUS.md'] },
    testReport: { status: 'PASS', commands: ['git diff --check'] },
  });
  assert.equal(result.verdict, 'MERGEABLE');
});

// ── Structural: no changed files at all ──────────────────────────────

test('no changed files evidenced -> BLOCKED (not a fixable revision, not silently MERGEABLE)', () => {
  const result = review({ manifest: { changed_files: [] } });
  assert.equal(result.verdict, 'BLOCKED');
});

// ── evalReport still gates ────────────────────────────────────────────

test('a hard eval failure blocks even with clean file evidence', () => {
  const result = review({
    manifest: { changed_files: ['docs/agents/AGENT_STATUS.md'] },
    evalReport: { status: 'FAIL', hard_failures: ['scope violation'] },
  });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
});

// ── evidenceGaps / onlyTrivialTestRan helpers directly ───────────────

test('evidenceGaps returns empty for a fully-covered diff', () => {
  const gaps = evidenceGaps(['engine/routers/paper_trading.py', 'tests/backend/test_paper_trading_router.py']);
  assert.deepEqual(gaps, []);
});

test('onlyTrivialTestRan is false when a real command ran', () => {
  assert.equal(onlyTrivialTestRan({ commands: ['pytest -q'] }, ['engine/stock_scanner/logic.py']), false);
});

// ── Epic 20 adversarial-review fix: no more free-pass 'other' for real code ──

test('classifyFile: a Python file outside engine/ is other_code, not a free-pass other', () => {
  assert.equal(classifyFile('scripts/pricing_engine.py'), 'other_code');
  assert.equal(classifyFile('worker/pipeline.py'), 'other_code');
});

test('classifyFile: a genuinely non-code file still classifies as other (no evidence required)', () => {
  assert.equal(classifyFile('package-lock.json'), 'other');
  assert.equal(classifyFile('.gitignore'), 'other');
});

test('other_code changes require test evidence, unlike other', () => {
  const result = review({ manifest: { changed_files: ['scripts/pricing_engine.py'] } });
  assert.equal(result.verdict, 'NOT_MERGEABLE');
  assert.ok(result.findings.some((f) => f.includes('other_code') || f.toLowerCase().includes('unclassified code')));
});

test('other_code with matching test evidence passes', () => {
  const result = review({ manifest: { changed_files: ['scripts/pricing_engine.py', 'tests/backend/test_pricing_engine.py'] } });
  assert.equal(result.verdict, 'MERGEABLE');
});

test('classifyFile: security-sensitive files without "auth" in the name now classify as security_auth', () => {
  assert.equal(classifyFile('engine/utils/token_store.py'), 'security_auth');
  assert.equal(classifyFile('engine/utils/session_manager.py'), 'security_auth');
  assert.equal(classifyFile('engine/utils/crypto.py'), 'security_auth');
});
