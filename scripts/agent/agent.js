#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const lib = require('./lib');
const { plan } = require('./orchestrate-task');
const pipeline = require('./unified-pipeline');

const sessions = path.join(lib.REPO_ROOT, '.agent-room', 'sessions');
const manifestPath = (runId) => path.join(sessions, `${runId}.manifest.json`);

function save(manifest) {
  fs.mkdirSync(sessions, { recursive: true });
  const clean = Object.fromEntries(pipeline.MANIFEST_FIELDS.map((key) => [key, manifest[key] ?? null]));
  fs.writeFileSync(manifestPath(clean.run_id), `${JSON.stringify(clean, null, 2)}\n`, { mode: 0o600 });
  return clean;
}

function load(runId) {
  return JSON.parse(fs.readFileSync(manifestPath(runId), 'utf8'));
}

function planCommand(taskPath, configPath) {
  const result = plan(path.resolve(taskPath), configPath);
  if (!['MANUAL_EXPORT', 'RUNNING'].includes(result.state)) return result;
  const runId = result.run_id;
  const promptArtifact = path.join(sessions, `${runId}.prompt.md`);
  fs.writeFileSync(promptArtifact, result.prompt, { mode: 0o600 });
  const manifest = pipeline.createManifest({
    run_id: runId, task_id: result.task_id, issue_number: result.issue_number,
    agent: result.agent, provider: result.provider, model: result.model,
    input_budget: result.input_budget, output_budget: result.output_budget,
    production_access: result.production_access, human_gate: result.human_approval_required,
    branch: result.branch, allowed_files: result.allowed_files || [],
    forbidden_files: result.forbidden_files || [], prompt_artifact: promptArtifact,
    provider_mode: result.provider_mode, docs_required: result.docs_required,
  });
  save(manifest);
  return { ...manifest, manual_action: result.provider_mode === 'MANUAL_EXPORT' ? {
    provider: result.provider, model: result.model, prompt_artifact: promptArtifact,
    where: `Run the prompt in ${result.provider} using the configured model.`,
    expected_response: 'JSON object containing run_id, provider, model, changed_files, summary, and optional tests.',
    import: `node scripts/agent/agent.js import-result ${runId} result.json`,
    resume: `node scripts/agent/agent.js resume ${runId}`,
  } : null };
}

function main() {
  const [command, idOrPath, extra] = process.argv.slice(2);
  let result;
  if (command === 'plan') result = planCommand(idOrPath, extra);
  else if (command === 'import-result') result = save(pipeline.importProviderResult(load(idOrPath), path.resolve(extra), { artifactDir: sessions }));
  else if (command === 'resume') result = save(pipeline.resumeRun(load(idOrPath)));
  else if (command === 'tests') result = save(pipeline.testGate(load(idOrPath), JSON.parse(fs.readFileSync(extra, 'utf8'))));
  else if (command === 'eval') result = save(pipeline.evaluateGate(load(idOrPath), JSON.parse(fs.readFileSync(extra, 'utf8'))));
  else if (command === 'review') result = save(pipeline.reviewerGate(load(idOrPath), extra));
  else if (command === 'docs') result = save(pipeline.docsGate(load(idOrPath), extra === 'pass'));
  else if (command === 'pr-ready') result = save(pipeline.prGate(load(idOrPath)));
  else if (command === 'recommend-provider') result = pipeline.recommendProvider(JSON.parse(fs.readFileSync(extra, 'utf8')), idOrPath);
  else if (command === 'scoreboard') result = pipeline.buildScoreboard(JSON.parse(fs.readFileSync(idOrPath, 'utf8')));
  else {
    console.error('Usage: agent.js <plan|import-result|resume|tests|eval|review|docs|pr-ready|recommend-provider|scoreboard> ...');
    process.exit(2);
  }
  console.log(JSON.stringify(result, null, 2));
  if (/^BLOCKED/.test(result.state || '')) process.exitCode = 1;
}

if (require.main === module) main();
module.exports = { save, load, planCommand, manifestPath };
