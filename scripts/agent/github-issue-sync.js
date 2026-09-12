#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');

const SECRET = /(authorization|cookie|api[-_]?key|token|password)\s*[:=]\s*[^\s,;]+/gi;
const ACTIONABLE = new Set(['AUTO_TRIAGE_ELIGIBLE', 'REQUIRES_PRODUCT_DECISION']);

function sanitize(value) {
  if (typeof value === 'string') return value.replace(SECRET, '$1=[REDACTED]').slice(0, 2000);
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, /authorization|cookie|api[-_]?key|token|password/i.test(key) ? '[REDACTED]' : sanitize(item)]));
  return value;
}

function fingerprint(finding) {
  const safe = [finding.surface, finding.scenario, finding.route, finding.error_signature]
    .map((value) => String(value || '').trim().toLowerCase()).join('|');
  return crypto.createHash('sha256').update(safe).digest('hex');
}

function validateFinding(finding) {
  for (const field of ['finding_id', 'run_id', 'surface', 'scenario', 'classification', 'severity', 'observed', 'expected']) {
    if (!finding?.[field]) throw new Error(`finding.${field} is required`);
  }
  if (!ACTIONABLE.has(finding.classification)) throw new Error('finding.classification is not issue eligible');
  return sanitize(finding);
}

function issueLabels(finding) {
  const labels = ['agent-found', 'qa', `severity:${String(finding.severity).toLowerCase()}`];
  if (finding.classification === 'REQUIRES_PRODUCT_DECISION') labels.push('product-decision');
  if (finding.category === 'documentation') labels.push('documentation');
  return labels;
}

function buildIssue(finding, state = 'DETECTED') {
  const clean = validateFinding(finding);
  const id = fingerprint(clean);
  return { fingerprint: id, title: `[QA] ${clean.surface}: ${clean.scenario}`.slice(0, 240), labels: issueLabels(clean), body: [
    `Finding ID: ${clean.finding_id}`, `QA Run ID: ${clean.run_id}`, `Fingerprint: ${id}`,
    `Surface: ${clean.surface}`, `Scenario: ${clean.scenario}`, `Severity: ${clean.severity}`,
    `Classification: ${clean.classification}`, `Observed: ${clean.observed}`, `Expected: ${clean.expected}`,
    `Route: ${clean.route || 'N/A'}`, `Environment: ${clean.environment || 'N/A'}`,
    `Specialist: ${clean.specialist || 'unassigned'}`, `Pipeline state: ${state}`,
    '', `Evidence: ${JSON.stringify(clean.evidence || {})}`,
    '', clean.classification === 'REQUIRES_PRODUCT_DECISION' ? 'Autonomous implementation is blocked pending product decision.' : 'Actionable deterministic finding. Human approval remains required.',
  ].join('\n') };
}

async function syncFinding(finding, { client, state = 'DETECTED' } = {}) {
  const issue = buildIssue(finding, state);
  if (!client || typeof client.findOpenByFingerprint !== 'function') return { status: 'GITHUB_SYNC_BLOCKED_AUTH', issue };
  const existing = await client.findOpenByFingerprint(issue.fingerprint);
  if (existing) {
    if (typeof client.update !== 'function') return { status: 'GITHUB_SYNC_BLOCKED_AUTH', issue, existing };
    return { status: 'UPDATED', issue_number: existing.number, issue, result: await client.update(existing.number, { body: issue.body, labels: issue.labels }) };
  }
  if (typeof client.create !== 'function') return { status: 'GITHUB_SYNC_BLOCKED_AUTH', issue };
  return { status: 'CREATED', issue, result: await client.create({ title: issue.title, body: issue.body, labels: issue.labels }) };
}

module.exports = { ACTIONABLE, sanitize, fingerprint, validateFinding, issueLabels, buildIssue, syncFinding };
