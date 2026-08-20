# LLM-Native Development Principles

A working reference for getting predictable outcomes out of an LLM coding
agent. The point is not to sound clever — it's to make outcomes predictable.

## Quick reference

| # | Principle | Default move |
| --- | --- | --- |
| 1 | LLMs are retrieval systems | Use precise names, types, constraints, and input context |
| 2 | Iteration is required | Explore, constrain, refine, verify — don't one-shot |
| 3 | Context windows forget | Write summary checkpoints to files, not just chat |
| 4 | Explanation pressure finds weak spots | Ask it to explain, challenge, and restate the work |
| 5 | Negative knowledge is leverage | Keep an anti-patterns file; one avoided bug beats one good example |
| 6 | Tests are the spec | Write the test before the implementation |
| 7 | Specific names retrieve better | Prefer clear, specific, stable names over short or sprawling ones |
| 8 | Match process to work type | Use the lightest process that still protects quality |
| 9 | PRD and architecture co-evolve | Let architecture discoveries simplify the requirements |
| 10 | Serialize state | A checkpoint should let someone else resume without guesswork |
| 11 | Delegate with rules, not vibes | Can I define correctness right now? Yes: proceed. Missing facts: research. Unclear requirement: escalate. |
| 12 | Close the loop | Record failures and wins; feed both back into future prompts |

## How they connect

```
[Foundation] -> [Quality] -> [Process]
      ^                           |
      |                           |
      +-------- learning ---------+

Foundation = model behavior   (1-5)
Quality    = output quality   (6-7)
Process    = safe delivery    (8-11)
Learning   = feeds back in    (12)
```

---

## Principle 1: LLMs Are Retrieval Systems

**Rule:** Output quality depends on input context quality more than on
"prompting skill." Fix the input, not the model.

**Violation:** You ask an agent to "add caching." It invents a custom
in-memory cache using a plain object, ignoring the Redis client already
configured in `lib/cache.ts`, because nothing in the prompt mentioned
existing infrastructure. The resulting PR duplicates functionality and
introduces a cache invalidation bug.

**Compliance:** You tell the agent: "Add response caching to the
`/api/users` endpoint. The project uses Redis via `lib/cache.ts` — read
that file first. Cache keys should follow the `resource:id:action` pattern
established in `lib/cache.ts:L14-L22`. TTL: 5 minutes." The agent retrieves
the right pattern and extends it.

**Related:** `systematic-debugging.md` Phase 2 (pattern analysis relies on
giving the model the right reference), `brainstorming.md` (context
exploration step).

---

## Principle 2: Iteration Is Required

**Rule:** Explore, constrain, refine, verify. Don't one-shot. The first
answer is a draft, not a deliverable.

**Violation:** You accept the agent's first-pass database schema without
reviewing it. It normalizes aggressively, creating 7 join tables for what
could be 3 tables with a JSONB column. The query complexity compounds
through the entire codebase before anyone notices.

**Compliance:** You ask the agent to propose 2-3 schema approaches, state
the read/write ratio, then pick one. After the first implementation pass,
you ask "what are the three most likely failure modes for this schema under
10x current load?" and refine before committing.

**Related:** `brainstorming.md` (proposes alternatives before committing),
`writing-plans.md` (breaks work into iterable steps).

---

## Principle 3: Context Windows Forget

**Rule:** Write summary checkpoints to files, not just chat. A decision
that only lives in a chat message is a decision that will be re-derived
from scratch in the next session.

**Violation:** Over a 90-minute session, you and the agent agree to use
event sourcing for the audit log, reject CQRS as overkill, and decide on
a 30-day retention policy. None of this is written down. The next session
starts fresh and proposes CQRS for the audit log.

**Compliance:** After each significant decision, you checkpoint to
`.agent-room/decisions.md`: "Chose event sourcing over CQRS for audit.
Retention: 30 days. Rationale: read load is low, write-append is the
dominant pattern." The next session reads decisions.md first.

