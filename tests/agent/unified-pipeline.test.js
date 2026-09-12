const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  createManifest, importProviderResult, resumeRun, testGate, evaluateGate,
  reviewerGate, docsGate, prGate, recordQuality, recommendProvider,
  buildUnifiedPrBody, buildScoreboard, selectEvalGroups,
} = require('../../scripts/agent/unified-pipeline');

function tempDir() { return fs.mkdtempSync(path.join(os.tmpdir(), 'agent3-')); }
function base(overrides = {}) {
  return createManifest({
    run_id: 'run-1', task_id: 'task-1', issue_number: 42, agent: 'backend',
    provider: 'codex', model: 'configured-model', input_budget: 9000,
    output_budget: 3000, production_access: false, human_gate: true,
    branch: 'agent/42-backend-task-1', allowed_files: ['engine/**', 'tests/**'],
    forbidden_files: ['.env', '.github/workflows/**'], prompt_artifact: 'prompt.txt',
    provider_mode: 'MANUAL_EXPORT', docs_required: false, ...overrides,
  });
}
function writeResult(dir, value) {
  const file = path.join(dir, 'result.json'); fs.writeFileSync(file, JSON.stringify(value)); return file;
}

test('canonical manifest excludes secrets and has one resumable state', () => {
  const manifest = base({ api_key: 'secret', DATABASE_URL: 'secret', token: 'secret' });
  assert.equal(manifest.state, 'MANUAL_EXPORT');
  assert.equal(JSON.stringify(manifest).includes('secret'), false);
  assert.equal(manifest.production_access, false);
});

test('manual export imports and resumes the same run idempotently', () => {
  const dir = tempDir(); const manifest = base();
  const file = writeResult(dir, { run_id: 'run-1', provider: 'codex', model: 'configured-model', changed_files: ['engine/x.py'] });
  const imported = importProviderResult(manifest, file, { artifactDir: dir, now: '2026-09-11T00:00:00.000Z' });
  assert.equal(imported.run_id, 'run-1');
  assert.equal(imported.state, 'RESULT_IMPORTED');
  assert.equal(resumeRun(imported).state, 'VALIDATING_SCOPE');
  assert.deepEqual(resumeRun(resumeRun(imported)), resumeRun(imported));
});

test('issue-driven manual pause accepts provider result import', () => {
  const dir = tempDir();
  const file = writeResult(dir, {
    run_id: 'run-1', provider: 'codex', model: 'configured-model',
    changed_files: ['engine/x.py'],
  });
  const imported = importProviderResult(
    { ...base(), state: 'WAITING_FOR_PROVIDER_RESULT' },
    file,
    { artifactDir: dir },
  );
  assert.equal(imported.state, 'RESULT_IMPORTED');
});

test('wrong run id and provider mismatch are rejected', () => {
  const dir = tempDir();
  assert.throws(() => importProviderResult(base(), writeResult(dir, { run_id: 'wrong', provider: 'codex' }), { artifactDir: dir }), /run_id mismatch/);
  assert.throws(() => importProviderResult(base(), writeResult(dir, { run_id: 'run-1', provider: 'anthropic' }), { artifactDir: dir }), /provider mismatch/);
});

test('untrusted result cannot alter governance, scope, ceiling, or auto merge', () => {
  const dir = tempDir(); const manifest = base();
  const file = writeResult(dir, { run_id: 'run-1', provider: 'codex', production_access: true,
    allowed_files: ['**'], forbidden_files: [], input_budget: 999999, human_gate: false,
    review_required: false, auto_merge: true, changed_files: ['engine/x.py'] });
  const imported = importProviderResult(manifest, file, { artifactDir: dir });
  assert.equal(imported.production_access, false);
  assert.deepEqual(imported.allowed_files, manifest.allowed_files);
  assert.equal(imported.input_budget, 9000);
  assert.equal(imported.human_gate, true);
  assert.equal(imported.review_required, true);
  assert.equal(imported.auto_merge, false);
});

test('eval PASS and WARN proceed while FAIL and hard failures block', () => {
  assert.equal(evaluateGate(base(), { status: 'PASS', score: 95, hard_failures: [] }).state, 'REVIEW_PENDING');
  const warn = evaluateGate(base(), { status: 'WARN', score: 84, hard_failures: [] });
  assert.equal(warn.state, 'REVIEW_PENDING'); assert.equal(warn.eval_status, 'EVAL_WARN');
  assert.equal(evaluateGate(base(), { status: 'FAIL', score: 60, hard_failures: [] }).state, 'BLOCKED_EVAL');
  assert.equal(evaluateGate(base(), { status: 'PASS', score: 99, hard_failures: ['secret_exposure'] }).state, 'BLOCKED_EVAL');
});

