"""FORTRESS-V4 / Blocker D: production database must fail closed.

V3 found FORTRESS_DB_BACKEND=neon with no valid DATABASE_URL silently fell
back to ephemeral local SQLite. validate_database_configuration() is the
fix — called once at app startup (engine/main.py), reusing H3's existing
production-mode convention (FORTRESS_DB_BACKEND not sqlite/local), never a
second env flag. No live network access: a real Postgres connection is
mocked at the create_engine/connect boundary for the "secure config
starts" case — clearly labeled below.
"""
import pytest
from utils.db import validate_database_configuration


def test_dev_sqlite_starts_normally(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "sqlite")
    validate_database_configuration()  # must not raise


def test_local_mode_starts_normally(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "local")
    validate_database_configuration()  # must not raise


def test_production_without_database_url_fails_startup(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "neon")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        validate_database_configuration()


def test_production_unset_backend_also_treated_as_production(monkeypatch):
    # Matches _can_use_neon()/is_production_environment()'s own convention:
    # unset FORTRESS_DB_BACKEND is production, not an implicit dev default.
    monkeypatch.delenv("FORTRESS_DB_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        validate_database_configuration()


def test_production_with_unreachable_database_fails_startup(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "neon")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:supersecretpassword@bad-host:5432/db")

    def fail_connect(*a, **k):
        raise ConnectionError("could not connect to server")

    monkeypatch.setattr("utils.db.create_engine", fail_connect)
    with pytest.raises(RuntimeError, match="unreachable"):
        validate_database_configuration()


def test_secrets_never_appear_in_the_raised_error(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "neon")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:supersecretpassword@bad-host:5432/db")

    def fail_connect(*a, **k):
        raise ConnectionError("postgresql://user:supersecretpassword@bad-host:5432/db is unreachable")

    monkeypatch.setattr("utils.db.create_engine", fail_connect)
    with pytest.raises(RuntimeError) as exc_info:
        validate_database_configuration()
    message = str(exc_info.value)
    assert "supersecretpassword" not in message
    assert "bad-host" not in message


def test_missing_database_url_error_never_echoes_env_value(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "neon")
    monkeypatch.setenv("DATABASE_URL", "")  # explicitly blank, not merely unset
    with pytest.raises(RuntimeError) as exc_info:
        validate_database_configuration()
    assert "DATABASE_URL" in str(exc_info.value)  # names the variable
    assert "postgresql://" not in str(exc_info.value)  # never echoes a value


# ── mocked-provider verification: real Postgres is unreachable in this
# sandbox, so create_engine/connect is mocked here — the app-startup
# integration path (validate_database_configuration itself, called from
# engine/main.py) is exercised for real. ──


def test_secure_production_config_starts_mocked_connection(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "neon")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@real-host:5432/db")

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            return None

    class _FakeEngine:
        def connect(self):
            return _FakeConn()

    monkeypatch.setattr("utils.db.create_engine", lambda *a, **k: _FakeEngine())
    validate_database_configuration()  # must not raise
