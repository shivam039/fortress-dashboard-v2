#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { loadCases, scoreCase, staticResultFor, summarize } = require('./lib');

const manifestPath = process.argv[2];
if (!manifestPath) {
  console.error('usage: run-gate.js <run-manifest.json> [report.json]');
  process.exit(2);
}
const manifest = JSON.parse(fs.readFileSync(path.resolve(manifestPath), 'utf8'));
const groups = new Set(manifest.eval_groups || []);
const selected = loadCases().filter(({ caseData }) => groups.has(caseData.category));
if (!selected.length) throw new Error('manifest selected no known eval groups');
const results = selected.map(({ caseData }) => scoreCase(caseData, staticResultFor(caseData)));
const summary = summarize(results, { mode: 'STATIC_GATE' });
const report = { status: summary.status, score: summary.score,
  hard_failures: summary.hard_failures.map((item) => item.failure),
  groups: [...groups], total_cases: summary.total_cases };
if (process.argv[3]) fs.writeFileSync(path.resolve(process.argv[3]), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report, null, 2));
if (report.status === 'FAIL') process.exitCode = 1;
