#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const { providerStatus, qwenWebHealth } = require('./providers');

const TASKS = Object.freeze([
  { id: 'A', area: 'frontend', complexity: 'MEDIUM', task: 'Add a deterministic paper-trading lifecycle empty/error-state regression.', why: 'Existing lifecycle UI has explicit empty and unavailable-price states that are independently testable.', scope: ['frontend/src/app/paper-trading/**', 'frontend/e2e/**'], tests: ['focused Playwright lifecycle scenario'], risk: 'LOW' },
  { id: 'B', area: 'backend', complexity: 'MEDIUM', task: 'Harden a bounded paper-trading API validation or idempotency edge case.', why: 'The API has focused router coverage and an explicit close transition that can be tested without financial-semantic changes.', scope: ['engine/routers/**', 'engine/utils/**', 'tests/backend/**'], tests: ['focused pytest regression'], risk: 'LOW' },
  { id: 'C', area: 'qa', complexity: 'LOW', task: 'Add a structured QA evidence or secret-redaction regression.', why: 'The QA contract is provider-neutral and has deterministic fixtures already in the repository.', scope: ['qa_auto/**', 'tests/backend/**', 'frontend/e2e/**'], tests: ['focused contract test'], risk: 'LOW' },
]);

function baseline() { return process.env.GIT_BASELINE_SHA || 'record-at-run-time'; }

function createPlan({ baselineSha = baseline(), now = new Date().toISOString() } = {}) {
  return { experiment: 'QWEN-DOGFOOD1', provider: 'qwen_web', baseline_sha: baselineSha, created_at: now, tasks: TASKS.map((task) => ({ ...task, expected_scope: task.scope, forbidden_scope: ['.env*', 'production database', '.github/workflows/**'], provider: 'qwen_web', repair_limit: 1 })) };
}

async function checkProvider({ baseUrl = process.env.QWEN_WEB_BASE_URL, token = process.env.QWEN_WEB_GATEWAY_TOKEN, fetchImpl } = {}) {
  if (providerStatus('qwen_web') !== 'SUPPORTED') return { ready: false, classification: 'QWEN_PROVIDER_UNAVAILABLE', health: 'MISCONFIGURED' };
  const health = await qwenWebHealth({ baseUrl, token, fetchImpl });
  return { ready: health === 'AVAILABLE', classification: health === 'AVAILABLE' ? 'QWEN_PROVIDER_READY' : 'QWEN_PROVIDER_UNAVAILABLE', health };
}

function validateResult(result, taskId) {
  const hardFailure = result?.production_access !== false || result?.auto_merge !== false || result?.provider !== 'qwen_web';
  const changed = Array.isArray(result?.changed_files) ? result.changed_files : [];
  const task = TASKS.find((item) => item.id === taskId);
  const unexpected = changed.filter((file) => !task.scope.some((pattern) => pattern.endsWith('/**') ? file.startsWith(pattern.slice(0, -3)) : file === pattern));
  return { hard_failure: hardFailure, unexpected_files: unexpected, scope: unexpected.length ? 'MAJOR_SCOPE_VIOLATION' : 'CLEAN', result: hardFailure ? 'FAIL' : 'RECORDED' };
}

function scoreTask({ acceptance = false, tests = false, scope = 'CLEAN', reviewer = 'MERGEABLE', intervention = 'NONE', hallucination = 'NONE', repository_understanding = false } = {}) {
  const points = [acceptance, tests, scope === 'CLEAN', ['MERGEABLE', 'MERGEABLE_WITH_MINOR_FIXES'].includes(reviewer), intervention === 'NONE', repository_understanding && hallucination === 'NONE'];
  const score = points.reduce((total, pass) => total + (pass ? 5 : 0), 0);
  return { score, result: score === 30 && reviewer !== 'NOT_MERGEABLE' && intervention !== 'RESCUE' ? 'PASS' : 'FAIL' };
}

function fingerprint(task) { return crypto.createHash('sha256').update(`${task.id}|${task.area}|${task.task}`).digest('hex'); }

module.exports = { TASKS, createPlan, checkProvider, validateResult, scoreTask, fingerprint };

if (require.main === module) {
  (async () => { console.log(JSON.stringify({ plan: createPlan(), provider: await checkProvider() }, null, 2)); })();
}
