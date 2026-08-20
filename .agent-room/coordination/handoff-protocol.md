# Agent Handoff Protocol

## Overview

Modern agent workflows often involve multiple sessions, orchestrators,
and sub-agents. A handoff protocol ensures that context isn't lost when
one agent finishes its turn and another begins. The receiving agent
must not have to guess what was already done or what assumptions were
made.

## The iron law

```
NEVER END A SESSION WITH "WIP" — ALWAYS SERIALIZE STATE
```

If an agent session is ending before the full feature is complete, it
must serialize its state so the next session can pick up exactly where
it left off.

## The Handoff Note

When handing off work, write a handoff note (either in the chat, in a
PR description, or in the session log). It must include:

1.  **Completed:** What is definitively finished and verified.
2.  **In Progress:** What is partially built but not yet working.
3.  **Blocked On:** What is preventing completion (missing credentials,
    unclear requirements, failing dependency).
4.  **Assumptions:** Any decisions made during the session that the next
    agent needs to know.

### Example Handoff Note

```markdown
**Completed:**
- User model and database migration.
- `POST /register` route (handler skeleton exists, validation not started).

**In Progress:**
- Email verification service.

**Blocked On:**
- Need SMTP credentials in the `.env` file to test the email service.

**Assumptions:**
- Using `bcrypt` for passwords per decision in `.agent-room/decisions.md`.
```

## Receiving Handoffs

When you are the receiving agent (starting a new session):

1.  **Re-verify, don't trust:** Do not blindly trust the previous agent's
    "Completed" list. Run the tests. Check the diff. Verify the state
    yourself.
2.  **Read decisions:** Check `.agent-room/decisions.md` to understand
    *why* the previous agent made the choices it did.
3.  **Address blockers first:** If the handoff note lists blockers,
    resolve them (or escalate them to the user) before writing new code.
