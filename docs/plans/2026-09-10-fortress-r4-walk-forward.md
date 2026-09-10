# Fortress R4 Walk-Forward Validation Implementation Plan

**Goal:** Add a deterministic, research-only walk-forward evaluator for R1/R2 data that separates training, validation, and untouched out-of-sample test periods.
**Architecture:** Read the R1 SQLite session calendar, observations, labels, and prices without mutating or rescoring production data. Generate 252/63/63-session rolling windows with a 63-session step, evaluate fixed Fortress score buckets and top-N portfolios (N=5/10/20), and compare Nifty, simple momentum, and equal-universe baselines. Emit per-window and aggregate JSON/CSV/Markdown reports.
**Tech stack:** Python 3.9+, sqlite3, pandas/numpy already present in the backend, pytest.

---

### Task 1: Define the R4 evaluator contract and synthetic regression fixture

**Files:**
- Create: `tests/backend/test_walk_forward_validation.py`

**Step 1: Write the failing tests**

Add a synthetic R1 SQLite fixture with a known session calendar, two rolling windows,
multiple symbols, archived scores, RS scores, Nifty prices, and 5/10-day labels.
Test that:

- windows are exactly 252 train, 63 validation, 63 test sessions with 63-session
  advancement;
- train/validation/test dates are disjoint and ordered;
- test observations cannot influence window training summaries;
- fixed top-N selection is deterministic and handles N larger than the eligible
  universe;
- score-bucket, top-N, momentum, equal-universe, and Nifty metrics are returned;
- forward-return aggregation, win rate, benchmark excess, drawdown, and turnover
  are correct on known synthetic prices;
- incomplete windows and missing labels are reported without imputation;
- JSON/CSV/Markdown output is deterministic.

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_walk_forward_validation.py`
Expected: FAIL because the R4 module does not exist.

### Task 2: Implement deterministic walk-forward windowing and data loading

**Files:**
- Create: `engine/research/walk_forward_validation.py`

**Step 1: Write minimal implementation**

Implement typed constants and helpers for:

- `TRAIN_SESSIONS = 252`, `VALIDATION_SESSIONS = 63`,
  `TEST_SESSIONS = 63`, `STEP_SESSIONS = 63`;
- loading sessions, observations, labels, and prices from an R1 SQLite database;
- generating only complete ordered windows from the declared `sessions` table;
- validating that score/feature dates are assigned to their own window only;
- deterministic sorting by session date, score descending, and symbol;
- fixed score buckets reused from R2 without modifying R2;
- extraction of archived `RS_Score` for the momentum baseline.

No production scoring import, price fill, label fill, or parameter optimization is
allowed.

**Step 2: Run focused tests**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_walk_forward_validation.py -k 'window or leakage'`
Expected: PASS.

### Task 3: Implement portfolio evaluation and comparison metrics

**Files:**
- Modify: `engine/research/walk_forward_validation.py`
- Test: `tests/backend/test_walk_forward_validation.py`

**Step 1: Write failing metric tests**

Assert per-window and aggregate metrics for:

- Fortress score buckets;
- top-N Fortress portfolios for N=5, 10, 20;
- top-N archived RS_Score momentum portfolios;
- equal-weight eligible-universe baseline;
- Nifty benchmark;
- mean/median return, win rate, benchmark excess, sample size;
- cumulative equity, max drawdown, and turnover based on set overlap between
  consecutive test-window portfolios.

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_walk_forward_validation.py -k 'metric or portfolio or turnover'`
Expected: FAIL for missing evaluator functions/fields.

**Step 3: Implement minimal metric engine**

Use only valid R1 labels. Keep missing labels visible in coverage counts and exclude
them from the specific metric denominator. Treat Nifty as the benchmark symbol
provided by the CLI. Use equal-weight aggregation within each selected portfolio;
do not claim executable performance or add transaction costs not present in R1.

**Step 4: Run focused tests**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_walk_forward_validation.py`
Expected: PASS.

### Task 4: Add report serialization and CLI

**Files:**
- Modify: `engine/research/walk_forward_validation.py`
- Create: `docs/research/walk_forward_validation.md`
- Test: `tests/backend/test_walk_forward_validation.py`

**Step 1: Write failing serialization tests**

Assert stable JSON key ordering, CSV row ordering, Markdown sections for methodology,
in-sample performance, out-of-sample performance, degradation, stability, sample
sizes, and limitations.

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=.:engine .venv/bin/pytest -q tests/backend/test_walk_forward_validation.py -k 'report or serialization'`
Expected: FAIL because report writers do not exist.

**Step 3: Implement report writers and CLI**

Provide:

```bash
PYTHONPATH=.:engine .venv/bin/python -m research.walk_forward_validation \
  /path/to/r1-dataset.sqlite \
  --output-dir /path/to/r4-output \
  --benchmark NIFTY
```

Write deterministic `r4_walk_forward.json`, `r4_windows.csv`,
`r4_metrics.csv`, and `r4_walk_forward.md`. Include explicit window geometry,
whether validation was used for tuning (`false` by default), all parameter values,
and limitations.

**Step 4: Run tests and lint**

Run:

```bash
PYTHONPATH=.:engine .venv/bin/pytest -q \
  tests/backend/test_walk_forward_validation.py \
  tests/backend/test_forward_return_validation.py
.venv/bin/ruff check engine/research/walk_forward_validation.py \
  tests/backend/test_walk_forward_validation.py
```

Expected: all tests pass and Ruff reports no errors.

### Task 5: Verify compatibility and commit

**Files:**
- No additional source changes unless verification finds an R4-specific defect.

**Step 1: Run the affected research suite**

Run:

```bash
PYTHONPATH=.:engine .venv/bin/pytest -q \
  tests/backend/test_historical_dataset.py \
  tests/backend/test_forward_return_validation.py \
  tests/backend/test_feature_correlation_ablation.py \
  tests/backend/test_walk_forward_validation.py
```

Expected: all affected research tests pass.

**Step 2: Commit**

```bash
git add engine/research/walk_forward_validation.py \
  tests/backend/test_walk_forward_validation.py \
  docs/research/walk_forward_validation.md
git commit -m "feat(fortress): add R4 walk-forward validation"
```
