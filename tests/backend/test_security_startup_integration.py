"""FORTRESS-H3: proves the real startup wiring, not just the underlying
validator functions — that `import auth_utils` / `import routers.auth`
actually raises in production with an unsafe secret, and stays
warn-and-continue in development.

Each check runs in a fresh subprocess (not importlib.reload() in-process)
so a deliberately-failing import can never leave engine/auth_utils.py's
module-level SECRET_KEY in a half-initialized state for the rest of this
test session — every other test in this suite imports auth_utils exactly
once, normally, at collection time.
"""
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = str(Path(__file__).resolve().parents[2] / "engine")


def _run_import(module: str, env: dict) -> subprocess.CompletedProcess:
    full_env = {"PATH": "/usr/bin:/bin"}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ENGINE_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_B_production_default_jwt_secret_refuses_to_import(tmp_path):
    result = _run_import(
        "auth_utils",
        {
            "FORTRESS_DB_BACKEND": "neon",  # production
            "FORTRESS_JWT_SECRET": "fortress-dev-jwt-secret-change-in-production-2024",
        },
    )
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "FORTRESS_JWT_SECRET" in result.stderr
    assert "fortress-dev-jwt-secret-change-in-production-2024" not in result.stderr


def test_C_production_missing_jwt_secret_refuses_to_import():
    result = _run_import("auth_utils", {"FORTRESS_DB_BACKEND": "neon"})
    assert result.returncode != 0
    assert "FORTRESS_JWT_SECRET" in result.stderr


def test_D_production_secure_jwt_secret_imports_cleanly():
    result = _run_import(
        "auth_utils",
        {"FORTRESS_DB_BACKEND": "neon", "FORTRESS_JWT_SECRET": "x" * 64},
    )
    assert result.returncode == 0, result.stderr


def test_A_dev_mode_default_jwt_secret_imports_with_warning_only():
    result = _run_import("auth_utils", {"FORTRESS_DB_BACKEND": "sqlite"})
    assert result.returncode == 0, result.stderr


def test_E_production_default_admin_password_refuses_to_import():
    result = _run_import(
        "routers.auth",
        {
            "FORTRESS_DB_BACKEND": "neon",
            "FORTRESS_JWT_SECRET": "x" * 64,
            "FORTRESS_APP_PASSWORD": "fortress123",
        },
    )
    assert result.returncode != 0
    assert "FORTRESS_APP_PASSWORD" in result.stderr
    assert "fortress123" not in result.stderr


def test_F_production_secure_admin_password_imports_cleanly():
    result = _run_import(
        "routers.auth",
        {
            "FORTRESS_DB_BACKEND": "neon",
            "FORTRESS_JWT_SECRET": "x" * 64,
            "FORTRESS_APP_PASSWORD": "Xk9#mP2$vQ7!wR4z",
        },
    )
    assert result.returncode == 0, result.stderr
