---
name: brainstorming
description: "Use before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores intent, requirements and design before implementation."
---

# Brainstorming Ideas Into Designs

## Overview

Turn an idea into a fully formed design through collaborative dialogue
before writing any code.

<HARD-GATE>
Do NOT write code, scaffold a project, or take any implementation action
until a design has been presented and approved. This applies to every
project regardless of perceived simplicity.
</HARD-GATE>

## Anti-pattern: "this is too simple to need a design"

A todo list, a single-function utility, a config change — all of them go
through this process. "Simple" work is where unexamined assumptions cause
the most wasted effort. The design can be a few sentences for truly simple
work, but it must be presented and approved.

## Process

1. **Explore project context** — read `.agent-room/decisions.md`,
   `.agent-room/anti-patterns.md`, relevant docs, recent commits.
2. **Ask clarifying questions, one at a time** — multiple-choice preferred,
   open-ended is fine. Focus on purpose, constraints, success criteria.
3. **Propose 2-3 approaches** with trade-offs, leading with a recommendation
   and why.
4. **Present the design in sections**, scaled to complexity (a few sentences
   if straightforward, up to 200-300 words if nuanced). Cover architecture,
   components, data flow, error handling, testing. Ask after each section
   whether it looks right before moving on.
5. **Write the approved design** to `docs/plans/YYYY-MM-DD-<topic>-design.md`
   and commit it.
6. **Hand off to implementation** — see "After the design" below.

```
Explore context -> Ask questions (1 at a time) -> Propose 2-3 approaches
   -> Present design (section by section, approve each) -> Write design doc
   -> Implementation (see below)
```

## After the design

- If a `writing-plans`-style skill/convention is available for this
  project, use it to turn the design into a bite-sized task plan before
  touching code.
- Otherwise, proceed straight into TDD (`.agent-room/skills/test-driven-development.md`),
  using the design doc as the spec, one task at a time, with frequent commits.
- Do not skip straight to a broad implementation pass — even with an
  approved design, work task-by-task.

## Key principles

- One question at a time — don't overwhelm with multiple questions.
- Multiple choice preferred over open-ended when reasonable.
- YAGNI ruthlessly — remove unnecessary features from the design.
- Always propose alternatives before settling on one.
- Get incremental approval; be ready to revise when something doesn't add up.
