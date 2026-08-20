# Workflow Classifier

Not all work deserves the same process. Classify before loading process —
over-process wastes time, under-process builds the wrong thing.

## Quick classifier

| Work Type | Use it for | PRD | Architecture | TDD | Time |
| --- | --- | --- | --- | --- | --- |
| Bug | Something broke | None | None | Fix + regression test | Hours |
| Enhancement | Small change on existing rails | Light | Light | Yes | Days |
| Feature | New bounded capability | Yes | Yes | Full | Weeks |
| Product | New system or unclear scope | Deep | Extensive | Full + spikes | Months |

## Decision tree

```
Did something break?
  yes -> Bug Flow
  no
    Does similar code/pattern already exist in this repo?
      yes -> Enhancement Flow
      no
        Is the scope clear and bounded?
          yes -> Feature Flow
          no  -> Product Flow
```

Stop as soon as one answer is clear. Ask in this order:
1. Did something break?
2. Am I extending an existing pattern?
3. Can I define "done" right now?
4. If not, am I still discovering the problem?

## Worked examples

### "Fix: login button returns 500 on Safari"
- Did something break? Yes — it worked before, now it doesn't.
- **Classification: Bug.**
- Process: Reproduce on Safari, read the server logs, find the root cause
  (not the symptom), write a regression test, smallest fix, note why it
  slipped through in `anti-patterns.md`. Hours.

### "Add dark mode to the settings page"
- Did something break? No.
- Does similar code exist? Yes — there's already a theme toggle in the
  header component and CSS custom properties for colors in `theme.css`.
- **Classification: Enhancement.**
- Process: Light PRD (one paragraph: "extend the existing theme system to
  settings page, using the same CSS custom properties"), find the closest
  prior example (`Header.tsx` theme toggle), TDD the new toggle, 1-2 days.

### "Support webhook notifications for order status changes"
- Did something break? No.
- Does similar code exist? No — there's no webhook infrastructure, no
  event system, no retry queue.
- Is the scope clear? Yes — we know exactly which events trigger webhooks,
  the payload shape, and the delivery guarantees we need.
- **Classification: Feature.**
- Process: Full brainstorm (delivery guarantees? retry policy? signature
  verification?), design doc, architecture review, TDD, 1-2 weeks.

### "We need to support multi-tenant data isolation"
- Did something break? No.
- Does similar code exist? No — the app is single-tenant.
- Is the scope clear? Partially — we know what isolation means, but the
  migration strategy, tenant resolution mechanism, and query scoping
  approach all need design. We're still discovering the problem.
- **Classification: Product.**
- Process: Define the problem before the feature list. Write key hypotheses
  ("row-level security vs. schema-per-tenant"). Spike the risky assumptions.
  Build the smallest useful proof of concept. Learn and iterate. Months.

## Misclassification signals

You classified wrong if any of these are true:

| Signal | What it means |
| --- | --- |
| A "Bug" fix requires changing more than 3 files | It's probably an Enhancement or Feature — the root cause is structural, not a local defect. |
| An "Enhancement" keeps revealing new unknowns | It's actually a Feature — you can't define "done" because the scope keeps growing. |
| A "Feature" has been in progress for 2+ months | It's actually a Product — the scope was never bounded, and you're discovering requirements as you build. |
| A "Product" has a perfectly clear scope and takes 2 weeks | It was a Feature all along — you over-classified and loaded unnecessary process. |
| Time spent dramatically exceeds the budget below | The classification, not the estimate, is probably wrong. Re-classify rather than push through. |

**The fix is always the same:** stop, re-classify, adjust the process.
Don't push through with the wrong process — that's how Bug fixes become
multi-week refactors and Features become death marches.

## Bug Flow (hours)
Reproduce -> Diagnose (root cause, not symptom) -> Write the regression test
first -> Smallest fix that passes -> Run the relevant checks -> Note why it
slipped through (append to `.agent-room/anti-patterns.md`).

Do not load: PRD files, architecture exploration, spikes.

## Enhancement Flow (days)
Confirm it fits existing rails -> short PRD (a paragraph is fine) -> find the
closest prior example in the codebase -> TDD -> quick review and ship.

Rule of thumb: if you can describe it as "do X like we already do Y," it's an
enhancement. If you can't find a Y, it's a feature.

## Feature Flow (weeks)
Write the first design from the user journey -> let architecture discoveries
tighten/simplify the design (don't treat draft 1 as sacred) -> TDD against the
final shape -> review -> observe after shipping.

Use the `brainstorming` -> `writing-plans` -> TDD chain in `.agent-room/skills/`
for this.

## Product Flow (months)
Define the problem before the feature list -> write the key hypotheses ->
spike the risky assumptions -> build the smallest useful MVP -> learn from
reality and loop (iterate or pivot).

## Time budget as a signal

| Work Type | Design | Build | Review | Total |
| --- | --- | --- | --- | --- |
| Bug | 0 | ~2h | 30m | hours |
| Enhancement | 30m | ~4h | 1h | 1-2 days |
| Feature | 4-8h | 16h+ | 4h | 1-2 weeks |
| Product | 8h+ | 40h+ | 8h+ | 4+ weeks |

If real work keeps blowing past the expected budget, the classification —
not the estimate — is probably wrong. Re-classify rather than push through.
