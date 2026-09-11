#!/usr/bin/env node
'use strict';

/*
 * Shared helpers for scripts/agent/*.js. Zero dependencies, matching
 * .agent-room/hooks/'s style. Includes a deliberately minimal YAML
 * subset parser (mappings + nested mappings + scalars only — no lists,
 * anchors, or multi-line strings) sufficient for config/agents.*.yaml's
 * shape. Do not extend this into a general-purpose YAML parser; if the
 * config ever needs lists/anchors, switch to a real library instead.
 */

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const AGENTS_DIR = path.join(REPO_ROOT, 'agents');
const REQUIRED_AGENTS = [
  'coordinator', 'backend', 'frontend', 'qa', 'performance',
  'infra', 'research', 'docs', 'reviewer',
];
const CLASSIFICATION_ONLY_AGENTS = new Set(['coordinator']);
const NON_IMPLEMENTATION_AGENTS = new Set(['coordinator', 'reviewer']);
const KNOWN_PROVIDERS = new Set(['codex', 'anthropic', 'xai', 'gemini']);

function parseScalar(raw) {
  const v = raw.trim();
  if (v === '' ) return null;
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (/^-?\d+$/.test(v)) return parseInt(v, 10);
  if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v);
  // Flow sequence: [a, b, c] — the only list form this parser supports.
  if (v.startsWith('[') && v.endsWith(']')) {
    const inner = v.slice(1, -1).trim();
    if (inner === '') return [];
    return inner.split(',').map((item) => parseScalar(item.trim()));
  }
  // Strip matching surrounding quotes, if present.
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    return v.slice(1, -1);
  }
  return v;
}

function stripComment(line) {
  // Simple: our config never needs a literal '#' inside a scalar value.
  const idx = line.indexOf('#');
  return idx === -1 ? line : line.slice(0, idx);
}

function parseMiniYaml(text) {
  const root = {};
  const stack = [{ indent: -1, obj: root }];
  const lines = text.split('\n');

  for (const rawLine of lines) {
    const line = stripComment(rawLine).replace(/\s+$/, '');
    if (line.trim() === '') continue;
    const indent = line.length - line.trimStart().length;
    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue; // not a "key: value" or "key:" line — skip
    const key = line.slice(indent, colonIdx).trim();
    const rest = line.slice(colonIdx + 1);

    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].obj;

    const value = parseScalar(rest);
    if (value === null) {
      const child = {};
      parent[key] = child;
      stack.push({ indent, obj: child });
    } else {
      parent[key] = value;
    }
  }
  return root;
}

function loadConfig(configPath) {
  const resolved = configPath || findDefaultConfigPath();
  const text = fs.readFileSync(resolved, 'utf8');
  return { config: parseMiniYaml(text), path: resolved };
}

function findDefaultConfigPath() {
  const real = path.join(REPO_ROOT, 'config', 'agents.yaml');
  const example = path.join(REPO_ROOT, 'config', 'agents.example.yaml');
  if (fs.existsSync(real)) return real;
  return example;
}

function resolveAgentBudget(config, agentName) {
  const defaults = config.defaults || {};
  const perAgent = (config.agents && config.agents[agentName]) || {};
  return {
    provider: perAgent.provider || defaults.provider,
    model: perAgent.model || defaults.model,
    input_budget: perAgent.input_budget != null ? perAgent.input_budget : defaults.input_budget,
    output_budget: perAgent.output_budget != null ? perAgent.output_budget : defaults.output_budget,
    production_access: perAgent.production_access === true, // defaults false
  };
}

function listAgentFiles() {
  if (!fs.existsSync(AGENTS_DIR)) return [];
  return fs.readdirSync(AGENTS_DIR).filter((f) => f.endsWith('.md'));
}

function agentExists(name) {
  return fs.existsSync(path.join(AGENTS_DIR, `${name}.md`));
}

module.exports = {
  REPO_ROOT,
  AGENTS_DIR,
  REQUIRED_AGENTS,
  CLASSIFICATION_ONLY_AGENTS,
  NON_IMPLEMENTATION_AGENTS,
  KNOWN_PROVIDERS,
  parseMiniYaml,
  loadConfig,
  findDefaultConfigPath,
  resolveAgentBudget,
  listAgentFiles,
  agentExists,
};
