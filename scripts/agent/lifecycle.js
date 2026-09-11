#!/usr/bin/env node
'use strict';

/*
 * Task execution state machine (AGENT1B, Phase 3). No database — state
 * lives in the GitHub Issue (labels/comments) and/or a run record under
 * .agent-room/sessions/ (see run-record.js). This module only validates
 * transitions; it does not persist anything itself.
 */

const STATES = [
  'CREATED', 'CLASSIFIED', 'APPROVED', 'RUNNING', 'IMPLEMENTED',
  'TESTING', 'REVIEWING', 'DOCS_PENDING', 'READY_FOR_PR', 'PR_OPEN',
  'AWAITING_HUMAN', 'MERGED', 'FAILED', 'BLOCKED', 'CANCELLED',
];

// Terminal states nothing may transition out of.
const TERMINAL = new Set(['MERGED', 'CANCELLED']);

// Every state may transition to FAILED, BLOCKED, or CANCELLED (bounded
// retry / human intervention / abandonment can happen at any point), so
// those three are added to every entry below rather than repeated.
const ALWAYS_REACHABLE = ['FAILED', 'BLOCKED', 'CANCELLED'];

const TRANSITIONS = {
  CREATED: ['CLASSIFIED'],
  CLASSIFIED: ['APPROVED'], // approval gate — see Phase 25
  APPROVED: ['RUNNING'],
  RUNNING: ['IMPLEMENTED'],
  IMPLEMENTED: ['TESTING'],
  TESTING: ['REVIEWING'], // test failure -> FAILED (via ALWAYS_REACHABLE) up to MAX_IMPLEMENTATION_ATTEMPTS, then BLOCKED
  REVIEWING: ['DOCS_PENDING', 'READY_FOR_PR'], // NOT_MERGEABLE -> RUNNING (one correction cycle) or BLOCKED
  DOCS_PENDING: ['READY_FOR_PR'],
  READY_FOR_PR: ['PR_OPEN'],
  PR_OPEN: ['AWAITING_HUMAN'],
  AWAITING_HUMAN: ['MERGED'], // human-only transition — never automated
  FAILED: ['RUNNING'], // bounded retry re-enters RUNNING; see MAX_IMPLEMENTATION_ATTEMPTS
  BLOCKED: [], // requires human intervention to move at all
  MERGED: [],
  CANCELLED: [],
};

// REVIEWING -> RUNNING is the one allowed correction cycle (Phase 19).
TRANSITIONS.REVIEWING.push('RUNNING');

function isValidState(state) {
  return STATES.includes(state);
}

function isTerminal(state) {
  return TERMINAL.has(state);
}

function allowedTransitions(fromState) {
  if (!isValidState(fromState)) return [];
  if (isTerminal(fromState)) return [];
  const explicit = TRANSITIONS[fromState] || [];
  const reachable = ALWAYS_REACHABLE.filter((s) => s !== fromState); // no self-transition
  return [...new Set([...explicit, ...reachable])];
}

function canTransition(fromState, toState) {
  if (!isValidState(fromState) || !isValidState(toState)) return false;
  return allowedTransitions(fromState).includes(toState);
}

module.exports = { STATES, TERMINAL, isValidState, isTerminal, allowedTransitions, canTransition };
