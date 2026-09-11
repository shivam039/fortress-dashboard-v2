#!/usr/bin/env node
'use strict';

/*
 * Tests for the AGENT1A framework (scripts/agent/*, agents/*.md,
 * config/agents.example.yaml). Zero dependencies — Node's built-in test
 * runner. Run with: node --test scripts/agent/agent-system.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const lib = require('./lib');
const { validateBudget } = require('./validate-budget');
const { selectAgent } = require('./select-agent');
const { buildPrompt, loadTask } = require('./build-agent-prompt');

const EXAMPLE_CONFIG_PATH = path.join(lib.REPO_ROOT, 'config', 'agents.example.yaml');
const EXAMPLE_TASK_PATH = path.join(lib.REPO_ROOT, '.agent-tasks', 'example-task.yaml');

function loadExampleConfig() {
  return lib.loadConfig(EXAMPLE_CONFIG_PATH).config;
}

// 1. all required agent role files exist
test('all required agent role files exist', () => {
  for (const name of lib.REQUIRED_AGENTS) {
    assert.ok(lib.agentExists(name), `missing agents/${name}.md`);
  }
});

// 2. config parses
test('example config parses into an object with agents/defaults/ceilings', () => {
  const config = loadExampleConfig();
  assert.ok(config.defaults, 'defaults missing');
  assert.ok(config.agents, 'agents missing');
  assert.ok(config.ceilings, 'ceilings missing');
});

// 3. unknown agent rejected
test('unknown agent is rejected by selectAgent', () => {
  const config = loadExampleConfig();
  assert.throws(() => selectAgent('not-a-real-agent', config), /unknown agent/);
});

// 4. invalid provider rejected or handled intentionally
test('unknown provider is a warning, not silently accepted as a known provider', () => {
  const config = { defaults: { provider: 'totally-made-up', input_budget: 100, output_budget: 100 }, agents: {} };
  const resolved = lib.resolveAgentBudget(config, 'backend');
  assert.equal(resolved.provider, 'totally-made-up');
  assert.equal(lib.KNOWN_PROVIDERS.has(resolved.provider), false);
});

// 5. missing budget rejected
test('missing input/output budget fails validation', () => {
  const config = { defaults: {}, agents: {} };
  const result = validateBudget(config, 'backend');
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.includes('input_budget')));
});

// 6. negative budget rejected
test('negative budget fails validation', () => {
  const config = { defaults: { input_budget: -100, output_budget: 100 }, agents: {} };
  const result = validateBudget(config, 'backend');
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.includes('positive')));
});

// 7. per-agent override works
test('per-agent budget overrides the default', () => {
  const config = {
    defaults: { input_budget: 100, output_budget: 100, provider: 'codex' },
    agents: { backend: { input_budget: 9999 } },
  };
  const resolved = lib.resolveAgentBudget(config, 'backend');
  assert.equal(resolved.input_budget, 9999);
  assert.equal(resolved.output_budget, 100); // falls back to default
});

// 8. project ceiling works
test('budget exceeding the project ceiling fails validation', () => {
  const config = {
    ceilings: { max_input_tokens: 500, max_output_tokens: 500 },
    defaults: { input_budget: 1000, output_budget: 100, provider: 'codex' },
    agents: {},
  };
  const result = validateBudget(config, 'backend');
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.includes('ceiling')));
});

// 9. prompt builder includes role/task/budget
test('generated prompt includes role mission, task id, and budget', () => {
  const config = loadExampleConfig();
  const resolved = selectAgent('backend', config);
  const roleFileText = fs.readFileSync(path.join(lib.AGENTS_DIR, 'backend.md'), 'utf8');
  const task = loadTask(EXAMPLE_TASK_PATH);
  const prompt = buildPrompt({ agentName: 'backend', roleFileText, task, resolved });
  assert.match(prompt, /## MISSION/);
  assert.match(prompt, /example-001/);
  assert.match(prompt, /input_budget: 9000/);
});

// 10. prompt builder does not include env secrets
test('prompt builder never touches process.env and cannot leak a secret', () => {
  process.env.AGENT1A_TEST_SECRET = 'should-never-appear-in-prompt';
  try {
    const config = loadExampleConfig();
    const resolved = selectAgent('backend', config);
    const roleFileText = fs.readFileSync(path.join(lib.AGENTS_DIR, 'backend.md'), 'utf8');
    const task = loadTask(EXAMPLE_TASK_PATH);
    const prompt = buildPrompt({ agentName: 'backend', roleFileText, task, resolved });
    assert.ok(!prompt.includes('should-never-appear-in-prompt'));
  } finally {
    delete process.env.AGENT1A_TEST_SECRET;
  }
});

// 11. infra role defaults production access=false
test('infra agent defaults production_access to false', () => {
  const config = loadExampleConfig();
  const resolved = lib.resolveAgentBudget(config, 'infra');
  assert.equal(resolved.production_access, false);
});

// 12. coordinator cannot be implementation target if contract says classification-only
test('coordinator is marked classification-only and non-implementation', () => {
  assert.ok(lib.CLASSIFICATION_ONLY_AGENTS.has('coordinator'));
  assert.ok(lib.NON_IMPLEMENTATION_AGENTS.has('coordinator'));
  const text = fs.readFileSync(path.join(lib.AGENTS_DIR, 'coordinator.md'), 'utf8');
  assert.match(text.replace(/\s+/g, ' '), /must not implement code/i);
});

// 13. reviewer role is non-implementation
test('reviewer is marked non-implementation and its role file says so', () => {
  assert.ok(lib.NON_IMPLEMENTATION_AGENTS.has('reviewer'));
  const text = fs.readFileSync(path.join(lib.AGENTS_DIR, 'reviewer.md'), 'utf8');
  assert.match(text.replace(/\s+/g, ' '), /must not implement/i);
});

// 14. docs role contract includes current-reality rule
test('docs role contract states docs describe current merged reality', () => {
  const text = fs.readFileSync(path.join(lib.AGENTS_DIR, 'docs.md'), 'utf8');
  assert.match(text.replace(/\s+/g, ' '), /current merged reality/i);
});

// 15. dry-run works without any API key
test('build-agent-prompt dry run works with no API-key-shaped env vars set', () => {
  const before = { ...process.env };
  for (const key of Object.keys(process.env)) {
    if (/key|token|secret/i.test(key)) delete process.env[key];
  }
  try {
    const config = loadExampleConfig();
    const resolved = selectAgent('backend', config);
    const roleFileText = fs.readFileSync(path.join(lib.AGENTS_DIR, 'backend.md'), 'utf8');
    const task = loadTask(EXAMPLE_TASK_PATH);
    const prompt = buildPrompt({ agentName: 'backend', roleFileText, task, resolved });
    assert.ok(prompt.length > 0);
  } finally {
    process.env = before;
  }
});
