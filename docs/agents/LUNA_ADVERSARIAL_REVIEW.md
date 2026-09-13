# LUNA MISSES CLOSEOUT — Epic 20: Final Adversarial Review

Per this closeout's own instruction, this review's mandate was NOT "did we
satisfy our own tests" — it was "what important assumption are our tests
not checking." Conducted against the closeout's own PRs (#80-87) after
every other epic's P0/P1 work had landed, as required.

## Findings and outcomes

| # | Claim under test | Result | Outcome |
|---|---|---|---|
| 1 | Reviewer evidence gate (PR #80) blocks unreviewed logic changes | **CONFIRMED GAP** | Fixed — see below |
| 2 | docs_required escalation (PR #84) catches security-sensitive changes | **CONFIRMED GAP** | Fixed — see below |
| 3 | Architecture fitness test (PR #86) prevents direct yfinance imports in routers | **CONFIRMED GAP** (narrow) | Documented, not fixed — see rationale |
| 4 | Production smoke test (PR #87) can never mutate production | **CONFIRMED GAP** (latent, not exploited) | Documented, not fixed — see rationale |

### 1. Fixed: `classifyFile()`'s free-pass fallback

`reviewer-evidence.js`'s category rules were all scoped to specific
directory prefixes (`backend_logic`: `engine/**.py`, `frontend_logic`:
`frontend/src/**`). A real code file living outside those trees — e.g.
`scripts/pricing_engine.py`, `worker/*.py` — fell all the way through to
`'other'`, which requires **zero evidence** by design (a docs-only or
lockfile-only PR shouldn't be held to a test bar it can't clear). That
meant a genuine, unreviewed logic change could dodge the evidence gate
entirely just by living in a directory none of the category regexes
anticipated.

**Fix:** any changed file with a recognized source-code extension
(`.py .js .jsx .ts .tsx .mjs .cjs .go .rs .java .rb .sh .bash`) that no
named category claims now classifies as `other_code` instead of `other`,
and requires generic test evidence (any `tests/**` file, `frontend/e2e/**`,
`frontend/tests/**`, or a `*.test.*` file in the same diff). Only
genuinely non-code files (configs, lockfiles, images) still land in the
truly-free `other` bucket. 4 new tests in `reviewer-evidence.test.js`.

### 2. Fixed: `security_auth`'s narrow keyword match

The category's test was `/auth/i.test(f) || /security_config/i.test(f)`
— a file handling tokens, sessions, crypto, secrets, or rate limiting
(all genuinely security-sensitive) with no literal "auth" in its path
fell through to `backend_logic`, which `docs-evidence.js`'s
`DOCS_LIKELY_CATEGORIES` doesn't escalate for docs requirements.

**Fix:** widened the regex to also match
`token|session|crypto|secret|rate_limit`. Both the classifier and its
matching evidence-requirement test were updated together so a
`security_auth`-classified change still needs a `tests/**` file mentioning
one of the same keywords.

### 3. Documented, not fixed: dynamic-import bypass

`test_architecture_fitness.py`'s AST-based check (correctly) walks into
function bodies to catch lazy `import yfinance`, but only matches
`ast.Import`/`ast.ImportFrom` nodes — `importlib.import_module("yfinance")`
or `__import__("yfinance")` would not be caught. No code in this
repository does this today; a fitness test hardened against a
*deliberately evasive* dynamic import (as opposed to a careless direct
one, the actual failure mode this test exists to catch) is a
disproportionate response to a threat that doesn't exist here. Recorded
in `.agent-room/decisions.md` as an accepted limitation, not silently
assumed away.

### 4. Documented, not fixed: GET-for-mutation bypass

`smoke-production.spec.ts`'s safety guard (PR #87) decides "safe to let
through" purely by HTTP method (GET/HEAD pass, everything else but
login/logout is blocked) — it does not know anything about a given
endpoint's semantics. A mutating action incorrectly exposed as a GET route
would slip through undetected. Verified: no such route exists anywhere in
`engine/routers/*` today (every mutation-shaped endpoint is POST). The
claim "can never mutate production" is therefore true of this codebase's
current conventions, not of the guard mechanism itself — recorded here so
a future GET-based mutation endpoint doesn't silently inherit an assumed
safety property the test was never actually enforcing.
