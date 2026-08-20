# Agent Guardrails — app

Boundaries and constraints for AI agents working in this codebase. Read
this file before making changes to protected areas. When in doubt, ask
the maintainer rather than proceeding.

## Protected paths

Files and directories that agents must not modify without explicit
approval from the project maintainer:

<!-- Add paths that require human review before agent modification.
     Examples: infrastructure/, *.tfstate, docker-compose.prod.yml,
     .github/workflows/, database/migrations/ -->

## Approval requirements

Changes that require human review, even if technically possible:

- Database migrations (schema changes, data backfills)
- Dependency major version bumps
- Changes to CI/CD pipeline configuration
- Changes to authentication or authorization logic
- Modifications to production deployment configuration

## Scope guidance

Keep individual changes focused and reviewable:

- **Aim for:** single-purpose PRs, one concern per change
- **Watch for:** PRs touching more than 15-20 files, changes exceeding
  ~500 lines of new code, or changes that mix refactoring with new features
- These are guidelines, not hard limits — a migration touching 30 files
  may be appropriate, but it deserves extra scrutiny

## Forbidden actions

Actions agents must never take, regardless of context. These are
human-facing intents — read and follow them; they are not something a
regex can check for you:

- Deploy to production without human approval
- Delete database tables or collections in production
- Modify authentication middleware without security review
- Commit secrets, API keys, or credentials to the repository
- Disable or skip tests to make a build pass
- Suppress security audit warnings without documenting why

The narrower, mechanically-checkable case — "does this diff literally
contain something that looks like a credential" — is enforced separately
by the pre-commit hook, which pattern-matches staged content against the
`forbiddenActions` entries in `.agent-room/guardrails.json` (AWS keys,
private key headers, API token formats, and similar). That JSON list is
deliberately narrow and pattern-based; it can't catch "committed a secret
in a format we didn't anticipate," so the prose rule above still applies
even where the hook stays silent.

## How to use this file

1. **Before starting work:** Scan the change against protected paths. If
   the change touches a protected area, ask the maintainer for approval.
2. **During work:** Check scope guidance. If the change is growing beyond
   the guidelines, consider splitting it.
3. **Before finishing:** Verify none of the forbidden actions were taken.

For machine-readable guardrails that CI and tooling can enforce, see
`.agent-room/guardrails.json`.
