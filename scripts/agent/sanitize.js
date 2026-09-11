#!/usr/bin/env node
'use strict';

/*
 * Sanitization for anything derived from untrusted Issue/task content
 * before it touches a branch name, file path, or shell argument
 * (AGENT1B Phase 27). Issue titles/bodies are treated as data, never as
 * commands — nothing here ever passes a raw string to a shell.
 */

// Branch/task-id slug: lowercase, only [a-z0-9-], collapsed dashes,
// bounded length. Safe as a git branch component and a filename.
function slugify(input, maxLength = 50) {
  const s = String(input == null ? '' : input)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-');
  const truncated = s.slice(0, maxLength).replace(/-+$/, '');
  return truncated || 'task';
}

function sanitizeTaskId(rawId) {
  return slugify(rawId, 40);
}

// agent/<issue-number>-<agent>-<slug>, per Phase 12. issueNumber must be
// a positive integer (never interpolated from raw issue text); agent
// must be one of the known role names.
function buildBranchName({ issueNumber, agent, slug }) {
  const num = Number(issueNumber);
  if (!Number.isInteger(num) || num <= 0) {
    throw new Error(`invalid issue number for branch name: ${issueNumber}`);
  }
  const safeAgent = slugify(agent, 20);
  const safeSlug = slugify(slug, 40);
  return `agent/${num}-${safeAgent}-${safeSlug}`;
}

// A file path from a task's allowed_files/forbidden_files must stay
// inside the repo — reject anything with .. segments or a leading '/'
// that would escape the working tree.
function isSafeRepoPath(p) {
  if (typeof p !== 'string' || p === '') return false;
  if (p.startsWith('/')) return false;
  const parts = p.split('/');
  return !parts.includes('..');
}

module.exports = { slugify, sanitizeTaskId, buildBranchName, isSafeRepoPath };
