#!/usr/bin/env node
'use strict';

/*
 * Scope enforcement (AGENT1B Phase 13). Compares the actual changed files
 * (git diff --name-only) against a task's allowed_files/forbidden_files.
 * A minimal glob subset is supported — '**' (any depth), '*' (one path
 * segment) — sufficient for patterns like 'engine/**' or
 * 'tests/backend/*.py'. This is deliberately not a full glob
 * implementation; extend only if a real pattern needs it.
 */

const { execSync } = require('child_process');
const { isSafeRepoPath } = require('./sanitize');

function globToRegExp(pattern) {
  let re = '';
  for (let i = 0; i < pattern.length; i++) {
    if (pattern[i] === '*' && pattern[i + 1] === '*') {
      re += '.*';
      i++;
    } else if (pattern[i] === '*') {
      re += '[^/]*';
    } else {
      re += pattern[i].replace(/[.+?^${}()|[\]\\]/g, '\\$&');
    }
  }
  return new RegExp(`^${re}$`);
}

function matchesAny(filePath, patterns) {
  return patterns.some((p) => globToRegExp(p).test(filePath));
}

function getChangedFiles(baseRef = 'HEAD') {
  const out = execSync(`git diff --name-only ${baseRef}`, { encoding: 'utf8' });
  return out.split('\n').map((l) => l.trim()).filter(Boolean);
}

// Returns { ok, violations, unsafePaths }. `allowedFiles` empty/undefined
// means "no restriction beyond forbiddenFiles" — an empty allow-list is
// NOT treated as "nothing allowed", since most tasks only need to name
// forbidden files, not enumerate every permitted one.
function checkScope(changedFiles, { allowedFiles = [], forbiddenFiles = [] }) {
  const unsafePaths = changedFiles.filter((f) => !isSafeRepoPath(f));
  const violations = [];

  for (const file of changedFiles) {
    if (forbiddenFiles.length && matchesAny(file, forbiddenFiles)) {
      violations.push({ file, reason: 'forbidden_files match' });
      continue;
    }
    if (allowedFiles.length && !matchesAny(file, allowedFiles)) {
      violations.push({ file, reason: 'not in allowed_files' });
    }
  }

  return {
    ok: violations.length === 0 && unsafePaths.length === 0,
    violations,
    unsafePaths,
  };
}

function main() {
  const [allowedArg, forbiddenArg, baseRefArg] = process.argv.slice(2);
  const allowedFiles = allowedArg ? JSON.parse(allowedArg) : [];
  const forbiddenFiles = forbiddenArg ? JSON.parse(forbiddenArg) : [];
  const changed = getChangedFiles(baseRefArg || 'HEAD');
  const result = checkScope(changed, { allowedFiles, forbiddenFiles });

  console.log(JSON.stringify({ changed, ...result }, null, 2));
  if (!result.ok) {
    console.error('BLOCKED_SCOPE');
    process.exit(1);
  }
  console.log('SCOPE OK');
  process.exit(0);
}

if (require.main === module) main();
module.exports = { globToRegExp, matchesAny, getChangedFiles, checkScope };
