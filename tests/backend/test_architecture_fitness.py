"""LUNA MISSES CLOSEOUT Epic 14: architecture fitness tests.

A small number of high-value invariant checks derived from real rules this
repo already states (CLAUDE.md, engine/CLAUDE.md) and from bugs already
seen — not a speculative rulebook. Each test here fails loudly the moment
the invariant it protects is violated, rather than relying on someone
noticing in review.

Deliberately narrow in scope: `engine/*/logic.py` modules (stock_scanner,
reit_invits, commodities, mf_lab, options_algo, us_investing) still import
yfinance directly in several places today — pre-existing, documented
technical debt (see market_data_provider.py's own `record_ohlcv_served`
docstring), not something this pass fixes or hides. The invariant checked
here is the one that is actually true today: routers never do this, since
routers are the newer, thinner layer this rule was written to keep clean
going forward.
"""

import ast
import os

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROUTERS_DIR = os.path.join(REPO_ROOT, "engine", "routers")


def _router_files():
    return sorted(
        os.path.join(ROUTERS_DIR, name)
        for name in os.listdir(ROUTERS_DIR)
        if name.endswith(".py") and not name.startswith("__")
    )


def _top_level_module_imports(path):
    """Module names imported at any point in the file (import X / import X.Y
    / from X import Y) — deliberately not limited to module-top-level import
    statements, since engine/routers/*.py commonly does lazy `from
    utils.market_data_provider import get_ohlcv` inside a function body."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_routers_never_import_yfinance_directly():
    """engine/CLAUDE.md: 'Do not import yfinance directly in routers or
    scanner logic.' All market data must go through market_data_provider.py
    so provider selection, fallback, and call-count logging stay in one
    place. Violated once already (this is exactly the class of thing that
    slips in unnoticed) — this test makes it a hard failure instead of a
    hoped-for convention."""
    offenders = [
        path for path in _router_files() if "yfinance" in _top_level_module_imports(path)
    ]
    assert not offenders, (
        "engine/routers/*.py must never import yfinance directly — go through "
        f"utils.market_data_provider instead. Offending files: {offenders}"
    )


def test_routers_never_instantiate_indstocks_client_directly():
    """Same rule, the other named provider: 'Do not call INDstocksClient
    directly in routers or scanner logic' (engine/CLAUDE.md). INDstocksClient
    itself is only ever imported by market_data_provider.py and its own
    tests/instruments_cache — never by a router module."""
    offenders = [
        path
        for path in _router_files()
        if "indstocks_client" in _top_level_module_imports(path)
    ]
    assert not offenders, (
        "engine/routers/*.py must never import indstocks_client directly — go "
        f"through utils.market_data_provider instead. Offending files: {offenders}"
    )
