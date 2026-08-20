---
name: test-driven-development
description: "Use when implementing any feature or bugfix, before writing implementation code."
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** if you didn't watch the test fail, you don't know if it
tests the right thing.

## When to use

**Always:** new features, bug fixes, refactoring, behavior changes.

**Exceptions (ask the maintainer first):** throwaway prototypes, generated
code, configuration files.

Thinking "skip TDD just this once"? That's rationalization — stop.

## The iron law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Wrote code before the test? Delete it. Don't keep it "as reference," don't
adapt it while writing the test, don't look at it. Implement fresh from
tests.

## Red-Green-Refactor

```
RED: write one minimal failing test
  -> verify it fails for the right reason (not a typo, not existing behavior)
GREEN: write the minimal code to pass
  -> verify it passes, and nothing else broke
REFACTOR: clean up, keep tests green, no new behavior
  -> next failing test
```

### RED — write a failing test

One behavior, clear name, real code (mock only if unavoidable).

Good: `test('retries failed operations 3 times', ...)` — tests real behavior.
Bad: `test('retry works', ...)` with a mock asserting call count — tests the
mock, not the code.

### Verify RED — mandatory, never skip

Run the test command. Confirm: it fails (not errors), the failure message
is the expected one, and it fails because the feature is missing — not
because of a typo. If it passes, you're testing existing behavior — fix the
test.

### GREEN — minimal code

Write just enough to pass. Don't add options, config, or "while I'm here"
improvements the test doesn't require (YAGNI).

### Verify GREEN — mandatory

Run the test command again. Confirm it passes and nothing else broke, with
clean output (no stray errors/warnings).

### REFACTOR

Remove duplication, improve names, extract helpers — only after green, and
only while staying green.

## Why order matters

- **Tests written after code pass immediately** — passing immediately proves
  nothing about whether the test would have caught a real bug.
- **Manual testing isn't a substitute** — no record, can't re-run, easy to
  forget edge cases under pressure.
- **"I already spent hours on this, deleting is wasteful"** is sunk-cost
  reasoning — the time is gone either way; the choice is rewrite-with-tests
  (high confidence) vs. keep-untested (technical debt from day one).

## Verification checklist before calling work done

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for the expected reason
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass, output is clean
- [ ] Edge cases and error paths are covered

Can't check every box? TDD was skipped somewhere — go back.

## Debugging integration

Found a bug? Write a failing test that reproduces it first, then follow the
same red-green-refactor cycle. Never fix a bug without a regression test.
See `.agent-room/skills/systematic-debugging.md` for root-causing it first.
