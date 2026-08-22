#!/usr/bin/env node
'use strict';

/**
 * Pre-commit hook for guardrails enforcement
 * Prevents commits that violate project guardrails
 *
 * Checks:
 * - Protected paths: blocks commits to paths requiring approval
 * - Forbidden actions: blocks commits containing dangerous patterns (e.g., hard-coded credentials)
 * - Minimum checks before merge
 */

const fs = require('fs');
const path = require('path');
const { execSync, execFileSync } = require('child_process');

const projectRoot = process.cwd();
const guardrailsPath = path.join(projectRoot, '.agent-room', 'guardrails.json');

// Allow override via env variable
const ALLOW_GUARDRAILS_BYPASS = process.env.GUARDRAILS_BYPASS || process.env.SKIP_GUARDRAILS_CHECK;

// Strict Forbidden Email Validation Check
const forbiddenEmails = ['shivam.dixit@publicissapient.com', 'shidixit2@publicisgroupe.net'];
try {
  const authorIdent = execSync('git var GIT_AUTHOR_IDENT', { encoding: 'utf8' });
  const committerIdent = execSync('git var GIT_COMMITTER_IDENT', { encoding: 'utf8' });
  
  const emailRegex = /<([^>]+)>/;
  const authorEmailMatch = authorIdent.match(emailRegex);
  const committerEmailMatch = committerIdent.match(emailRegex);
  
  const emailsToCheck = [];
  if (authorEmailMatch) emailsToCheck.push(authorEmailMatch[1].toLowerCase().trim());
  if (committerEmailMatch) emailsToCheck.push(committerEmailMatch[1].toLowerCase().trim());
  
  for (const email of emailsToCheck) {
    if (forbiddenEmails.includes(email)) {
      console.error('');
      console.error(`❌ Commit Blocked: Commits from email address '${email}' are strictly forbidden in this repository.`);
      console.error('Please configure your git user.email to shivamdixit039@gmail.com:');
      console.error('  git config user.email shivamdixit039@gmail.com');
      console.error('');
      process.exit(1);
    }
  }
} catch (err) {
  // Continue if git commands fail
}

if (!fs.existsSync(guardrailsPath)) {
  // No guardrails file, allow commit
  process.exit(0);
}

let guardrails = {};
try {
  guardrails = JSON.parse(fs.readFileSync(guardrailsPath, 'utf8'));
} catch (err) {
  console.error('');
  console.error(`❌ .agent-room/guardrails.json is broken and could not be parsed: ${err.message}`);
  console.error('Commits are blocked until this file is fixed (failing closed, since a');
  console.error('corrupted config must not silently disable guardrail enforcement).');
  console.error('');
  console.error('To bypass while you fix it, use:');
  console.error('  GUARDRAILS_BYPASS=1 git commit');
  console.error('');
  if (!ALLOW_GUARDRAILS_BYPASS) {
    process.exit(1);
  }
  console.warn('⚠️  Guardrails bypass enabled - proceeding with commit despite broken config');
  process.exit(0);
}

// Get staged files
let stagedFiles = [];
try {
  const output = execSync('git diff --cached --name-only', { encoding: 'utf8' });
  stagedFiles = output.trim().split('\n').filter(Boolean);
} catch (err) {
  // Not a git repo or no staged files
  process.exit(0);
}

const protectedPaths = guardrails.protectedPaths || [];
const forbiddenPatterns = guardrails.forbiddenActions || [];

let violations = [];

// A repository's very first commit has nothing established yet to protect -
// the scaffolding tool creates the protected paths (e.g. CI workflows) in
// the same commit as guardrails.json itself. Protected-path review exists to
// gate *changes* to already-established infrastructure, not its initial
// creation, so it's skipped only for this one commit. Forbidden-pattern
// (secret) scanning below still applies regardless.
if (!isInitialCommit()) {
  for (const file of stagedFiles) {
    for (const protectedPath of protectedPaths) {
      if (isPathProtected(file, protectedPath)) {
        violations.push(`Protected path violation: ${file}`);
      }
    }
  }
}

// Self-protect guardrails.json: the check above only evaluates staged files
// against the protectedPaths in the version of guardrails.json being
// committed. If a single commit both edits guardrails.json and removes its
// own path from protectedPaths in that same edit, the newly-weakened rules
// approve themselves. Compare against HEAD's protectedPaths (the rules that
// applied before this commit) so that scenario is still caught.
const guardrailsRelPath = path.relative(projectRoot, guardrailsPath).replace(/\\/g, '/');
if (stagedFiles.includes(guardrailsRelPath)) {
  const headGuardrails = getHeadGuardrails();
  if (headGuardrails) {
    const headProtectedPaths = headGuardrails.protectedPaths || [];
    const wasProtected = headProtectedPaths.some((p) => isPathProtected(guardrailsRelPath, p));
    const isStillProtected = protectedPaths.some((p) => isPathProtected(guardrailsRelPath, p));
    if (wasProtected && !isStillProtected) {
      violations.push(
        `Protected path violation: ${guardrailsRelPath} (removed from protectedPaths in the same commit that edits it)`
      );
    }
  }
}

