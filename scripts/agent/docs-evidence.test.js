#!/usr/bin/env node
'use strict';

/*
 * Tests for FORTRESS-NEXT Epic 19's Docs Agent check (docs-evidence.js).
 * Run with: node --test scripts/agent/docs-evidence.test.js
 *
 * The last test in this file is the epic's own required proof: replay PR
 * #21's real diff against a real historical checkout of docs/ as it stood
 * BEFORE PR #72's manual fix, and confirm the check flags
 * docs/research/REAL_VALIDATION_RESULTS.md. This uses `git worktree`
 * against this repo's own real history — not a synthetic fixture — so a
 * failure here means the check regressed on the one case we already know
 * it must catch.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const { checkDocsImpact, extractReferences, docsLikelyRequired } = require('./docs-evidence');
const { REPO_ROOT } = require('./lib');

// ── FORTRESS "LUNA MISSES CLOSEOUT" Epic 7 ───────────────────────────────
// docs_required in the real pipeline used to be fixed at classification
// time (selectedAgent === 'docs' only) - a backend/infra/agent-framework
// change could reach PR with docs_status NOT_REQUIRED no matter what it
// touched. docsLikelyRequired() is what closes that (wired into agent.js's
// autoGatesCommand as reviewerGate()'s docsImpact argument).

test('docsLikelyRequired: a new/changed API route requires docs', () => {
  const result = docsLikelyRequired(['engine/routers/paper_trading.py']);
  assert.equal(result.required, true);
  assert.equal(result.hits[0].category, 'api_contract');
});

test('docsLikelyRequired: a security/auth change requires docs', () => {
  const result = docsLikelyRequired(['engine/auth_utils.py']);
  assert.equal(result.required, true);
  assert.equal(result.hits[0].category, 'security_auth');
});

test('docsLikelyRequired: an agent-framework/workflow change requires docs', () => {
  const result = docsLikelyRequired(['.github/workflows/agent-pipeline.yml']);
  assert.equal(result.required, true);
  assert.equal(result.hits[0].category, 'agent_framework');
});

test('docsLikelyRequired: a pure backend-logic refactor does not require docs', () => {
  const result = docsLikelyRequired(['engine/stock_scanner/logic.py']);
  assert.equal(result.required, false);
  assert.deepEqual(result.hits, []);
});

test('docsLikelyRequired: a test-only or docs-only change does not require docs', () => {
  assert.equal(docsLikelyRequired(['tests/backend/test_options_provider.py']).required, false);
  assert.equal(docsLikelyRequired(['docs/agents/AGENT_STATUS.md']).required, false);
});

test('checkDocsImpact reports docs_required alongside the advisory docs_impacted flag', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-evidence-epic7-'));
  const result = checkDocsImpact({ changedFiles: ['engine/routers/paper_trading.py'], repoRoot: dir });
  assert.equal(result.docs_required, true);
  assert.equal(result.docs_required_reasons[0].category, 'api_contract');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('extractReferences finds a backtick-quoted file path', () => {
  const refs = extractReferences('See `engine/utils/db.py` for details.');
  assert.deepEqual(refs, ['engine/utils/db.py']);
});

test('extractReferences finds a directory glob reference', () => {
  const refs = extractReferences('The framework (`engine/research/*`, documented in...)');
  assert.deepEqual(refs, ['engine/research/*']);
});

test('extractReferences strips a ::function_name suffix from the captured path', () => {
  const refs = extractReferences('`engine/utils/db.py::save_scan_results` legacy rows');
  assert.deepEqual(refs, ['engine/utils/db.py']);
});

test('checkDocsImpact flags a doc referencing an exact changed file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-evidence-test-'));
  fs.mkdirSync(path.join(dir, 'docs/research'), { recursive: true });
  fs.writeFileSync(
    path.join(dir, 'docs/research/CLAIM.md'),
    'This describes `engine/utils/db.py` behavior.'
  );
  const result = checkDocsImpact({ changedFiles: ['engine/utils/db.py'], repoRoot: dir });
  assert.equal(result.docs_impacted, true);
  assert.equal(result.advisory, true);
  assert.equal(result.flags.length, 1);
  assert.equal(result.flags[0].doc, 'docs/research/CLAIM.md');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('checkDocsImpact does not flag a doc that was itself updated in the same PR', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-evidence-test-'));
  fs.mkdirSync(path.join(dir, 'docs/research'), { recursive: true });
  fs.writeFileSync(
    path.join(dir, 'docs/research/CLAIM.md'),
    'This describes `engine/utils/db.py` behavior.'
  );
  const result = checkDocsImpact({
    changedFiles: ['engine/utils/db.py', 'docs/research/CLAIM.md'],
    repoRoot: dir,
  });
  assert.equal(result.docs_impacted, false);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('checkDocsImpact does not flag an unrelated file reference', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-evidence-test-'));
  fs.mkdirSync(path.join(dir, 'docs/research'), { recursive: true });
  fs.writeFileSync(
    path.join(dir, 'docs/research/CLAIM.md'),
    'This describes `engine/utils/other_module.py` behavior.'
  );
  const result = checkDocsImpact({ changedFiles: ['engine/utils/db.py'], repoRoot: dir });
  assert.equal(result.docs_impacted, false);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('agent-pipeline.yml actually invokes docs-evidence.js, not just defines it', () => {
  // The whole point of this pass: a file existing is not evidence it runs.
  // Assert the real invocation is present in the workflow, not just that
  // scripts/agent/docs-evidence.js exists on disk.
  const workflow = fs.readFileSync(
    path.join(REPO_ROOT, '.github/workflows/agent-pipeline.yml'),
    'utf8'
  );
  assert.ok(
    workflow.includes('scripts/agent/docs-evidence.js'),
    'agent-pipeline.yml does not invoke scripts/agent/docs-evidence.js'
  );
});

test('historical proof: PR #21 (FORTRESS-E3) would have been flagged against pre-PR#72 docs', (t) => {
  // PR #21's own real, merged changed-file list (git diff --name-only
  // a54b1cb~1 a54b1cb, run once when this test was written and pinned
  // here — the point is replaying it, not re-deriving it every run).
  const PR21_CHANGED_FILES = [
    '.github/workflows/auto-scan-eod.yml',
    'docs/research/AUTOMATED_MULTI_UNIVERSE_SCANNING.md',
    'engine/main.py',
    'engine/research/auto_scan.py',
    'engine/research/prospective_store.py',
    'engine/routers/auto_scan.py',
    'engine/utils/db.py',
    'tests/backend/test_auto_scan.py',
  ];
  const PR21_MERGE_COMMIT = 'a54b1cb65b16b54bf11289c0cc7f32a09b857b82';

  let hasCommit = true;
  try {
    execFileSync('git', ['cat-file', '-e', `${PR21_MERGE_COMMIT}~1`], { cwd: REPO_ROOT });
  } catch {
    hasCommit = false;
  }
  if (!hasCommit) {
    t.skip('PR #21 merge commit not present in this checkout (shallow clone?)');
    return;
  }

  const worktreeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-evidence-pr21-'));
  fs.rmSync(worktreeDir, { recursive: true, force: true }); // git worktree add wants the dir absent
  execFileSync('git', ['worktree', 'add', '--detach', worktreeDir, `${PR21_MERGE_COMMIT}~1`], {
    cwd: REPO_ROOT,
  });
  try {
    const result = checkDocsImpact({ changedFiles: PR21_CHANGED_FILES, repoRoot: worktreeDir });
    assert.equal(result.docs_impacted, true, 'expected the historical PR #21 diff to be flagged');
    const hit = result.flags.find((f) => f.doc === 'docs/research/REAL_VALIDATION_RESULTS.md');
    assert.ok(
      hit,
      `expected a flag on docs/research/REAL_VALIDATION_RESULTS.md, got: ${JSON.stringify(result.flags)}`
    );
    assert.equal(hit.referenced_path, 'engine/research/*');
  } finally {
    execFileSync('git', ['worktree', 'remove', '--force', worktreeDir], { cwd: REPO_ROOT });
  }
});
