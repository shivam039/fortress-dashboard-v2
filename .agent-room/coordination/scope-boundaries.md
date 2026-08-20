# Agent Scope Boundaries

## Overview

When multiple agents (or humans and agents) work in the same repository
simultaneously, conflicts are inevitable unless scope boundaries are
established. This protocol defines how to partition work to avoid
stepping on toes.

## The iron law

```
NEVER MODIFY FILES OUTSIDE YOUR ASSIGNED SCOPE WITHOUT EXPLICIT COORDINATION
```

If your task is to update the billing module, and you notice a typo in
the authentication module, do not fix it in the same PR. Scope creep
causes merge conflicts and blocks parallel work.

## Conflict avoidance

### 1. File-level ownership

During a task, treat the files you are actively modifying as "owned" by
your session. Before modifying a shared file (like a main router, a
root configuration file, or `package.json`), check if another session
might be touching it.

### 2. Lock semantics for shared resources

Certain operations inherently block parallel work:

- **Database migrations:** Do not create a new migration if another
  agent is currently building one. Coordinate to ensure sequential
  migration numbering/timestamping.
- **Dependency updates:** Do not bump a major dependency while another
  feature branch is in progress, unless coordinated.

### 3. Detect conflicts early

Before starting a new feature branch, or before modifying a highly
contested file:

1.  Run `git fetch` and `git status`.
2.  Check for open PRs that might touch the same files.
3.  If a conflict is highly likely, communicate the overlap before
    writing code.

## Handling out-of-scope discoveries

When you discover an issue outside your current scope (e.g., a bug in a
utility function, a missing test in another module):

1.  **Do not fix it immediately** (unless it directly blocks your work).
2.  **Document it.** Write it down in a tracking issue, a TODO comment,
    or notify the user.
3.  **Stay focused.** Finish your assigned task first.