// The guardrails config/docs themselves legitimately contain the forbidden-
// pattern strings as data (that's how they're defined) - scanning their own
// content would always self-trigger, so they're exempt from this check.
const guardrailsSelfPaths = new Set(
  [guardrailsPath, path.join(projectRoot, '.agent-room', 'guardrails.md')].map((p) =>
    path.relative(projectRoot, p).replace(/\\/g, '/')
  )
);

// Check for forbidden patterns in staged content
for (const file of stagedFiles) {
  if (!fs.existsSync(file)) continue;
  if (guardrailsSelfPaths.has(file.replace(/\\/g, '/'))) continue;

  // Skip binary files and very large files
  if (isBinaryFile(file) || fs.statSync(file).size > 1000000) {
    continue;
  }

  try {
    // Get staged content (not working tree)
    const stagedContent = execFileSync('git', ['show', `:${file}`], { encoding: 'utf8' });

    for (const entry of forbiddenPatterns) {
      const { pattern, type, label } = normalizeForbiddenEntry(entry);
      if (!pattern) continue;

      if (type === 'regex') {
        try {
          const regex = new RegExp(pattern, 'i');
          if (regex.test(stagedContent)) {
            violations.push(`Forbidden pattern found in ${file}: ${label}`);
          }
        } catch (regexErr) {
          // Invalid regex, skip
        }
      } else {
        // Literal string
        if (stagedContent.includes(pattern)) {
          violations.push(`Forbidden pattern found in ${file}: ${label}`);
        }
      }
    }
  } catch (err) {
    // File might not exist in index yet
  }
}

if (violations.length > 0) {
  console.error('');
  console.error('❌ Guardrails Check Failed: Commit violates project guardrails');
  console.error('');
  for (const violation of violations) {
    console.error(`  - ${violation}`);
  }
  console.error('');
  console.error('To bypass guardrails (requires approval), use:');
  console.error('  GUARDRAILS_BYPASS=1 git commit');
  console.error('');

  if (!ALLOW_GUARDRAILS_BYPASS) {
    process.exit(1);
  }

  console.warn('⚠️  Guardrails bypass enabled - proceeding with commit');
}

process.exit(0);

// forbiddenActions entries are normally { pattern, type: "regex"|"literal",
// description } objects. Flat strings from the pre-schema config format are
// still accepted (inferring regex-vs-literal the old, best-effort way) so
// existing projects aren't silently left unprotected until they migrate.
function normalizeForbiddenEntry(entry) {
  if (typeof entry === 'string') {
    const looksLikeRegex = entry.match(/^\/.*\/[gimuy]*$/) || entry.startsWith('(?:') || entry.includes('(?:');
    return { pattern: entry, type: looksLikeRegex ? 'regex' : 'literal', label: entry };
  }
  if (entry && typeof entry === 'object' && typeof entry.pattern === 'string') {
    return {
      pattern: entry.pattern,
      type: entry.type === 'regex' ? 'regex' : 'literal',
      label: entry.description || entry.pattern
    };
  }
  return { pattern: null, type: null, label: null };
}

function isInitialCommit() {
  try {
    execFileSync('git', ['rev-parse', '--verify', 'HEAD'], { stdio: 'ignore' });
    return false;
  } catch (err) {
    return true;
  }
}

function isPathProtected(filePath, protectedPattern) {
  // Normalize paths for comparison
  const normalized = filePath.replace(/\\/g, '/');
  const pattern = protectedPattern.replace(/\\/g, '/');

  // Handle glob patterns. Translates a small, deliberate glob subset:
  //   **/  -> zero or more path segments, INCLUDING none at all, so a
  //           pattern like "**/*secret*" still matches a root-level file
  //           (e.g. "my_secret.py"), not just one nested in a directory.
  //           The naive "split on every '*' and join with .*" approach this
  //           replaced could not express "zero segments" and silently never
  //           matched protected root-level files.
  //   **   -> match across path separators anywhere else in the pattern
  //   *    -> match within a single path segment only (no "/")
  if (pattern.includes('*')) {
    let regexPattern = '';
    let i = 0;
    while (i < pattern.length) {
      if (pattern.startsWith('**/', i)) {
        regexPattern += '(?:.*/)?';
        i += 3;
      } else if (pattern.startsWith('**', i)) {
        regexPattern += '.*';
        i += 2;
      } else if (pattern[i] === '*') {
        regexPattern += '[^/]*';
        i += 1;
      } else {
        regexPattern += pattern[i].replace(/[.+?^${}()|[\]\\]/g, '\\$&');
        i += 1;
      }
    }
    return new RegExp(`^${regexPattern}$`).test(normalized);
  }

  // Direct match or prefix match
  return normalized === pattern || normalized.startsWith(pattern + '/');
}

function getHeadGuardrails() {
  let headContent;
  try {
    headContent = execFileSync('git', ['show', 'HEAD:.agent-room/guardrails.json'], { encoding: 'utf8' });
  } catch (err) {
    // No HEAD yet (genesis commit) or guardrails.json didn't exist at HEAD -
    // nothing to compare against.
    return null;
  }
  try {
    return JSON.parse(headContent);
  } catch (err) {
    // HEAD's guardrails.json doesn't parse cleanly - treat as no prior
    // protection to compare against rather than crashing the hook.
    return null;
  }
}

function isBinaryFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const binaryExts = ['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.tar', '.exe', '.dll', '.so', '.bin'];
  return binaryExts.includes(ext);
}
