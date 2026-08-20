---
name: writing-plans
description: "Use when you have an approved design or requirements for a multi-step task, before touching code."
---

# Writing Plans

## Overview

Turn an approved design into an implementation plan, written as if the
executor (a fresh agent session, a teammate, or future-you) has zero context
on this codebase. Document exactly which files to touch, the code, the
tests, and how to verify each step. DRY. YAGNI. TDD. Frequent commits.

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md`

## Bite-sized task granularity

Each step is one action, roughly 2-5 minutes:
- "Write the failing test" — step
- "Run it, confirm it fails for the right reason" — step
- "Write the minimal code to pass" — step
- "Run it, confirm it passes" — step
- "Commit" — step

## Plan document header

Every plan starts with:

```markdown
# [Feature Name] Implementation Plan

**Goal:** [one sentence describing what this builds]
**Architecture:** [2-3 sentences about the approach]
**Tech stack:** [key technologies/libraries]

---
```

## Task structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.ext`
- Modify: `exact/path/to/existing.ext:123-145`
- Test: `tests/exact/path/to/test.ext`

**Step 1: Write the failing test**
[complete test code, not "add validation"]

**Step 2: Run test to verify it fails**
Run: `<exact command>`
Expected: FAIL with "<exact message>"

**Step 3: Write minimal implementation**
[complete code]

**Step 4: Run test to verify it passes**
Run: `<exact command>`
Expected: PASS

**Step 5: Commit**
```bash
git add <files>
git commit -m "<message>"
```
````

## Remember

- Exact file paths always.
- Complete code in the plan, never "add validation" as a placeholder.
- Exact commands with expected output, not "run the tests."
- DRY, YAGNI, TDD, frequent commits.

## Execution

Once the plan is saved, either:
1. **Work through it task-by-task in this session**, verifying each step
   before moving to the next (see `.agent-room/skills/test-driven-development.md`
   and `.agent-room/skills/verification-before-completion.md`), or
2. **Hand the plan file to a fresh agent session** to execute, if you want a
   clean context with no accumulated assumptions from the design discussion.

Either way: one task at a time, verify before moving on, commit frequently.
