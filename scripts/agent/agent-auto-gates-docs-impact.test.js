#!/usr/bin/env node
'use strict';

/*
 * FORTRESS "LUNA MISSES CLOSEOUT" Epic 7: end-to-end proof that
 * agent.js's real `auto-gates` CLI path (not just reviewerGate() in
 * isolation) actually escalates docs_required from the real changed-file
 * categories, and does NOT crash now that the workflow always passes a
 * docs-report.json (previously never passed at all - autoGatesCommand
 * would have thrown "docs evidence is required when docs are required"
 * the first time docs_required ever turned out true for a run that
 * wasn't classified as docs, since nothing supplied docsPath).
 *
 * Run with: node --test scripts/agent/agent-auto-gates-docs-impact.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const os = require('os');

const lib = require('./lib');
const { save, load, autoGatesCommand } = require('./agent');
const pipeline = require('./unified-pipeline');

const sessions = path.join(lib.REPO_ROOT, '.agent-room', 'sessions');

function makeManifest(runId, changedFiles) {
  const manifest = pipeline.createManifest({
    run_id: runId, task_id: runId, agent: 'backend', provider: 'codex', model: 'default',
    input_budget: 8000, output_budget: 2500, production_access: false, human_gate: true,
    branch: `agent/${runId}`, allowed_files: ['**'], forbidden_files: [], prompt_artifact: 'x',
    provider_mode: 'MANUAL_EXPORT', docs_required: false, // classified as backend, not docs
  });
  return save({ ...manifest, changed_files: changedFiles, scope_status: 'PASS', state: 'TESTING' });
}

function writeJson(runId, suffix, data) {
  const file = path.join(sessions, `${runId}.${suffix}`);
  fs.writeFileSync(file, JSON.stringify(data));
  return file;
}

function cleanup(runId) {
  for (const f of fs.readdirSync(sessions)) {
    if (f.startsWith(runId)) fs.unlinkSync(path.join(sessions, f));
  }
}

test('auto-gates escalates docs_required for an API-route change classified as backend, and does not crash', () => {
  const runId = `epic7-test-${Date.now()}`;
  makeManifest(runId, ['engine/routers/paper_trading.py', 'tests/backend/test_paper_trading_router.py']);
  const testReport = writeJson(runId, 'test-report.json', { status: 'PASS', commands: ['pytest -q'], exit_codes: [0] });
  const evalReport = writeJson(runId, 'eval-report.json', { status: 'PASS', hard_failures: [] });
  const reviewReport = writeJson(runId, 'review-report.json', { verdict: 'MERGEABLE', findings: [] });
  const docsReport = writeJson(runId, 'docs-report.json', { docs_impacted: false, flags: [] }); // no status field, like the real docs-evidence.js output

  try {
    const result = autoGatesCommand(runId, evalReport, testReport, reviewReport, docsReport);
    // Escalated: this run was classified 'backend' (docs_required started
    // false), but touching an api_contract file must still turn it on.
    assert.equal(result.docs_required, true);
    // No real "were docs written" check exists yet (Epic 7 scope), so this
    // must block for a human, not silently pass.
    assert.equal(result.docs_status, 'PENDING');
    assert.equal(result.state, 'BLOCKED_PR');
  } finally {
    cleanup(runId);
  }
});

test('auto-gates does not require docs for a pure backend-logic change', () => {
  const runId = `epic7-test-nodocs-${Date.now()}`;
  makeManifest(runId, ['engine/stock_scanner/logic.py', 'tests/backend/test_stock_scanner_backtest.py']);
  const testReport = writeJson(runId, 'test-report.json', { status: 'PASS', commands: ['pytest -q'], exit_codes: [0] });
  const evalReport = writeJson(runId, 'eval-report.json', { status: 'PASS', hard_failures: [] });
  const reviewReport = writeJson(runId, 'review-report.json', { verdict: 'MERGEABLE', findings: [] });
  const docsReport = writeJson(runId, 'docs-report.json', { docs_impacted: false, flags: [] });

  try {
    const result = autoGatesCommand(runId, evalReport, testReport, reviewReport, docsReport);
    assert.equal(result.docs_required, false);
    assert.equal(result.docs_status, 'NOT_REQUIRED');
    assert.equal(result.state, 'AWAITING_HUMAN');
  } finally {
    cleanup(runId);
  }
});
