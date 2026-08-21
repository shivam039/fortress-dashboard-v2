# Decisions Log — app

Short, append-only record of architecture/design decisions and why. A
decision belongs here if a future session (or a future you) would otherwise
have to re-derive it from scratch by reading git history.

## Format

```
### YYYY-MM-DD — short title

**Decision:** what was decided.
**Why:** the constraint or trade-off that drove it.
**Rejected:** what else was considered, and why it lost.
```

<!-- Entries go below this line, newest first. -->

### 2026-08-21 — Configure Vercel FastAPI entrypoint

**Decision:** Declare `engine.main:app` in the `[tool.vercel]` section of
`pyproject.toml` so Vercel can deploy the repository-root FastAPI backend.
**Why:** Vercel's build could find the application but could not select an
entrypoint automatically.
**Rejected:** Moving or duplicating the FastAPI app into a default location.
Rejected because the existing module is already the canonical backend entrypoint.

### 2026-07-10 — Final cleanup standardizes formatting and repository layout

**Decision:** Added explicit formatter/linter configuration in `pyproject.toml`, ran `isort`, `black`, and `ruff` across the Python project, kept legacy modules excluded from Ruff enforcement, and moved the cron setup utility into `scripts/`.
**Why:** The development-db branch needed a consistent, review-ready baseline without changing core business behavior. Formatting the full Python tree makes future diffs smaller and easier to review, while excluding legacy modules avoids turning archival code into an unrelated cleanup project.
**Rejected:** Selectively formatting only touched files. Rejected because the requested final cleanup pass specifically asked to run project formatting tools and improve overall structure.


### 2026-07-10 — Adopt multi-layer ui/ architecture (internal single-page routing)

**Decision:** Extracted the 1,626-line `streamlit_app.py` monolith into a structured `ui/` package:
- `ui/state.py` — central state manager with typed getters, `bootstrap()`, `require_login()`, and broker cache helpers
- `ui/components/` — reusable widgets: `auth`, `broker`, `orders`, `profile`, `sidebar`
- `ui/utils/` — pure helpers: `formatting`, `scan` (run_scan_directly / fetch_universes), `telegram`
- `ui/views/` — one `render()` entry-point per module: dashboard, stock_screener, mf_lab, orders, commodities, options, history
- `streamlit_app.py` reduced to ~200 lines (path setup + bootstrap + sidebar + routing only)
**Why:** Adopted internal single-page routing (not `pages/` folder) because `pages/` does not automatically apply the auth gate — each sub-page file would need its own `require_login()` check, increasing boilerplate and risk of auth bypass. Internal routing keeps a single `st.stop()` as the auth gate.
**Rejected:** Streamlit `pages/` folder. Rejected because the auth gate must protect every module and `pages/` has no built-in auth guard.



### 2026-07-10 — Improve normalization fallback for zero-variance universes and single stock scans

**Decision:** Modified `_normalize_series` in `engine/stock_scanner/logic.py` to return the absolute values (clamped to `[0, 100]`) instead of forcing them to a constant `50.0` when `max_v == min_v`.
**Why:** To ensure that single stock scans or uniform lists (zero variance) reflect the correct raw technical/fundamental scores rather than degrading/inflating all values to a middle-of-the-road average.
**Rejected:** Forcing a constant `50.0` or raising an exception.

### 2026-07-10 — Resolve test suite execution hangs and logic errors

**Decision:** Optimized repository test suite execution and fixed logic bugs in mutual fund tools:
1. Configured local test environment `conftest.py` to force `FORTRESS_DB_BACKEND=sqlite` to prevent execution hangs from attempting connections to PostgreSQL/Neon.
2. Updated `detect_integrity_issues` in `mf_lab/logic.py` to align indices on `'date'` when it is present as a column, resolving testing alignment errors.
3. Corrected safe_session_state lookup syntax in `tests/frontend/test_login.py`.
4. Completed implementation of `render_selected_schemes_analysis` in `ui_scheme_discovery.py` replacing the TODO placeholder with the real `fetch_mf_snapshot` call.
**Why:** To ensure 100% passing tests, zero execution hangs, and complete, functional mutual fund scheme browsing/analysis.
**Rejected:** Leaving tests disabled or stubs. Rejected because maintaining a clean, passing test suite is key to code quality and prevents regressions.

### 2026-07-10 — Prevent commits from corporate email addresses

**Decision:** Modified the pre-commit guardrails hook to strictly prevent commits using corporate email addresses (`shivam.dixit@publicissapient.com` and `shidixit2@publicisgroupe.net`).
**Why:** To enforce repository security constraints requiring all contributions to use `shivamdixit039@gmail.com` as the commit author/committer.
**Rejected:** Checking the email inside `.git/hooks/pre-commit` itself. Rejected because `.git/` is not committed/shared, whereas `.agent-room/hooks/guardrails-check.js` is tracked in git and will be distributed to all clones/agents.

### 2026-07-10 — Scaffold full agent-room profile

**Decision:** Scaffolded the full agent-room profile, including coordination protocols, principles.md, workflow-classifier.md, and configured .agent-room.json to use "profile": "full".
**Why:** To ensure the workspace has all the recommended agent-room files and matches the specifications referenced in AGENTS.md.
**Rejected:** Keeping the minimal profile. Rejected because AGENTS.md specifically directs agents to read .agent-room/principles.md and workflow-classifier.md, which were missing in the minimal profile.