**Related:** `closing-the-loop.md` (enforces the checkpoint habit),
`decisions.md` (the storage format).

---

## Principle 4: Explanation Pressure Finds Weak Spots

**Rule:** Ask "explain why" and "what could fail" before shipping. Claims
the model can't justify are claims it shouldn't make.

**Violation:** The agent produces a retry mechanism with exponential
backoff. You say "looks good" and ship. In production, the retry loop
has no jitter, causing thundering herd failures during partial outages
because all retries hit the same millisecond.

**Compliance:** You ask: "Walk me through what happens when 1,000
concurrent requests all fail at the same time and all start retrying." The
agent discovers the jitter gap itself and adds randomized delay before you
have to file the production incident.

**Related:** `verification-before-completion.md` (evidence before claims),
`brainstorming.md` (questioning step).

---

## Principle 5: Negative Knowledge Is Leverage

**Rule:** One avoided mistake is worth more than one polished example. Keep
an anti-patterns file; make the agent read it before every session.

**Violation:** The agent fixes a timezone bug by converting to UTC at the
API boundary. Two weeks later, a different session encounters the same
class of bug in reporting and tries local-time comparison first — because
nobody wrote down the root cause.

**Compliance:** After fixing the timezone bug, the agent appends to
`anti-patterns.md`: "Date comparisons must use UTC. Local time caused
silent data corruption in reporting. Rule: all datetime comparisons
normalized to UTC before comparison." The next session reads this entry
and avoids the trap entirely.

**Related:** `closing-the-loop.md` (the enforcement mechanism),
`anti-patterns.md` (the storage format), `systematic-debugging.md`
(root cause investigation feeds anti-patterns).

---

## Principle 6: Tests Are the Spec

**Rule:** Write the test before the implementation. If the test didn't
fail first, you don't know if it tests the right thing.

**Violation:** The agent writes a user registration endpoint, then writes
tests that assert exactly what the code does — including a bug where
duplicate emails return 200 instead of 409. The test passes, the bug
ships, and the test provides false confidence.

**Compliance:** The agent writes the test first: `POST /register with an
already-registered email should return 409 Conflict`. The test fails
(no implementation yet). The agent writes the handler, the test passes.
The spec drove the code, not the other way around.

**Related:** `test-driven-development.md` (full TDD process),
`systematic-debugging.md` Phase 4 (regression test before fix).

---

## Principle 7: Specific Names Retrieve Better

**Rule:** Prefer clear, specific, stable names over short or sprawling
ones. The model retrieves patterns based on naming — vague names retrieve
vague patterns.

**Violation:** A module is named `utils.js`. It grows to 400 lines
containing date formatting, string sanitization, and HTTP helpers. The
agent asked to "add a utility function" dumps yet another unrelated
function into the file because the name invites everything.

**Compliance:** The module is split into `date-format.js`,
`string-sanitize.js`, and `http-helpers.js`. When the agent is asked to
add date formatting, it finds and extends `date-format.js` without
touching unrelated code. Retrieval matches intent.

**Related:** `brainstorming.md` (naming is a design decision worth
discussing), `writing-plans.md` (exact file paths in every task).

---

## Principle 8: Match Process to Work Type

**Rule:** Use the lightest process that still protects quality.
Over-process wastes time; under-process builds the wrong thing.

**Violation:** A one-line typo fix goes through a full design review,
PRD, architecture doc, and TDD cycle. Or: a new authentication system is
built without any design discussion because "we'll figure it out as we
code."

**Compliance:** The typo fix is classified as Bug → fixed, regression
test, done in hours. The auth system is classified as Feature → full
brainstorm, design doc, architecture review, TDD, done in weeks. The
process matches the risk.

**Related:** `workflow-classifier.md` (the classification system),
`brainstorming.md` (invoked for Features and Products, not Bugs).

---

## Principle 9: PRD and Architecture Co-Evolve

