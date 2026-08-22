import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

# Force SQLite only mode in tests to avoid database connection hangs
os.environ["FORTRESS_DB_BACKEND"] = "sqlite"

# engine/main.py normally appends its own directory to sys.path at import
# time — that's what lets everything under engine/ (utils.db, stock_scanner.
# logic, routers.reit_invits, etc.) use bare "utils.X" / "routers.X" imports
# instead of "engine.utils.X". Bare imports are what actually works on
# Render, which deploys with Root Directory=engine (engine/ as the process's
# own working directory, with no "engine" package visible on sys.path at
# all) — an "engine.utils.X" import only ever worked by accident, when
# running from the repo root gave Python's implicit-namespace-package
# resolution something to find, and it always failed on the real deployment
# (see the "No module named 'engine'" INDstocks fetch failures this fixed).
#
# A test file that imports an engine/ submodule directly — e.g. `from
# engine.utils import market_data_provider` — without first importing
# engine.main never triggers that append itself, so its own bare-import
# monkeypatches (and the module's internal bare imports) fail with "No
# module named 'utils'". Whether that happens depended on pytest's file
# collection order (whichever test file imports engine.main first, if any,
# happens to fix it for every file collected after). Doing the append here,
# once, for every test session regardless of which files run or in what
# order, removes that order-dependence.
_ENGINE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine")
)
if _ENGINE_DIR not in sys.path:
    sys.path.append(_ENGINE_DIR)


@pytest.fixture
def app():
    return AppTest.from_file("streamlit_app.py").run(timeout=20)
