---
name: systematic-debugging
description: "Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes."
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask the
underlying issue.

**Core principle:** always find the root cause before attempting a fix.
Symptom fixes are failure.

## The iron law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

**Especially when:** under time pressure, "just one quick fix" seems
obvious, you've already tried multiple fixes, or you don't fully understand
the issue yet. None of these are reasons to skip investigation — they're
exactly when guessing gets expensive.

## The four phases

### Phase 1: Root cause investigation

1. **Read error messages and stack traces completely** — line numbers,
   file paths, error codes, not just the first line.
2. **Reproduce consistently** — exact steps, every time. Not reproducible?
   Gather more data, don't guess.
3. **Check recent changes** — git diff, recent commits, new dependencies,
   config or environment differences.
4. **In multi-component systems, gather evidence at each boundary** before
   proposing fixes: log what enters/exits each component, verify
   config/env propagation, check state at each layer. Run once, see *where*
   it breaks, then investigate that specific component.
5. **Trace data backward** when the error is deep in a call stack: where
   did the bad value originate? What called this with that bad value? Keep
   tracing up to the source — fix at the source, not at the symptom.

### Phase 2: Pattern analysis

- Find working examples of similar code in the same codebase.
- If implementing a known pattern, read the reference completely — not a
  skim.
- List every difference between the working and broken case, however small.
- Understand the dependencies, config, and assumptions involved.

### Phase 3: Hypothesis and testing

- State one hypothesis clearly: "I think X is the root cause because Y."
- Test it with the smallest possible change — one variable at a time.
- Worked? Move to Phase 4. Didn't work? Form a *new* hypothesis — don't
  stack another fix on top.
- Genuinely don't know? Say so explicitly rather than guessing.

### Phase 4: Implementation

1. Create a failing test that reproduces the bug (see
   `.agent-room/skills/test-driven-development.md`).
2. Implement a single fix addressing the root cause — one change, no
   bundled refactoring.
3. Verify: test passes, no other tests broke, the original issue is
   actually resolved.
4. **If the fix doesn't work, stop and count attempts.** Fewer than 3:
   return to Phase 1 with the new information. **3 or more failed fixes
   means the architecture is probably wrong, not the fix** — stop and
   question the pattern itself rather than attempting fix #4.

## Red flags — stop and return to Phase 1

"Quick fix for now, investigate later" · "just try changing X" · "skip the
test, I'll verify manually" · "it's probably X" · proposing a fix before
tracing data flow · "one more attempt" after 2+ failures · each fix
revealing a new problem somewhere else.

## When investigation truly finds no root cause

Document what was investigated, implement appropriate handling (retry,
timeout, clear error message), add logging for next time. This is rare —
most "no root cause" conclusions are incomplete investigation.
