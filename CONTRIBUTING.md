# Contributing to Fortress Dashboard

Thank you for contributing! This guide explains the project conventions and how to add the most common types of contributions: new stock universes, new scanner signals, new dashboard views, and new engine modules.

> **Before you start:** Read [AI_AGENT_PROTOCOL.md](./AI_AGENT_PROTOCOL.md) — its rules apply to all contributors (human and AI).

---

## Table of Contents

1. [Development Setup](#1-development-setup)
2. [Repository Conventions](#2-repository-conventions)
3. [How to Add a New Stock Universe](#3-how-to-add-a-new-stock-universe)
4. [How to Add a New Scanner Signal](#4-how-to-add-a-new-scanner-signal)
5. [How to Add a New Dashboard View](#5-how-to-add-a-new-dashboard-view)
6. [How to Add a New Engine Module](#6-how-to-add-a-new-engine-module)
7. [Testing Requirements](#7-testing-requirements)
8. [Commit & PR Standards](#8-commit--pr-standards)
9. [AI Agent Rules](#9-ai-agent-rules)

---

## 1. Development Setup

```bash
git clone https://github.com/your-org/fortress-dashboard
cd fortress-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds pytest, flake8

export FORTRESS_DB_BACKEND=sqlite     # no Neon needed for dev
streamlit run streamlit_app.py
```

Run tests before any commit:

```bash
PYTHONPATH=.:engine .venv/bin/pytest -v
```

---

## 2. Repository Conventions

### Python style

- **PEP 8** compliance. Line length ≤ 88 (Black-compatible).
- **Type hints** on all function signatures.
- **Docstrings** on every public function and class (Google-style or NumPy-style, be consistent within a file).
- **No bare `except`** — catch specific exceptions.
- **No `import *`** — always explicit imports.

### Imports order (isort-style)

```python
# 1. stdlib
import os
from typing import Dict, List

# 2. third-party
import pandas as pd
import streamlit as st

# 3. engine packages
from fortress_config import TICKER_GROUPS
from utils.db import fetch_fortress_orders

# 4. ui packages (only in ui/ layer)
from ui.state import State
from ui.utils.api import trigger_scan
```

### Separation of concerns

| Layer | What belongs here |
|---|---|
| `ui/views/` | Streamlit `render()` functions only — no HTTP calls, no SQL |
| `ui/utils/api.py` | All FastAPI HTTP calls — no UI widgets here |
| `ui/utils/scan.py` | In-process engine fallbacks — no UI widgets here |
| `engine/*/logic.py` | Pure business logic — no Streamlit, no HTTP |
| `engine/*/ui.py` | Engine-level Streamlit rendering (called by `ui/views/`) |
| `engine/utils/db.py` | All database access — no business logic |

---

## 3. How to Add a New Stock Universe

Stock universes are defined as ticker lists in `engine/fortress_config.py`.

**Step 1** — Add your tickers to the `TICKER_GROUPS` dict:

```python
# engine/fortress_config.py
TICKER_GROUPS = {
    # ... existing universes ...
    "Nifty IT": [
        "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS",
        "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "OFSS.NS",
    ],
}
```

**Step 2** — Add sector mappings if needed:

```python
# engine/fortress_config.py  — SECTOR_MAP dict
SECTOR_MAP = {
    # ...
    "TCS.NS": "Technology",
    "INFY.NS": "Technology",
    # etc.
}
```

**Step 3** — Test that the universe appears in the sidebar:

```bash
PYTHONPATH=.:engine .venv/bin/pytest -v -k "screener"
```

No other code changes are needed — the universe list is fetched dynamically from `fortress_config.TICKER_GROUPS`.

---

## 4. How to Add a New Scanner Signal

Scanner signals live in `engine/stock_scanner/logic.py` inside `check_institutional_fortress()`.

**Step 1** — Identify the signal phase:

| Phase | Where to add |
|---|---|
| Technical (price/volume/momentum) | `_score_technical()` |
| Fundamental (earnings/valuation) | `_score_fundamental()` |
| Sentiment (breadth/flow) | `_score_sentiment()` |
| Context (regime/sector) | `_score_context()` |

**Step 2** — Add the signal and its point contribution:

```python
# engine/stock_scanner/logic.py

def _score_technical(hist: pd.DataFrame, config: dict) -> float:
    score = 0.0
    # ... existing signals ...

    # ── Your new signal ────────────────────────────────────────────────
    # Example: ADX > 25 = strong trend
    try:
        if "ADX_14" in hist.columns and hist["ADX_14"].iloc[-1] > 25:
            score += 5.0          # max contribution: 5 pts
    except Exception:
        pass                      # never raise — degrade gracefully

    return score
```

**Step 3** — Document it in `SCORING.md`:

Add a row to the relevant signal table in [SCORING.md](./SCORING.md):

```markdown
| ADX > 25 | +5 | Strong directional trend confirmation |
```

**Step 4** — Write a unit test:

```python
# tests/backend/test_stock_scanner_scoring.py

def test_adx_trend_signal_contributes_score():
    hist = _make_hist_with_adx(adx_value=30)
    result = _score_technical(hist, DEFAULT_SCORING_CONFIG)
    assert result > 0
```

---

## 5. How to Add a New Dashboard View

**Step 1** — Create `ui/views/my_view.py`:

```python
"""
ui/views/my_view.py  —  My New View
=====================================
Brief description of what this view shows.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from ui.utils.error_handling import error_boundary  # type: ignore[import]


def render(username: str) -> None:
    """
    Render the 🆕 My View module.

    Args:
        username: Current logged-in username.
    """
    st.subheader("🆕 My View")
    st.caption("What this view does in one sentence.")

    with error_boundary("My View"):
        # Your rendering code here
        st.info("Coming soon!")
```

**Step 2** — Register the module in `ui/state.py`:

```python
# ui/state.py
BASE_MODULES: List[str] = [
    "🏠 Dashboard",
    "📊 Stock Screener",
    "📈 MF Lab",
    "📋 Orders",
    "🌍 Commodities",
    "⚡ Options",
    "🕐 Scan History",
    "🆕 My View",   # ← Add here
]
```

**Step 3** — Wire routing in `streamlit_app.py`:

```python
# streamlit_app.py
import ui.views.my_view as _v_my  # add with the other imports

# ...in the routing block at the bottom:
elif module == "🆕 My View":
    _v_my.render(username)
```

**Step 4** — Add sidebar filters if needed in `ui/components/sidebar.py` → `render_module_filters()`.

---

## 6. How to Add a New Engine Module

For a self-contained analysis domain (e.g., "Crypto", "Fixed Income"):

**Step 1** — Create the module directory:

```
engine/my_module/
├── __init__.py
├── logic.py      # Pure business logic — no Streamlit
└── ui.py         # Streamlit rendering — imports from logic.py
```

**Step 2** — Expose a `render()` function in `ui.py`:

```python
# engine/my_module/ui.py
def render(broker_name: str) -> None:
    """Top-level render entry-point called by ui/views/my_view.py."""
    ...
```

**Step 3** — Register in `engine/main.py` if you need API endpoints.

**Step 4** — Pre-load the module in `streamlit_app.py` to avoid concurrent reload issues:

```python
# streamlit_app.py — engine pre-load block
engine_pkgs = ["utils", "mf_lab", "stock_scanner", "options_algo",
               "commodities", "fortress_config", "my_module"]  # ← add here
```

---

## 7. Testing Requirements

- All new Python code **must have at least one test**.
- Tests live in `tests/` (backend logic) or `engine/*/tests/` (engine unit tests).
- Frontend tests using `AppTest` live in `tests/frontend/`.
- Always use `FORTRESS_DB_BACKEND=sqlite` in tests (see `tests/conftest.py`).

```bash
# Run all tests
PYTHONPATH=.:engine .venv/bin/pytest -v

# Run only backend tests
PYTHONPATH=.:engine .venv/bin/pytest tests/backend/ -v

# Run linting
.venv/bin/flake8 engine/ ui/ --max-line-length 88
```

---

## 8. Commit & PR Standards

### Commit format

```
type(scope): short description

Examples:
feat(screener): add ADX trend strength signal
fix(mf_lab): handle empty NAV cache on first startup
docs(readme): add Docker Compose deployment guide
refactor(ui): extract broker settings into component
test(scoring): add conviction score zero-variance test
```

### Branch naming

```
feat/adx-signal
fix/mf-nav-empty-cache
docs/deployment-guide
refactor/broker-component
```

### Commits must be from

```
shivamdixit039@gmail.com
```

Commits from `shivam.dixit@publicissapient.com` or `shidixit2@publicisgroupe.net` are **blocked** by the pre-commit hook.

### Checklist before pushing

- [ ] `pytest` passes (all 14+ tests green)
- [ ] New functions have type hints and docstrings
- [ ] `flake8` reports no errors
- [ ] Change is logged to `logs/ai_audit_log.jsonl` (AI agents only — use `engine/utils/ai_audit.py`)
- [ ] `SCORING.md` updated if you changed scoring logic
- [ ] `DEPLOYMENT.md` updated if you changed env vars or infra

---

## 9. AI Agent Rules

All AI coding agents modifying this repository **must**:

1. Read `AI_AGENT_PROTOCOL.md` before making any changes.
2. Log every change to `logs/ai_audit_log.jsonl` using `engine/utils/ai_audit.log_ai_change()`.
3. Never commit from a corporate email address (guardrail enforced by pre-commit hook).
4. Run `pytest` before committing — never commit failing tests.
5. Update `SCORING.md` when changing any scoring logic in `engine/stock_scanner/`.
6. Record architectural decisions in `.agent-room/decisions.md`.
7. Record anti-patterns discovered in `.agent-room/anti-patterns.md`.
