#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

function createReview({ manifest, testReport, evalReport, artifactDir }) {
  const findings = [];
  if (!manifest.changed_files || !manifest.changed_files.length) findings.push('No changed files were evidenced.');
  if (testReport.status !== 'PASS') findings.push('Task tests did not pass.');
  if (!['PASS', 'WARN'].includes(evalReport.status) || (evalReport.hard_failures || []).length) findings.push('Agent evaluation did not pass safely.');
  const report = { run_id: manifest.run_id, role: 'reviewer',
    verdict: findings.length ? 'NOT_MERGEABLE' : 'MERGEABLE', findings,
    production_impact: manifest.production_impact || 'NONE', docs_required: manifest.docs_required === true,
    completed_at: new Date().toISOString() };
  const artifact = path.join(artifactDir, `${manifest.run_id}.review-report.json`);
  fs.writeFileSync(artifact, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  return { ...report, artifact };
}

module.exports = { createReview };

if (require.main === module) {
  const [manifestPath, testPath, evalPath, artifactDir = '.agent-room/sessions'] = process.argv.slice(2);
  if (!manifestPath || !testPath || !evalPath) process.exit(2);
  const result = createReview({ manifest: JSON.parse(fs.readFileSync(manifestPath, 'utf8')),
    testReport: JSON.parse(fs.readFileSync(testPath, 'utf8')),
    evalReport: JSON.parse(fs.readFileSync(evalPath, 'utf8')), artifactDir });
  console.log(JSON.stringify(result));
}
