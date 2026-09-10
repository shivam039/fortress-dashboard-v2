# Fortress R3 Feature Correlation and Ablation Implementation Plan

**Goal:** Build a deterministic research-only analyzer for feature correlation, contribution, ablation, ranking stability, and forward-return impact using an R1 SQLite dataset.
**Architecture:** Read-only analysis of `observations.features_json`, archived scores, and R1 labels. Correlation and contribution metrics are calculated per feature and overall; exact ablations use explicit archived per-feature point contributions when present, while unavailable ablations are reported as unsupported rather than reconstructed from assumptions. Outputs are JSON, CSV, and Markdown.
**Tech stack:** Python 3.9+, pandas/numpy already used by the backend, sqlite3, pytest.

---

### Task 1: Extend the R1 research feature allowlist

**Files:**
- Modify: `engine/research/historical_dataset.py`
- Test: `tests/backend/test_historical_dataset.py`

**Step 1: Write the failing test**

Add a builder regression assertion that an input snapshot containing the investigated indicator fields and `Feature_Contributions` preserves those fields in `observations.features_json`.

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_historical_dataset.py`
Expected: FAIL because the current allowlist drops the new research fields.

**Step 3: Write minimal implementation**

Add the documented indicator names and `Feature_Contributions` to the existing `FEATURES` tuple. Do not alter score fields, production scoring, validation rules, or label generation.

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_historical_dataset.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add engine/research/historical_dataset.py tests/backend/test_historical_dataset.py
git commit -m "feat(fortress): preserve R3 research features in R1"
```

### Task 2: Implement the R3 analysis engine

**Files:**
- Create: `engine/research/feature_correlation_ablation.py`
- Test: `tests/backend/test_feature_correlation_ablation.py`

**Step 1: Write the failing tests**

Cover:
- deterministic feature extraction from `features_json`;
- Pearson and Spearman feature correlation with pairwise missing-value handling;
- score contribution diagnostics, including sample size, score correlation, and partial R²;
- exact ablation when `Feature_Contributions` is present;
- explicit `unsupported` status when contribution evidence is absent;
- ranking change metrics and forward-return differences for each horizon;
- deterministic JSON/Markdown serialization and CLI-compatible report structure.

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_feature_correlation_ablation.py`
Expected: FAIL because the module does not exist.

**Step 3: Write minimal implementation**

Implement:
- typed dataclasses for feature diagnostics, ablation results, and report metadata;
- a read-only SQLite loader joining observations to labels;
- canonical feature aliases for EMA alignment, Supertrend, ADX, 52-week distance, relative strength, volume surge, breakout, VCP/coiling, and overextension;
- pairwise Pearson/Spearman correlation matrix;
- contribution analysis against archived `fortress_score`, with optional date-clustered diagnostics and no fitted production weights;
- exact point-contribution ablation by neutralizing one or a declared group in `Feature_Contributions`, preserving regime/gate adjustments from the archived score;
- ranking stability metrics (Spearman rank agreement, top-quintile overlap, changed rank count);
- forward-return impact by horizon using only rows with valid baseline and ablated labels;
- group definitions for momentum/trend, participation/breakout, volatility/VCP, and overextension;
- report writers for JSON, CSV tables, and Markdown;
- CLI accepting an R1 SQLite path and output directory, with deterministic ordering and an option to fail on unsupported exact ablations.

The engine must never import or call production scanner scoring, mutate the database, fill missing features, or turn unsupported ablations into zero-point contributions.

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_feature_correlation_ablation.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add engine/research/feature_correlation_ablation.py tests/backend/test_feature_correlation_ablation.py
git commit -m "feat(fortress): add R3 feature ablation analyzer"
```

### Task 3: Document execution and interpretation

**Files:**
- Create: `docs/research/feature_correlation_ablation.md`

**Step 1: Document the CLI**

Include the exact command, output files, R1 schema prerequisites, missing-data policy, exact-versus-unsupported ablation semantics, and examples of how to interpret correlation, contribution, rank, and return tables.

**Step 2: Document research guardrails**

State that correlation is not proof of redundancy, archived scores remain unchanged, close-to-close labels are descriptive rather than executable strategy results, and no recommendation is valid when the relevant evidence is unavailable or sample sizes are insufficient.

**Step 3: Verify documentation references**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_historical_dataset.py tests/backend/test_feature_correlation_ablation.py`
Expected: PASS.

**Step 4: Commit**

```bash
git add docs/research/feature_correlation_ablation.md
git commit -m "docs(fortress): document R3 feature ablation analysis"
```
