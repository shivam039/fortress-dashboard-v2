#!/usr/bin/env node

const crypto = require('node:crypto');
const fs = require('node:fs');

const STATES = Object.freeze([
  'BLOCKED_TRIAGE', 'WAITING_APPROVAL', 'WAITING_PROVIDER',
  'IMPLEMENTING', 'TESTING', 'QA_REVERIFY', 'EVALUATING', 'REVIEWING',
  'READY_FOR_PR', 'BLOCKED_TESTS', 'BLOCKED_QA', 'BLOCKED_EVAL',
  'BLOCKED_REVIEW', 'AWAITING_HUMAN',
]);

const SECRET = /(authorization|cookie|api[-_]?key|token|password)\s*[:=]\s*[^\s,;]+/gi;

function redact(value) {
  if (typeof value === 'string') return value.replace(SECRET, '$1=[REDACTED]');
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redact(v)]));
  }
  return value;
}

function required(value, name) {
  if (value === undefined || value === null || value === '') throw new Error(`finding.${name} is required`);
}

function validateFinding(input) {
  const finding = redact(input);
  for (const field of ['finding_id', 'run_id', 'environment', 'surface', 'scenario', 'status', 'severity', 'observed', 'expected', 'route', 'evidence']) required(finding[field], field);
  if (!['FAIL', 'BLOCKED', 'PASS', 'NOT_APPLICABLE'].includes(finding.status)) throw new Error('finding.status is invalid');
  if (!['QA0', 'QA1', 'QA2', 'QA3'].includes(finding.severity)) throw new Error('finding.severity is invalid');
  return finding;
}

function findingFingerprint(finding) {
  const safe = [finding.environment, finding.surface, finding.scenario, finding.route, finding.status, finding.observed, finding.expected]
    .map((item) => String(item).trim().toLowerCase()).join('|');
  return crypto.createHash('sha256').update(safe).digest('hex');
}

function classifyFinding(finding) {
  const text = `${finding.surface} ${finding.scenario} ${finding.observed} ${finding.expected}`.toLowerCase();
  if (finding.environment === 'production' && finding.action_class !== 'READ_ONLY') return 'HUMAN_GATED_PRODUCTION_CHANGE';
  if (/(oracle|buy|sell|score|quantity|sizing|stop|target|allocation|financial)/.test(text)) return 'HUMAN_PRODUCT_DECISION_REQUIRED';
  if (finding.status !== 'FAIL') return 'OBSERVATION_ONLY';
  if (/(404|500|502|handler|route|stale|malformed|console|network|render)/.test(text)) return 'AUTO_TRIAGE_ELIGIBLE';
  return 'OBSERVATION_ONLY';
}

function triageFinding(finding) {
  const route = String(finding.route).toLowerCase();
  const surface = String(finding.surface).toLowerCase();
  const specialist = /api|backend|server|db|database/.test(`${route} ${surface}`) ? 'backend'
    : /infra|deploy|health|container/.test(`${route} ${surface}`) ? 'infra'
      : /docs|documentation/.test(`${route} ${surface}`) ? 'docs' : 'frontend';
  return { specialist, state: specialist ? 'WAITING_APPROVAL' : 'BLOCKED_TRIAGE', ambiguous: !specialist };
}

function dedupeFinding(finding, existing = []) {
  const fingerprint = findingFingerprint(finding);
  const duplicate = existing.find((item) => item.fingerprint === fingerprint && !['READY_FOR_PR', 'AWAITING_HUMAN'].includes(item.state));
  return { fingerprint, duplicate: duplicate || null };
}

function conservativeScope(finding, specialist) {
  const scopes = {
    frontend: ['frontend/**'], backend: ['engine/**', 'tests/backend/**'],
    infra: ['.github/**', 'docker-compose*.yml', 'Dockerfile*'], docs: ['docs/**', 'agents/**'],
  };
  return { allowed: scopes[specialist] || [], forbidden: ['.env*', '**/*secret*', 'production database', 'deploy commands'] };
}

function createLoop(input, existing = [], options = {}) {
  const finding = validateFinding(input);
  const classification = classifyFinding(finding);
  const { fingerprint, duplicate } = dedupeFinding(finding, existing);
  if (duplicate) return { state: 'AWAITING_HUMAN', classification, fingerprint, duplicate: true, canonical_id: duplicate.id };
  if (classification !== 'AUTO_TRIAGE_ELIGIBLE') return { state: 'AWAITING_HUMAN', classification, fingerprint, reason: 'human decision required' };
  const triage = triageFinding(finding);
  if (triage.ambiguous) return { state: 'BLOCKED_TRIAGE', classification, fingerprint };
  const approved = options.AUTO_APPROVE_LOW_RISK === true && finding.environment !== 'production' && finding.severity === 'QA3';
  return { state: approved ? 'IMPLEMENTING' : 'WAITING_APPROVAL', classification, fingerprint, specialist: triage.specialist, scope: conservativeScope(finding, triage.specialist), repair_cycles: 0, approval_required: !approved, auto_merge: false, auto_deploy: false };
}

function advanceLoop(loop, event) {
  const next = { ...loop };
  if (event === 'approve' && loop.state === 'WAITING_APPROVAL') next.state = 'IMPLEMENTING';
  else if (event === 'implementation_complete' && loop.state === 'IMPLEMENTING') next.state = 'TESTING';
  else if (event === 'tests_pass' && loop.state === 'TESTING') next.state = 'QA_REVERIFY';
  else if (event === 'tests_fail' && loop.state === 'TESTING') next.state = loop.repair_cycles < 1 ? 'IMPLEMENTING' : 'BLOCKED_TESTS';
  else if (event === 'qa_pass' && loop.state === 'QA_REVERIFY') next.state = 'EVALUATING';
  else if (event === 'qa_fail' && loop.state === 'QA_REVERIFY') next.state = 'BLOCKED_QA';
  else if (event === 'eval_pass' && loop.state === 'EVALUATING') next.state = 'REVIEWING';
  else if (event === 'eval_fail' && loop.state === 'EVALUATING') next.state = 'BLOCKED_EVAL';
  else if (event === 'review_pass' && loop.state === 'REVIEWING') next.state = 'READY_FOR_PR';
  else if (event === 'review_fail' && loop.state === 'REVIEWING') next.state = 'BLOCKED_REVIEW';
  if (event === 'tests_fail' && loop.state === 'TESTING' && loop.repair_cycles < 1) next.repair_cycles += 1;
  if (!STATES.includes(next.state)) throw new Error(`invalid loop state: ${next.state}`);
  return next;
}

function buildPRBody(finding, loop, refs = {}) {
  return redact(`## QA finding\n- Finding: ${finding.finding_id}\n- Classification: ${loop.classification}\n- Fingerprint: ${loop.fingerprint}\n- Specialist: ${loop.specialist}\n\n## Evidence\n- Original QA: ${refs.original_qa || 'required'}\n- Re-run QA: ${refs.rerun_qa || 'required'}\n- Eval: ${refs.eval || 'required'}\n- Reviewer: ${refs.reviewer || 'required'}\n\nManual merge and production deployment remain required.`);
}

if (require.main === module) {
  const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  process.stdout.write(`${JSON.stringify(createLoop(input), null, 2)}\n`);
}

module.exports = { STATES, validateFinding, findingFingerprint, classifyFinding, triageFinding, dedupeFinding, conservativeScope, createLoop, advanceLoop, buildPRBody };
