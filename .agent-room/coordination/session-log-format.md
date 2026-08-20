# Session Log Format

## Overview

Session logs provide observability into what agents are doing, how long
they take, and what decisions they make. This is crucial for debugging
agent failures and for team visibility.

## Storage location

Logs should be saved in `.agent-room/sessions/` using the following
naming convention:

`YYYY-MM-DD-HH-MM-<topic>.md`

Example: `2025-03-15-14-30-fix-login-timeout.md`

## Log format

Every session log must follow this structure:

```markdown
# Session Log: [Short title]

**Date:** YYYY-MM-DD HH:MM
**Agent:** [Name/Version of the agent, e.g., Claude 3.5 Sonnet]
**Classification:** [Bug | Enhancement | Feature | Product]

## Goal
[One sentence describing what the session aimed to achieve]

## Files touched
- Read: [list of key files read for context]
- Created: [list of new files]
- Modified: [list of modified files]

## Actions taken
1. [Step 1: e.g., Ran grep to find login timeout config]
2. [Step 2: e.g., Wrote failing test in auth.test.js]
3. [Step 3: e.g., Updated timeout value and passed test]

## Tests run
- Command: `npm test`
- Result: [Pass | Fail | 2 errors]

## Decisions made
- [Any non-obvious architecture or design calls made during the session.
  These should also be appended to .agent-room/decisions.md]

## Outcome
[Completed | Blocked | Handed Off]

**Handoff note (if applicable):**
[Insert the handoff note here, following handoff-protocol.md]
```

## When to write a session log

- **Opt-in:** Depending on the project's `.agent-room.json` config,
  session logging may be required or optional.
- **Default:** Write a log at the end of any session that lasted more
  than 15 minutes or resulted in a non-trivial code change.
