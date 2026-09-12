#!/usr/bin/env node
'use strict';

/* AGENT3 integration contract. Provider output is data, never authority. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { checkScope } = require('./scope-check');

const MANIFEST_VERSION = 1;
const GOVERNANCE_FIELDS = new Set([
  'production_access', 'human_gate', 'allowed_files', 'forbidden_files',
  'input_budget', 'output_budget', 'review_required', 'auto_merge',
]);
const MANIFEST_FIELDS = [
  'manifest_version', 'run_id', 'task_id', 'issue_number', 'agent', 'provider',
  'model', 'input_budget', 'output_budget', 'production_access', 'human_gate',
  'human_gate_status', 'branch', 'allowed_files', 'forbidden_files',
  'prompt_artifact', 'provider_mode', 'provider_result_artifact',
  'provider_result_sha256', 'provider_result_imported_at', 'changed_files',
  'governance_override_attempts',
  'scope_status', 'tests', 'eval_groups', 'eval_status', 'eval_score',
  'eval_hard_failures', 'review_required', 'review_status', 'docs_required',
  'docs_status', 'repair_count', 'pr_number', 'production_impact', 'auto_merge',
  'state', 'created_at', 'updated_at',
];

function pick(source, fields) {
  return Object.fromEntries(fields.map((key) => [key, source[key] ?? null]));
}

function createManifest(input, now = new Date().toISOString()) {
  if (!input.run_id || !input.task_id) throw new Error('run_id and task_id are required');
  const value = {
    ...input,
    manifest_version: MANIFEST_VERSION,
    issue_number: input.issue_number ?? null,
    production_access: input.production_access === true,
    human_gate: input.human_gate !== false,
    human_gate_status: input.human_gate_status || 'VALID',
    allowed_files: input.allowed_files || [],
    forbidden_files: input.forbidden_files || [],
    provider_result_artifact: null,
    provider_result_sha256: null,
    provider_result_imported_at: null,
    governance_override_attempts: [],
    changed_files: [], scope_status: 'PENDING', tests: { status: 'PENDING' },
    eval_groups: selectEvalGroups(input.agent), eval_status: 'PENDING',
    eval_score: null, eval_hard_failures: [], review_required: true,
    review_status: 'PENDING', docs_required: input.docs_required === true,
    docs_status: input.docs_required === true ? 'PENDING' : 'NOT_REQUIRED',
    repair_count: 0, pr_number: null, production_impact: 'NONE',
    auto_merge: false, state: input.provider_mode === 'MANUAL_EXPORT' ? 'MANUAL_EXPORT' : 'RUNNING',
    created_at: now, updated_at: now,
  };
  return pick(value, MANIFEST_FIELDS);
}

function parseProviderResult(filePath) {
  const stat = fs.lstatSync(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('provider result must be a regular file');
  if (stat.size > 1024 * 1024) throw new Error('provider result exceeds 1 MiB limit');
  const raw = fs.readFileSync(filePath, 'utf8');
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('provider result must be a JSON object');
  return { raw, parsed };
}

function importProviderResult(manifest, resultPath, options = {}) {
  if (!['MANUAL_EXPORT', 'RESULT_IMPORTED'].includes(manifest.state)) {
    throw new Error(`cannot import result while run is ${manifest.state}`);
  }
  const { raw, parsed } = parseProviderResult(resultPath);
  if (parsed.run_id !== manifest.run_id) throw new Error('provider result run_id mismatch');
  const aliases = { claude: 'anthropic', grok: 'xai' };
  const expected = aliases[manifest.provider] || manifest.provider;
  const actual = aliases[parsed.provider] || parsed.provider;
  if (actual !== expected) throw new Error('provider mismatch');
  if (parsed.model && manifest.model && parsed.model !== manifest.model) throw new Error('model mismatch');

  const changed = Array.isArray(parsed.changed_files) ? parsed.changed_files : [];
  const scope = checkScope(changed, {
    allowedFiles: manifest.allowed_files, forbiddenFiles: manifest.forbidden_files,
  });
  const artifactDir = options.artifactDir || path.dirname(resultPath);
  const artifactName = `${manifest.run_id}.provider-result.json`;
  const artifactPath = path.join(artifactDir, artifactName);
  // Store only the operational result fields. Governance-shaped keys are ignored.
  const safeResult = {
    run_id: manifest.run_id, provider: manifest.provider, model: manifest.model,
    changed_files: changed, summary: typeof parsed.summary === 'string' ? parsed.summary.slice(0, 4000) : null,
    tests: parsed.tests && typeof parsed.tests === 'object' ? parsed.tests : null,
  };
  fs.mkdirSync(artifactDir, { recursive: true });
  fs.writeFileSync(artifactPath, `${JSON.stringify(safeResult, null, 2)}\n`, { mode: 0o600 });
  const now = options.now || new Date().toISOString();
  const attemptedGovernanceOverrides = Object.keys(parsed).filter((key) => GOVERNANCE_FIELDS.has(key));
  return {
    ...manifest, changed_files: changed, scope_status: scope.ok ? 'PASS' : 'FAIL',
    provider_result_artifact: artifactPath,
    provider_result_sha256: crypto.createHash('sha256').update(raw).digest('hex'),
    provider_result_imported_at: now,
    state: scope.ok ? 'RESULT_IMPORTED' : 'BLOCKED_SCOPE', updated_at: now,
    governance_override_attempts: attemptedGovernanceOverrides,
  };
}

function resumeRun(manifest) {
  if (manifest.state === 'VALIDATING_SCOPE') return manifest;
  if (manifest.state !== 'RESULT_IMPORTED') return manifest;
  if (manifest.scope_status !== 'PASS') return { ...manifest, state: 'BLOCKED_SCOPE' };
  return { ...manifest, state: 'VALIDATING_SCOPE', updated_at: new Date().toISOString() };
}

function selectEvalGroups(agent) {
  const groups = {
    backend: ['backend', 'security', 'reviewer'], infra: ['infra', 'security', 'reviewer'],
    docs: ['docs', 'reviewer'], coordinator: ['coordinator', 'security'],
    frontend: ['frontend', 'security', 'reviewer'], qa: ['qa', 'security', 'reviewer'],
    performance: ['performance', 'security', 'reviewer'], research: ['research', 'security', 'reviewer'],
    'agent-framework': ['coordinator', 'backend', 'frontend', 'qa', 'performance', 'infra', 'research', 'docs', 'reviewer', 'security'],
  };
  return groups[agent] || [agent, 'security', 'reviewer'].filter(Boolean);
}

function evaluateGate(manifest, report) {
  const hard = Array.isArray(report.hard_failures) ? report.hard_failures : [];
  const status = String(report.status || 'FAIL').toUpperCase();
  const failed = status === 'FAIL' || hard.length > 0;
  return { ...manifest, eval_status: `EVAL_${failed ? 'FAIL' : status}`,
    eval_score: Number.isFinite(report.score) ? report.score : null,
    eval_hard_failures: hard, state: failed ? 'BLOCKED_EVAL' : 'REVIEW_PENDING' };
}

function testGate(manifest, report) {
  const status = String(report?.status || 'FAIL').toUpperCase();
  if (!['PASS', 'FAIL'].includes(status)) throw new Error('test status must be PASS or FAIL');
  return { ...manifest, tests: { status, commands: Array.isArray(report.commands) ? report.commands : [] },
    state: status === 'PASS' ? 'EVALUATING' : 'BLOCKED_TESTS' };
}

function reviewerGate(manifest, verdict, docsImpact = false) {
  if ((manifest.eval_hard_failures || []).length || manifest.state === 'BLOCKED_EVAL') return { ...manifest, state: 'BLOCKED_EVAL' };
  if (!['MERGEABLE', 'MERGEABLE_WITH_MINOR_FIXES', 'NOT_MERGEABLE'].includes(verdict)) throw new Error('invalid reviewer verdict');
  if (verdict === 'NOT_MERGEABLE') {
    if ((manifest.repair_count || 0) >= 1) return { ...manifest, review_status: verdict, state: 'BLOCKED' };
    return { ...manifest, review_status: verdict, repair_count: 1,
      tests: { status: 'PENDING' }, eval_status: 'PENDING', eval_score: null,
      eval_hard_failures: [], state: 'REPAIR_PENDING' };
  }
  const required = manifest.docs_required || docsImpact;
  return { ...manifest, review_status: verdict, docs_required: required,
    docs_status: required ? 'PENDING' : 'NOT_REQUIRED', state: required ? 'DOCS_PENDING' : 'PR_GATE_PENDING' };
}

function docsGate(manifest, satisfied) {
  if (!manifest.docs_required) return { ...manifest, docs_status: 'NOT_REQUIRED', state: 'PR_GATE_PENDING' };
  return { ...manifest, docs_status: satisfied ? 'PASS' : 'PENDING', state: satisfied ? 'PR_GATE_PENDING' : 'DOCS_PENDING' };
}

function prGate(manifest) {
  const reviewOk = ['MERGEABLE', 'MERGEABLE_WITH_MINOR_FIXES'].includes(manifest.review_status);
  const docsOk = ['PASS', 'NOT_REQUIRED'].includes(manifest.docs_status);
  const evalOk = ['EVAL_PASS', 'EVAL_WARN'].includes(manifest.eval_status);
  const ok = manifest.scope_status === 'PASS' && manifest.tests?.status === 'PASS' && evalOk &&
    reviewOk && docsOk && manifest.human_gate_status === 'VALID' && !(manifest.eval_hard_failures || []).length;
  return { ...manifest, state: ok ? 'AWAITING_HUMAN' : 'BLOCKED_PR', auto_merge: false };
}

function recordQuality(input) {
  const total = Number.isFinite(input.input_tokens) && Number.isFinite(input.output_tokens)
    ? input.input_tokens + input.output_tokens : null;
  return { provider: input.provider, model: input.model, role: input.agent,
    eval_score: input.eval_score, review_verdict: input.review_verdict, tests: input.tests,
    hard_failures: Array.isArray(input.hard_failures) ? input.hard_failures : [],
    input_tokens: Number.isFinite(input.input_tokens) ? input.input_tokens : null,
    output_tokens: Number.isFinite(input.output_tokens) ? input.output_tokens : null,
    quality_per_1k_tokens: total > 0 && !(input.hard_failures || []).length
      ? Math.round((input.eval_score / (total / 1000)) * 100) / 100 : null };
}

function recommendProvider(records, agent, minimumSamples = 5) {
  const relevant = records.filter((r) => r.role === agent && !(r.hard_failures || []).length);
  const byProvider = new Map();
  for (const record of relevant) {
    const values = byProvider.get(record.provider) || []; values.push(record); byProvider.set(record.provider, values);
  }
  const eligible = [...byProvider].filter(([, values]) => values.length >= minimumSamples);
  if (!eligible.length) return { status: 'INSUFFICIENT_EVIDENCE', agent, minimum_samples: minimumSamples };
  const scored = eligible.map(([provider, values]) => ({ provider, samples: values.length,
    average_quality: Math.round(values.reduce((n, v) => n + v.eval_score, 0) / values.length * 100) / 100,
    average_tokens: values.every((v) => v.input_tokens != null && v.output_tokens != null)
      ? Math.round(values.reduce((n, v) => n + v.input_tokens + v.output_tokens, 0) / values.length) : null }));
  scored.sort((a, b) => b.average_quality - a.average_quality);
  const samples = scored[0].samples;
  return { status: 'ADVISORY', recommended: scored[0].provider, evidence: scored,
    confidence: samples >= 20 ? 'HIGH' : samples >= 10 ? 'MEDIUM' : 'LOW', config_changed: false };
}

function buildScoreboard(records) {
  const grouped = {};
  for (const record of records) {
    const role = record.role || 'unknown';
    const provider = record.provider || 'unknown';
    grouped[role] ||= {};
    grouped[role][provider] ||= [];
    grouped[role][provider].push(record);
  }
  return Object.fromEntries(Object.entries(grouped).map(([role, providers]) => [role,
    Object.fromEntries(Object.entries(providers).map(([provider, values]) => [provider, {
      samples: values.length,
      average_quality: Math.round(values.reduce((sum, item) => sum + item.eval_score, 0) / values.length * 100) / 100,
      recommendation_strength: values.length >= 20 ? 'HIGH' : values.length >= 10 ? 'MEDIUM' : values.length >= 5 ? 'LOW' : 'INSUFFICIENT_EVIDENCE',
    }]))]));
}

function buildUnifiedPrBody(m) {
  return ['## Task', `${m.task_id} (Issue #${m.issue_number ?? 'none'})`, `Run ID: ${m.run_id}`, '',
    '## Implementation', `Agent: ${m.agent}`, `Provider: ${m.provider}`, `Model: ${m.model}`,
    `Token Budget: input=${m.input_budget}, output=${m.output_budget}`,
    `Changed Files: ${JSON.stringify(m.changed_files || [])}`, '', '## Tests', `${m.tests?.status || 'PENDING'}`,
    '', '## Agent Eval', `Status: ${m.eval_status}`, `Score: ${m.eval_score ?? 'N/A'}`,
    `Hard failures: ${JSON.stringify(m.eval_hard_failures || [])}`, '', '## Reviewer', `${m.review_status}`,
    '', '## Docs', `${m.docs_status}`, '', '## Production Impact', `${m.production_impact || 'NONE'}`,
    '', '## Human Gate', 'AWAITING HUMAN REVIEW AND MERGE. Automated merge is disabled.'].join('\n');
}

module.exports = { MANIFEST_FIELDS, createManifest, importProviderResult, resumeRun,
  selectEvalGroups, testGate, evaluateGate, reviewerGate, docsGate, prGate, recordQuality,
  recommendProvider, buildScoreboard, buildUnifiedPrBody };
