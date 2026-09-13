#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

// FORTRESS "LUNA MISSES CLOSEOUT" Epic 1: Reviewer must evaluate evidence,
// not merely green checks. Previously createReview() only checked (a)
// changed_files non-empty, (b) testReport.status === 'PASS', (c)
// evalReport.status in [PASS,WARN] with no hard_failures - it never
// looked at WHICH files changed, so a core-logic change with no
// corresponding test-file change (existing unrelated tests still green)
// returned MERGEABLE. Proven by reviewer-evidence-gap.test.js's fixture
// reintroducing PR #67's bug class (latest-price-as-baseline instead of
// a point-in-time anchor). That regression test's fixture is preserved
// per this epic's explicit instruction not to delete or weaken it - its
// assertion now expects the fixed verdict (NOT_MERGEABLE).
//
// This is a deterministic, path-based evidence policy - not a semantic
// diff-analysis framework. It answers three questions per the epic's own
// framing: what changed (category), what could break (the category's
// blast radius), what evidence proves it didn't (a matching evidence
// file in the same changed-file list).

// Category classification, most-specific-first (a file lands in exactly
// one category).
const CATEGORY_RULES = [
  { category: 'tests', test: (f) => /(^|\/)tests\//.test(f) || /\.test\.(js|ts|tsx|mjs)$/.test(f) || /^frontend\/e2e\//.test(f) },
  { category: 'docs', test: (f) => /^docs\//.test(f) || /(^|\/)(README|AGENTS)\.md$/i.test(f) || /\.md$/i.test(f) },
  { category: 'security_auth', test: (f) => /auth/i.test(f) || /security_config/i.test(f) },
  { category: 'agent_framework', test: (f) => /^scripts\/agent/.test(f) || /^agents\//.test(f) || /^config\/agents/.test(f) || /^\.github\/workflows\/agent-/.test(f) },
  { category: 'infra_workflow', test: (f) => /^\.github\/workflows\//.test(f) || /^Dockerfile/.test(f) || /^docker-compose/.test(f) || /^Caddyfile/.test(f) || /^scripts\/deploy-/.test(f) },
  { category: 'api_contract', test: (f) => /^engine\/routers\//.test(f) },
  { category: 'db_persistence', test: (f) => /^engine\/utils\/db\.py$/.test(f) },
  { category: 'backend_logic', test: (f) => /^engine\//.test(f) && f.endsWith('.py') },
  { category: 'frontend_logic', test: (f) => /^frontend\/src\//.test(f) },
];

function classifyFile(file) {
  for (const rule of CATEGORY_RULES) if (rule.test(file)) return rule.category;
  return 'other';
}

// A category here requires at least one changed file that looks like
// relevant evidence for it. 'tests', 'docs', and 'other' are absent from
// this map on purpose - they never require evidence (a docs-only or
// test-only PR, or an unclassified file like package.json, is not held
// to a test-evidence bar it can't sensibly clear).
const EVIDENCE_REQUIREMENTS = {
  backend_logic: { label: 'backend test evidence', test: (files) => files.some((f) => /^tests\/backend\//.test(f) || /^tests\/[^/]*\.py$/.test(f)) },
  db_persistence: { label: 'backend test evidence', test: (files) => files.some((f) => /^tests\/backend\//.test(f)) },
  api_contract: { label: 'backend contract test or frontend integration evidence', test: (files) => files.some((f) => /^tests\/backend\//.test(f) || /^frontend\/e2e\//.test(f) || /^frontend\/tests\//.test(f)) },
  frontend_logic: { label: 'frontend unit/E2E evidence', test: (files) => files.some((f) => /^frontend\/tests\//.test(f) || /^frontend\/e2e\//.test(f) || /\.test\.(ts|tsx|js|jsx)$/.test(f)) },
  security_auth: { label: 'focused security/auth test evidence', test: (files) => files.some((f) => /^tests\//.test(f) && (/auth/i.test(f) || /security/i.test(f))) },
  infra_workflow: { label: 'workflow validation/static test evidence', test: (files) => files.some((f) => /^tests\/backend\/test_.*workflow.*\.py$/i.test(f)) },
  agent_framework: { label: 'agent framework test evidence', test: (files) => files.some((f) => /^scripts\/agent.*\.test\.js$/.test(f) || /^tests\/agent(-eval)?\//.test(f)) },
};

function evidenceGaps(changedFiles) {
  const present = new Set(changedFiles.map(classifyFile));
  const gaps = [];
  for (const category of Object.keys(EVIDENCE_REQUIREMENTS)) {
    if (!present.has(category)) continue;
    const { label, test } = EVIDENCE_REQUIREMENTS[category];
    if (!test(changedFiles)) gaps.push({ category, label });
  }
  return gaps;
}

// An explicit waiver must carry a human-legible reason - see
// docs/agents/AGENT4_PIPELINE.md's "test evidence waiver" section. Never
// settable from provider/agent output: it flows through the manifest the
// same way allowed_files/production_access do (Coordinator classification
// time only), not through import-result.
function waivedCategories(waiver) {
  if (!waiver || typeof waiver.reason !== 'string' || !waiver.reason.trim()) return new Set();
  if (Array.isArray(waiver.categories) && waiver.categories.length) return new Set(waiver.categories);
  return new Set(Object.keys(EVIDENCE_REQUIREMENTS)); // no categories named = applies to any gap found
}

// A category requiring evidence, present in the diff, whose ONLY executed
// test command was the generic no-op fallback (test-runner.js's
// selectTests() falls back to `git diff --check` when nothing else
// matches) counts as evidence never having actually run - distinct from
// "ran and failed."
function onlyTrivialTestRan(testReport, changedFiles) {
  const commands = Array.isArray(testReport.commands) ? testReport.commands : [];
  if (!commands.length || !commands.every((c) => String(c).trim() === 'git diff --check')) return false;
  return changedFiles.some((f) => Object.prototype.hasOwnProperty.call(EVIDENCE_REQUIREMENTS, classifyFile(f)));
}

function createReview({ manifest, testReport, evalReport, artifactDir }) {
  const changedFiles = manifest.changed_files || [];

  if (!changedFiles.length) {
    return writeReport({
      run_id: manifest.run_id, role: 'reviewer', verdict: 'BLOCKED',
      findings: ['No changed files were evidenced.'], notes: [],
      production_impact: manifest.production_impact || 'NONE', docs_required: manifest.docs_required === true,
      completed_at: new Date().toISOString(),
    }, manifest.run_id, artifactDir);
  }

  const findings = [];
  const notes = [];

  if (testReport.status !== 'PASS') findings.push('Task tests did not pass.');
  if (!['PASS', 'WARN'].includes(evalReport.status) || (evalReport.hard_failures || []).length) {
    findings.push('Agent evaluation did not pass safely.');
  }
  if (onlyTrivialTestRan(testReport, changedFiles)) {
    findings.push('Required tests were not executed for the changed files (only a no-op diff check ran).');
  }

  const waived = waivedCategories(manifest.test_waiver);
  for (const gap of evidenceGaps(changedFiles)) {
    if (waived.has(gap.category)) {
      notes.push(`Evidence gap for '${gap.category}' (${gap.label}) waived: ${manifest.test_waiver.reason}`);
    } else {
      findings.push(`Changed files include '${gap.category}' with no ${gap.label}.`);
    }
  }

  const verdict = findings.length ? 'NOT_MERGEABLE' : (notes.length ? 'MERGEABLE_WITH_NOTES' : 'MERGEABLE');

  return writeReport({
    run_id: manifest.run_id, role: 'reviewer', verdict, findings, notes,
    production_impact: manifest.production_impact || 'NONE', docs_required: manifest.docs_required === true,
    completed_at: new Date().toISOString(),
  }, manifest.run_id, artifactDir);
}

function writeReport(report, runId, artifactDir) {
  const artifact = path.join(artifactDir, `${runId}.review-report.json`);
  fs.writeFileSync(artifact, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  return { ...report, artifact };
}

module.exports = { createReview, classifyFile, evidenceGaps, onlyTrivialTestRan, CATEGORY_RULES, EVIDENCE_REQUIREMENTS };

if (require.main === module) {
  const [manifestPath, testPath, evalPath, artifactDir = '.agent-room/sessions'] = process.argv.slice(2);
  if (!manifestPath || !testPath || !evalPath) process.exit(2);
  const result = createReview({ manifest: JSON.parse(fs.readFileSync(manifestPath, 'utf8')),
    testReport: JSON.parse(fs.readFileSync(testPath, 'utf8')),
    evalReport: JSON.parse(fs.readFileSync(evalPath, 'utf8')), artifactDir });
  console.log(JSON.stringify(result));
}