test('test gate blocks failures and records only declared commands', () => {
  assert.equal(testGate(base(), { status: 'FAIL', commands: ['pytest'] }).state, 'BLOCKED_TESTS');
  const passed = testGate(base(), { status: 'PASS', commands: ['pytest'] });
  assert.equal(passed.state, 'EVALUATING');
  assert.deepEqual(passed.tests.commands, ['pytest']);
});

test('reviewer cannot override hard failure and repair is limited to one cycle without provider switching', () => {
  const blocked = evaluateGate(base(), { status: 'FAIL', score: 99, hard_failures: ['auto_merge'] });
  assert.equal(reviewerGate(blocked, 'MERGEABLE').state, 'BLOCKED_EVAL');
  const reviewed = reviewerGate({ ...base(), state: 'REVIEW_PENDING', eval_hard_failures: [] }, 'NOT_MERGEABLE');
  assert.equal(reviewed.state, 'REPAIR_PENDING'); assert.equal(reviewed.repair_count, 1); assert.equal(reviewed.provider, 'codex');
  const again = reviewerGate({ ...reviewed, state: 'REVIEW_PENDING' }, 'NOT_MERGEABLE');
  assert.equal(again.state, 'BLOCKED'); assert.equal(again.provider, 'codex');
});

test('docs and PR gates require every prerequisite and stop awaiting human', () => {
  const readyReview = reviewerGate({ ...base(), state: 'REVIEW_PENDING', eval_hard_failures: [] }, 'MERGEABLE');
  assert.equal(docsGate({ ...readyReview, docs_required: true }, false).state, 'DOCS_PENDING');
  const readyDocs = docsGate({ ...readyReview, docs_required: true }, true);
  const ready = prGate({ ...readyDocs, scope_status: 'PASS', tests: { status: 'PASS' }, eval_status: 'EVAL_PASS', human_gate_status: 'VALID' });
  assert.equal(ready.state, 'AWAITING_HUMAN'); assert.equal(ready.auto_merge, false);
  assert.equal(prGate({ ...readyDocs, scope_status: 'FAIL', tests: { status: 'PASS' }, eval_status: 'EVAL_PASS', human_gate_status: 'VALID' }).state, 'BLOCKED_PR');
});

test('task-specific eval selection stays practical', () => {
  assert.deepEqual(selectEvalGroups('backend'), ['backend', 'security', 'reviewer']);
  assert.deepEqual(selectEvalGroups('docs'), ['docs', 'reviewer']);
  assert.ok(selectEvalGroups('agent-framework').includes('coordinator'));
});

test('quality records keep optional token metrics and recommendations need evidence', () => {
  const records = [
    recordQuality({ provider: 'codex', model: 'm', agent: 'backend', eval_score: 95, review_verdict: 'MERGEABLE', tests: 'PASS', input_tokens: 8000, output_tokens: 2000 }),
    recordQuality({ provider: 'codex', model: 'm', agent: 'backend', eval_score: 90, review_verdict: 'MERGEABLE', tests: 'PASS' }),
  ];
  assert.equal(records[0].quality_per_1k_tokens, 9.5);
  assert.equal(records[1].quality_per_1k_tokens, null);
  assert.equal(recommendProvider(records, 'backend').status, 'INSUFFICIENT_EVIDENCE');
  const enough = [...records, ...Array.from({ length: 3 }, () => records[0])];
  assert.equal(recommendProvider(enough, 'backend').recommended, 'codex');
  assert.equal(buildScoreboard(enough).backend.codex.samples, 5);
});

test('PR body excludes secrets and exposes all gates', () => {
  const body = buildUnifiedPrBody({ ...base(), changed_files: ['engine/x.py'], tests: { status: 'PASS' }, eval_status: 'EVAL_PASS', eval_score: 95, eval_hard_failures: [], review_status: 'MERGEABLE', docs_status: 'NOT_REQUIRED', production_impact: 'NONE', api_key: 'dont-leak' });
  assert.match(body, /Agent Eval/); assert.match(body, /Human Gate/); assert.doesNotMatch(body, /dont-leak/); assert.doesNotMatch(body, /auto-merge enabled/i);
});

test('unified CLI has no merge command or production action', () => {
  const source = fs.readFileSync(path.join(__dirname, '../../scripts/agent/agent.js'), 'utf8');
  assert.doesNotMatch(source, /command === ['"]merge['"]/);
  assert.doesNotMatch(source, /Oracle|Vercel|Neon|Render/);
});
