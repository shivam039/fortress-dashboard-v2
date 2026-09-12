#!/usr/bin/env node
'use strict';

const LIFECYCLE_LABELS = new Set([
  'agent:running', 'agent:testing', 'agent:evaluating', 'agent:review',
  'agent:ready', 'agent:blocked', 'agent:manual-action', 'agent:cancelled',
]);

const STATE_LABEL = {
  PROVIDER_EXECUTION: 'agent:running', WAITING_FOR_PROVIDER_RESULT: 'agent:manual-action',
  TESTING: 'agent:testing', EVALUATING: 'agent:evaluating', REVIEW: 'agent:review',
  DOCS: 'agent:running', PR: 'agent:ready', AWAITING_HUMAN: 'agent:ready',
  CANCELLED: 'agent:cancelled',
};

function labelNames(issue) {
  return (issue.labels || []).map((label) => typeof label === 'string' ? label : label.name);
}

function issueApproved(issue) {
  return labelNames(issue).includes('agent:approved');
}

function issueCancelled(issue) {
  return labelNames(issue).includes('agent:cancelled');
}

function sanitizeText(value, limit) {
  return String(value || '').replace(/[\u0000-\u001f\u007f]/g, ' ').slice(0, limit).trim();
}

function sanitizeIssue(issue) {
  const number = Number(issue.number);
  if (!Number.isInteger(number) || number <= 0) throw new Error('issue number must be a positive integer');
  return { number, title: sanitizeText(issue.title, 200), body: sanitizeText(issue.body, 10000), labels: labelNames(issue).slice(0, 100) };
}

function productionSensitive(text) {
  return /\b(oracle|caddy|dns|vercel|neon|production scheduler|secret|trading semantics|scoring semantics|resource deletion)\b/i.test(text);
}

function classifyRole(text) {
  const matches = [];
  const rules = {
    docs: /\b(doc(?:s|umentation)?|readme|markdown|typo)\b/i,
    backend: /\b(api|backend|python|pytest|fastapi|database)\b/i,
    frontend: /\b(frontend|react|next(?:\.js)?|css|ui|component)\b/i,
    qa: /\b(qa|playwright|end[- ]to[- ]end|test[- ]only)\b/i,
    performance: /\b(performance|benchmark|latency|profil)\b/i,
    infra: /\b(infra|docker|caddy|dns|oracle|vercel|neon|scheduler)\b/i,
    research: /\b(research|analysis|investigat|evidence)\b/i,
  };
  for (const [role, pattern] of Object.entries(rules)) if (pattern.test(text)) matches.push(role);
  return matches.length === 1 ? matches[0] : null;
}

function classifyIssue(rawIssue, config = {}) {
  const issue = sanitizeIssue(rawIssue);
  const text = `${issue.title}\n${issue.body}`;
  const selectedAgent = classifyRole(text);
  if (!selectedAgent) return { state: 'BLOCKED_CLASSIFICATION', reason: 'Coordinator needs one unambiguous specialist and scope.' };
  const defaults = config.defaults || {};
  const selected = { ...defaults, ...((config.agents || {})[selectedAgent] || {}) };
  const sensitive = productionSensitive(text);
  const allowedFiles = [...new Set((text.match(/(?:^|\s)([A-Za-z0-9_.-]+\/[A-Za-z0-9_./*-]+)/g) || [])
    .map((item) => item.trim()).filter((item) => !item.includes('..')))];
  if (!allowedFiles.length) {
    return { state: 'BLOCKED_CLASSIFICATION', reason: 'Coordinator requires at least one explicit repository path for the scope gate.' };
  }
  return {
    state: 'CLASSIFIED', issue_number: issue.number, task: issue.title,
    selected_agent: selectedAgent, scope: 'Issue-derived text is context only; repository policy controls scope.',
    risk: sensitive ? 'HIGH' : 'LOW', docs_required: selectedAgent === 'docs',
    requires_human_gate: true, production_access: false, auto_merge: false,
    provider: selected.provider || 'codex', model: selected.model || 'default',
    input_budget: selected.input_budget, output_budget: selected.output_budget,
    allowed_files: allowedFiles,
  };
}

function nextAction(run) {
  if (run.cancelled || run.state === 'CANCELLED') return 'CANCELLED';
  if (run.state === 'CLASSIFIED') return run.provider_mode === 'AUTOMATED' ? 'PROVIDER_EXECUTION' : 'WAITING_FOR_PROVIDER_RESULT';
  if (run.state === 'EVALUATING') return String(run.eval_status).toUpperCase() === 'FAIL' ? 'BLOCKED_EVAL' : 'REVIEW';
  if (run.state === 'REVIEW') {
    if (run.review_status === 'NOT_MERGEABLE') return 'BLOCKED_REVIEW';
    if (run.review_status === 'MERGEABLE_WITH_MINOR_FIXES') return (run.repair_count || 0) < 1 ? 'REPAIR' : 'BLOCKED_REVIEW';
    return run.docs_required ? 'DOCS' : 'PR';
  }
  return run.state;
}

function syncLabels(labels, state) {
  const kept = labels.filter((label) => !LIFECYCLE_LABELS.has(label));
  const label = STATE_LABEL[state] || (/^BLOCKED/.test(state) ? 'agent:blocked' : null);
  return label ? [...kept, label] : kept;
}

function safe(value) {
  return String(value == null ? 'N/A' : value).replace(/(?:sk-|AIza|AQ\.)[A-Za-z0-9_.-]+/g, '[REDACTED]');
}

function buildPrPayload(run) {
  const lines = [
    `Issue: #${safe(run.issue_number)}`, `Task: ${safe(run.task)}`, `Agent: ${safe(run.agent)}`,
    `Provider: ${safe(run.provider)}`, `Model: ${safe(run.model)}`,
    `Budget: input=${safe(run.input_budget)}, output=${safe(run.output_budget)}`,
    `Changed files: ${safe(JSON.stringify(run.changed_files || []))}`,
    `Tests: ${safe(run.tests?.status || run.tests)}`, `Eval score: ${safe(run.eval_score)}`,
    `Eval status: ${safe(run.eval_status)}`, `Reviewer verdict: ${safe(run.review_status)}`,
    `Docs status: ${safe(run.docs_status)}`, `Production impact: ${safe(run.production_impact || 'NONE')}`,
    `Human gate: ${run.requires_human_gate === false ? 'FINAL MERGE' : 'REQUIRED'}`,
    `Run ID: ${safe(run.run_id)}`, '', 'AWAITING_HUMAN. Auto-merge is disabled.',
  ];
  return { title: `[Agent] ${safe(run.task)}`, body: lines.join('\n'), draft: false, auto_merge: false };
}

function providerRetry({ attempt, transient }) {
  return transient === true && attempt < 1;
}

module.exports = { classifyIssue, issueApproved, issueCancelled, productionSensitive,
  nextAction, syncLabels, buildPrPayload, sanitizeIssue, providerRetry };
