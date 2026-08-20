---
name: closing-the-loop
description: "Use before ending any turn that fixed a bug, changed behavior, or made a design call - check whether it belongs in anti-patterns.md or decisions.md."
---

# Closing the Loop

## Overview

Knowledge that isn't written down doesn't survive the session. A bug's root
cause, a rejected approach, a "this looked right but wasn't" — if it's not in
`.agent-room/anti-patterns.md` or `.agent-room/decisions.md`, the next
session (or the next you) re-derives it from scratch, or repeats it.

## The iron law

```
NO TURN ENDS WITHOUT A LOG CHECK
```

This doesn't mean every turn needs a log entry — most don't. It means every
turn that changed behavior or made a non-obvious call must be **checked**
against the two questions below before you consider the work done.

## The check

Before finishing any turn that touched code outside `.agent-room/` or
`docs/plans/`, ask:

1. **Did I find a root cause for a bug, or learn that an approach doesn't
   work?** → append an entry to `.agent-room/anti-patterns.md`.
2. **Did I make an architecture/design call that wasn't forced — i.e.
   someone could reasonably ask "why this way?"** → append an entry to
   `.agent-room/decisions.md`.

If neither applies — a routine, obvious change — say so explicitly rather
than silently skipping the check. In a project with the Claude Code hook
installed (see `CLAUDE.md`), state it as a one-line waiver in
`.agent-room/decisions.md`:

```
<!-- no-log: routine change, no decision or anti-pattern worth recording -->
```

This keeps the check enforceable: "I thought about it and there was nothing
to log" is a valid outcome, but it has to be visible, not assumed.

## What belongs in each log

**`anti-patterns.md`** — things that went wrong: a bug's actual root cause
(not the symptom), an approach that seemed reasonable but wasn't, a fix that
got reverted. Short format: what happened, root cause, the rule that would
have prevented it.

**`decisions.md`** — choices that could have gone another way: picking one
library/pattern over another, a scope cut, a trade-off accepted under a
constraint. Short format: the decision, why, what was rejected.

**Skip both for:** typo fixes, formatting, dependency bumps with no
surprises, anything where the "why" is fully obvious from the diff itself.

## Why this is its own skill, not just advice

`verification-before-completion.md` makes sure you don't claim done without
evidence. This skill makes sure "done" also means "and I didn't let
something worth remembering evaporate." They're both completion gates;
they check different things.
