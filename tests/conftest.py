import os

import pytest
from streamlit.testing.v1 import AppTest

# Force SQLite only mode in tests to avoid database connection hangs
os.environ["FORTRESS_DB_BACKEND"] = "sqlite"


@pytest.fixture
def app():
    return AppTest.from_file("streamlit_app.py").run(timeout=20)
