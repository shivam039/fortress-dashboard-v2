#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function selectTests(changedFiles, agent, explicitCommand) {
  if (explicitCommand) return [explicitCommand];
  const files = changedFiles || [];
  if (files.some((file) => file.startsWith('scripts/agent') || file.startsWith('scripts/agent-eval') || file.startsWith('tests/agent'))) {
    return ['node --test scripts/agent/*.test.js tests/agent/*.test.js tests/agent-eval/*.test.js'];
  }
  if (agent === 'docs' || files.every((file) => /(^|\/)(README|docs\/|.*\.md$)/i.test(file))) {
    return ['git diff --check'];
  }
  if (files.some((file) => file.endsWith('.py'))) return ['pytest -q'];
  if (files.some((file) => file.startsWith('frontend/'))) return ['npm test -- --runInBand'];
  return ['git diff --check'];
}

function runTests({ runId, changedFiles, agent, explicitCommand, artifactDir }) {
  const commands = selectTests(changedFiles, agent, explicitCommand);
  const started = new Date().toISOString();
  const results = commands.map((command) => {
    const result = spawnSync(command, { shell: true, encoding: 'utf8' });
    return { command, exit_code: result.status == null ? 1 : result.status,
      output: `${result.stdout || ''}${result.stderr || ''}`.slice(-12000) };
  });
  const status = results.every((result) => result.exit_code === 0) ? 'PASS' : 'FAIL';
  const report = { run_id: runId, commands, exit_codes: results.map((r) => r.exit_code),
    status, started_at: started, completed_at: new Date().toISOString(), results };
  const file = path.join(artifactDir, `${runId}.test-report.json`);
  fs.mkdirSync(artifactDir, { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  return { ...report, artifact: file };
}

module.exports = { selectTests, runTests };
