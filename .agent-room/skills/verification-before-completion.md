---
name: verification-before-completion
description: "Use before claiming work is complete, fixed, or passing - before committing or opening a PR. Evidence before assertions, always."
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not
efficiency.

**Core principle:** evidence before claims, always.

## The iron law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this turn, you cannot claim
it passes.

## The gate

```
Before claiming any status or expressing satisfaction:
1. IDENTIFY what command actually proves the claim
2. RUN the full command, fresh
3. READ the full output — exit code, failure count, warnings
4. Does the output confirm the claim?
     no  -> state the actual status, with evidence
     yes -> state the claim, with evidence
```

## Common failures

| Claim | Requires | Not sufficient |
| --- | --- | --- |
| Tests pass | test command output: 0 failures | "should pass", a previous run |
| Lint clean | linter output: 0 errors | partial check |
| Build succeeds | build command: exit 0 | linter passing |
| Bug fixed | test of the original symptom passes | code changed, assumed fixed |
| Regression test works | red-green cycle actually verified | passes once |
| Agent/subtask completed | diff shows the actual changes | "agent reported success" |

## Red flags — stop

Using "should", "probably", "seems to" · expressing satisfaction before
verifying ("done!", "perfect!") · about to commit/push/open a PR without
running anything · trusting a sub-agent's self-report instead of checking
the diff · "just this once."

## The bottom line

Run the command. Read the output. Then make the claim. No shortcuts.
