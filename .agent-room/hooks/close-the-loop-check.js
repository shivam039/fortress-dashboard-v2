#!/usr/bin/env node
'use strict';

/*
 * Claude Code Stop hook: mechanically enforces .agent-room/skills/closing-the-loop.md.
 *
 * Runs at the end of every turn. If tracked, uncommitted changes touch files
 * outside the agent-room scaffold but neither .agent-room/anti-patterns.md
 * nor .agent-room/decisions.md was also touched, it blocks the turn from
 * ending (exit code 2) and explains why via stderr, which Claude Code feeds
 * back to the model as the reason it can't stop yet.
 *
 * Exit hatch: touch either log file - a real entry, or a one-line waiver
 * comment - and the check passes. See closing-the-loop.md for the format.
 *
 * Limitations (by design, to stay simple):
 * - Only looks at `git status --porcelain` since the last commit, not since
 *   the start of this turn. Pre-existing unrelated dirty changes in the work
 *   tree will also trigger this - commit or stash them first if that's noisy.
 * - Treats any file rename touching scaffold paths as a non-scaffold change
 *   (rare, harmless false positive).
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

function sh(cmd) {
  try {
    return execSync(cmd, { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'ignore'] }).toString();
  } catch (err) {
    return '';
  }
}

function isGitRepo() {
  return sh('git rev-parse --is-inside-work-tree 2>/dev/null').trim() === 'true';
}

const SCAFFOLD_PREFIXES = [
  '.agent-room/',
  'docs/plans/',
  '.claude/skills/',
  '.claude/settings.json',
  '.cursor/rules/',
];
const SCAFFOLD_FILES = ['AGENTS.md', 'CLAUDE.md'];

function isScaffoldPath(p) {
  if (SCAFFOLD_FILES.includes(p)) return true;
  // Bidirectional: p itself under a scaffold prefix (normal case), OR p is an
  // ancestor directory of a scaffold prefix (git collapses an untracked dir
  // with no other tracked siblings into a single porcelain line, e.g. a
  // brand-new ".claude/" with nothing else in it yet shows as "?? .claude/").
  return SCAFFOLD_PREFIXES.some((prefix) => p.startsWith(prefix) || prefix.startsWith(p));
}

function isLogPath(p) {
  return p === '.agent-room/anti-patterns.md' || p === '.agent-room/decisions.md';
}

function main() {
  const cwd = process.cwd();

  if (!fs.existsSync(path.join(cwd, '.agent-room'))) {
    process.exit(0); // not a scaffolded project
  }
  if (!isGitRepo()) {
    process.exit(0); // no git history to check against
  }

  const lines = sh('git status --porcelain').split('\n').filter(Boolean);
  const changedPaths = lines.map((line) => line.slice(3).trim());

  const sourceChanges = changedPaths.filter((p) => !isScaffoldPath(p));
  const logTouched = changedPaths.some(isLogPath);

  if (sourceChanges.length === 0 || logTouched) {
    process.exit(0);
  }

  const sample = sourceChanges.slice(0, 5).join(', ') + (sourceChanges.length > 5 ? ', ...' : '');
  process.stderr.write(
    'Closing-the-loop check failed: this turn changed ' + sourceChanges.length +
      ' file(s) outside the agent-room scaffold (' + sample + '), but neither ' +
      '.agent-room/anti-patterns.md nor .agent-room/decisions.md was touched.\n\n' +
      'Follow .agent-room/skills/closing-the-loop.md before finishing this turn:\n' +
      '- If this fixed a bug or found a root cause, append an entry to anti-patterns.md.\n' +
      '- If this made a non-obvious design/architecture call, append an entry to decisions.md.\n' +
      '- If genuinely neither applies, add a one-line waiver to decisions.md instead:\n' +
      '  <!-- no-log: routine change, no decision or anti-pattern worth recording -->\n'
  );
  process.exit(2);
}

main();