**Rule:** Let architecture discoveries simplify the requirements. Don't
treat the first draft of requirements as sacred — the best designs emerge
when requirements and architecture inform each other.

**Violation:** The PRD demands real-time collaborative editing. The team
implements CRDTs. Mid-implementation, they discover the actual use case is
"two people occasionally edit the same document" — last-write-wins with
conflict detection would have been 90% simpler. But the PRD said
"real-time collaborative editing" so nobody questioned it.

**Compliance:** During architecture exploration, the agent asks: "The PRD
says real-time collaboration. What's the expected concurrent-editor count?
If it's typically 1-2, last-write-wins with conflict UI is dramatically
simpler." The PRD is updated to reflect the simpler requirement.

**Related:** `brainstorming.md` (propose alternatives), `writing-plans.md`
(architecture section in plan header).

---

## Principle 10: Serialize State

**Rule:** A checkpoint should let someone else resume without guesswork.
If you were hit by a bus, could the next person pick up from your notes?

**Violation:** An agent session ends mid-feature with code in a broken
state. The commit message is "WIP." The decisions made during the session
are in the chat history that the next session can't access. The next agent
starts over from scratch.

**Compliance:** Before ending the session, the agent writes a handoff note:
"Completed: user model and migration. In progress: registration endpoint
(handler skeleton exists, validation not started). Blocked on: email
service config (need SMTP credentials in env). Assumptions: using bcrypt
for passwords per decision 2025-01-15." The next session reads this and
picks up exactly where the work stopped.

**Related:** `closing-the-loop.md` (enforces serialization at turn end),
`decisions.md` (persistent state across sessions).

---

## Principle 11: Delegate with Rules, Not Vibes

**Rule:** Before starting work, ask: can I define correctness right now?
Yes → proceed. Missing facts → research. Unclear requirement → escalate.
Don't start building on "I think the user probably wants..."

**Violation:** The agent is asked to "improve the search." It spends 4
hours implementing Elasticsearch integration. The user meant "add a filter
dropdown to the existing search results page." The work is discarded.

**Compliance:** The agent asks: "Improve search could mean several things.
Which of these: (A) add filters to existing search, (B) improve result
relevance ranking, (C) switch to a dedicated search engine like
Elasticsearch? I recommend starting with A — it's the lowest-risk
improvement. What do you think?"

**Related:** `brainstorming.md` (clarifying questions step),
`workflow-classifier.md` (scope determines classification).

---

## Principle 12: Close the Loop

**Rule:** Record failures and wins; feed both back into future prompts.
Knowledge that isn't written down doesn't survive the session.

**Violation:** The agent discovers that the ORM silently truncates strings
longer than 255 characters in a specific column. It fixes the schema but
doesn't record the discovery. Three months later, a different column has
the same issue and takes another full debugging session to diagnose.

**Compliance:** The agent appends to `anti-patterns.md`: "ORM silently
truncates strings at column-defined length with no error. Root cause:
MySQL STRICT_TRANS_TABLES was off. Rule: always enable strict mode; add
length validation in the application layer, don't rely on the database to
reject." Future sessions read this entry first.

**Related:** `closing-the-loop.md` (the skill that enforces this
principle), `anti-patterns.md` and `decisions.md` (the two logs).

---

## Why this matters

Output quality depends on input context quality more than on "prompting
skill." Most failures trace back to one of:

- Vague or missing context (principle 1) — fix the input, not the model.
- A single-shot answer treated as final (principle 2) — iterate instead.
- A long session that silently lost an earlier decision (principle 3) —
  checkpoint to `.agent-room/decisions.md`.
- A claim made without forcing the model (or yourself) to explain it
  (principle 4) — ask "what could fail here?" before shipping.
- The same mistake repeated because nobody wrote it down (principle 5/12) —
  log it in `.agent-room/anti-patterns.md`.

> Fill the context with the right information at the right time.
