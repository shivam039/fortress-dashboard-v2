#!/usr/bin/env node
'use strict';

// FORTRESS-NEXT Epic 19: Docs Agent's first invoked check. ADVISORY ONLY -
// this never blocks a merge and has no gate/veto authority (unlike
// reviewer-evidence.js's auto-gates path). It flags, a human or Docs Agent
// decides.
//
// Deliberately a reference-match heuristic, not full LLM-driven semantic
// analysis: for each doc under docs/research/ or docs/product/ that was NOT
// changed in this PR, look for a backtick-quoted path (or `dir/*` glob) that
// names a file/module the PR DID change. That is "this doc makes a claim
// about a code path this PR touches, and nobody told the doc" - an honest
// first version, not a claim of full semantic understanding.

const fs = require('fs');
const path = require('path');
const { classifyFile } = require('./reviewer-evidence');

// FORTRESS "LUNA MISSES CLOSEOUT" Epic 7: the reference-match check above
// answers "does an EXISTING doc claim something about a file this PR
// changed?" - useful, but it says nothing when no doc happens to reference
// the changed area yet. Separately, `docs_required` in the real pipeline
// (github-pipeline.js's classifyIssue()) was purely `selectedAgent ===
// 'docs'` - a backend/infra/agent-framework-classified change to an API
// route, security config, or workflow file never set docs_required, no
// matter what it touched. Reusing reviewer-evidence.js's path-category
// classifier (already proven, already tested) closes that: any changed
// file landing in one of these categories is the kind of change this
// closeout's own examples call out as normally requiring docs (new/changed
// API, security requirement, agent behavior, provider behavior,
// deployment/operations change). backend_logic/frontend_logic/
// db_persistence/tests/docs/other are deliberately excluded - an internal
// refactor, a test-only change, or a docs-only change does not require
// more docs just because a file was touched.
const DOCS_LIKELY_CATEGORIES = new Set(['api_contract', 'security_auth', 'infra_workflow', 'agent_framework']);

function docsLikelyRequired(changedFiles) {
  const hits = [];
  for (const file of changedFiles) {
    const category = classifyFile(file);
    if (DOCS_LIKELY_CATEGORIES.has(category)) hits.push({ file, category });
  }
  return { required: hits.length > 0, hits };
}

const DOCS_DIRS = ['docs/research', 'docs/product'];
// Matches a backtick-quoted path like `engine/research/auto_scan.py`,
// `engine/utils/db.py::save_scan_results`, or a directory glob like
// `engine/research/*`.
const PATH_REF_RE = /`([A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|jsx|md|yml|yaml)|[A-Za-z0-9_./-]+\/\*)(::[A-Za-z0-9_]+)?`/g;

function listDocFiles(repoRoot) {
  const out = [];
  for (const dir of DOCS_DIRS) {
    const abs = path.join(repoRoot, dir);
    if (!fs.existsSync(abs)) continue;
    for (const name of fs.readdirSync(abs)) {
      if (name.endsWith('.md')) out.push(path.posix.join(dir, name));
    }
  }
  return out;
}

function extractReferences(text) {
  const refs = [];
  let m;
  PATH_REF_RE.lastIndex = 0;
  while ((m = PATH_REF_RE.exec(text)) !== null) refs.push(m[1]);
  return refs;
}

function referenceMatchesChangedFile(ref, changedFile) {
  if (ref.endsWith('/*')) return changedFile.startsWith(ref.slice(0, -1));
  return ref === changedFile;
}

// changedFiles: string[] of PR-relative changed file paths.
// repoRoot: absolute path to check out docs from (so this can run against a
// historical checkout, not only the working tree).
function checkDocsImpact({ changedFiles, repoRoot }) {
  const changedSet = new Set(changedFiles);
  const flags = [];
  for (const docFile of listDocFiles(repoRoot)) {
    if (changedSet.has(docFile)) continue; // doc itself was updated - fine
    const text = fs.readFileSync(path.join(repoRoot, docFile), 'utf8');
    for (const ref of extractReferences(text)) {
      for (const changedFile of changedFiles) {
        if (referenceMatchesChangedFile(ref, changedFile)) {
          flags.push({ doc: docFile, referenced_path: ref, changed_file: changedFile });
        }
      }
    }
  }
  const likely = docsLikelyRequired(changedFiles);
  return {
    role: 'docs',
    advisory: true, // this report's flags/reference-check never block a merge - see file header
    docs_impacted: flags.length > 0,
    flags,
    // Unlike `docs_impacted` above, `docs_required` DOES feed the real
    // pipeline: agent.js's auto-gates passes it as reviewerGate()'s
    // docsImpact argument, which can flip docs_required to true even for a
    // non-docs-classified run. This is the one part of this report that is
    // NOT merely advisory.
    docs_required: likely.required,
    docs_required_reasons: likely.hits,
    completed_at: new Date().toISOString(),
  };
}

module.exports = { checkDocsImpact, extractReferences, listDocFiles, docsLikelyRequired, DOCS_LIKELY_CATEGORIES };

if (require.main === module) {
  // Usage: node docs-evidence.js <changed-files.json> [repoRoot]
  // changed-files.json: a JSON array of PR-relative changed file paths.
  const [changedFilesPath, repoRoot = process.cwd()] = process.argv.slice(2);
  if (!changedFilesPath) {
    console.error('usage: docs-evidence.js <changed-files.json> [repoRoot]');
    process.exit(2);
  }
  const changedFiles = JSON.parse(fs.readFileSync(changedFilesPath, 'utf8'));
  const result = checkDocsImpact({ changedFiles, repoRoot });
  console.log(JSON.stringify(result, null, 2));
}
