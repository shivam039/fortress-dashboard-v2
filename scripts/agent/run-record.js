#!/usr/bin/env node
'use strict';

/*
 * Run records (AGENT1B Phase 30). Extends the existing
 * .agent-room/coordination/session-log-format.md convention instead of
 * inventing a parallel .agent-runs/ directory — records land in
 * .agent-room/sessions/ using that doc's own naming convention
 * (YYYY-MM-DD-HH-MM-<topic>.md).
 *
 * Structurally cannot record a secret: this module only ever serializes
 * the fixed field list below, never a raw prompt, env dump, or config
 * object that might carry a credential.
 */

const fs = require('fs');
const path = require('path');
const lib = require('./lib');

const SESSIONS_DIR = path.join(lib.REPO_ROOT, '.agent-room', 'sessions');

const RECORD_FIELDS = [
  'run_id', 'task_id', 'issue', 'agent', 'provider', 'model',
  'input_budget', 'output_budget', 'started', 'finished', 'branch',
  'files_changed', 'tests', 'review_verdict', 'docs_impact', 'pr',
  'final_state',
];

function buildRecord(fields) {
  const record = {};
  for (const key of RECORD_FIELDS) {
    record[key] = Object.prototype.hasOwnProperty.call(fields, key) ? fields[key] : null;
  }
  return record;
}

function renderMarkdown(record, topic) {
  const lines = [`# Agent run — ${topic}`, ''];
  for (const key of RECORD_FIELDS) {
    const value = record[key];
    const rendered = Array.isArray(value) ? JSON.stringify(value) : (value == null ? '(none)' : String(value));
    lines.push(`- **${key}**: ${rendered}`);
  }
  lines.push('');
  return lines.join('\n');
}

function timestampPrefix(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}-${pad(date.getUTCHours())}-${pad(date.getUTCMinutes())}`;
}

function writeRunRecord(fields, { topic, now } = {}) {
  const record = buildRecord(fields);
  const slugTopic = topic || `agent-run-${record.task_id || 'unknown'}`;
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
  const filename = `${timestampPrefix(now)}-${slugTopic}.md`;
  const filepath = path.join(SESSIONS_DIR, filename);
  fs.writeFileSync(filepath, renderMarkdown(record, slugTopic), 'utf8');
  return filepath;
}

module.exports = { RECORD_FIELDS, buildRecord, renderMarkdown, writeRunRecord, SESSIONS_DIR };
