"""FORTRESS-H3: production security hardening tests.

Covers utils/security_config.py's is_production_environment(),
validate_jwt_secret(), validate_admin_password(), validate_cors_origins(),
and the centralized validate_security_configuration(). No real
provider/broker credentials are required — every test uses synthetic
secret values.

Scenario labels below (A-I) match the FORTRESS-H3 story spec.
"""
import pytest
from utils.security_config import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_JWT_SECRET,
    is_production_environment,
    validate_admin_password,
    validate_cors_origins,
    validate_jwt_secret,
    validate_security_configuration,
    validate_staging_database_isolation,
)

# ── is_production_environment(): the single production-mode signal ──────


def test_is_production_environment_false_for_sqlite(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "sqlite")
    assert is_production_environment() is False


def test_is_production_environment_false_for_local(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "local")
    assert is_production_environment() is False


def test_is_production_environment_true_when_unset(monkeypatch):
    monkeypatch.delenv("FORTRESS_DB_BACKEND", raising=False)
    assert is_production_environment() is True


def test_is_production_environment_true_for_neon(monkeypatch):
    monkeypatch.setenv("FORTRESS_DB_BACKEND", "neon")
    assert is_production_environment() is True


# ── A/D: development mode + dev JWT secret → allowed ─────────────────────


def test_A_dev_mode_with_default_jwt_secret_is_allowed(caplog):
    # validate_security_configuration(production=False) must never raise,
    # regardless of secret value — dev keeps its convenient defaults.
    validate_security_configuration(
        jwt_secret=DEFAULT_JWT_SECRET,
        admin_password=DEFAULT_ADMIN_PASSWORD,
        cors_origins=["http://localhost:3000"],
        production=False,
    )  # must not raise


def test_D_production_with_secure_jwt_secret_passes():
    validate_jwt_secret("a" * 64)  # must not raise
    validate_security_configuration(
        jwt_secret="a" * 64,
        admin_password="a-genuinely-random-admin-password-999",
        cors_origins=["https://app.example.com"],
        production=True,
    )  # must not raise


# ── B: production + default JWT secret → fails ───────────────────────────


def test_B_production_default_jwt_secret_fails():
    with pytest.raises(RuntimeError, match="FORTRESS_JWT_SECRET"):
        validate_jwt_secret(DEFAULT_JWT_SECRET)


def test_B_production_generic_placeholder_jwt_secret_fails():
    for placeholder in ("changeme", "change-me", "secret", "your-secret-key"):
        with pytest.raises(RuntimeError):
            validate_jwt_secret(placeholder)


# ── C: production + missing JWT secret → fails ───────────────────────────


def test_C_production_missing_jwt_secret_fails():
    with pytest.raises(RuntimeError, match="FORTRESS_JWT_SECRET"):
        validate_jwt_secret(None)


def test_C_production_blank_jwt_secret_fails():
    with pytest.raises(RuntimeError):
        validate_jwt_secret("   ")
    with pytest.raises(RuntimeError):
        validate_jwt_secret("")


# ── E: production + default app password → fails ────────────────────────


def test_E_production_default_admin_password_fails():
    with pytest.raises(RuntimeError, match="FORTRESS_APP_PASSWORD"):
        validate_admin_password(DEFAULT_ADMIN_PASSWORD)


def test_E_production_generic_placeholder_password_fails():
    for placeholder in ("changeme", "password", "admin", "admin123"):
        with pytest.raises(RuntimeError):
            validate_admin_password(placeholder)


def test_E_production_missing_admin_password_fails():
    with pytest.raises(RuntimeError, match="FORTRESS_APP_PASSWORD"):
        validate_admin_password(None)
    with pytest.raises(RuntimeError):
        validate_admin_password("")


# ── F: production + secure app password → passes ────────────────────────


def test_F_production_secure_admin_password_passes():
    validate_admin_password("Xk9#mP2$vQ7!wR4z")  # must not raise


# ── G: secrets never appear in exception text ────────────────────────────


def test_G_jwt_secret_value_never_appears_in_exception_text():
    with pytest.raises(RuntimeError) as exc_info:
        validate_jwt_secret(DEFAULT_JWT_SECRET)
    assert DEFAULT_JWT_SECRET not in str(exc_info.value)


def test_G_admin_password_value_never_appears_in_exception_text():
    with pytest.raises(RuntimeError) as exc_info:
        validate_admin_password(DEFAULT_ADMIN_PASSWORD)
    assert DEFAULT_ADMIN_PASSWORD not in str(exc_info.value)


def test_G_validate_security_configuration_error_excludes_actual_values():
    with pytest.raises(RuntimeError) as exc_info:
        validate_security_configuration(
            jwt_secret="a-real-secret-that-happens-to-be-64-chars-long-xxxxxxxxxxxxxxx",
            admin_password=DEFAULT_ADMIN_PASSWORD,
            cors_origins=["https://app.example.com"],
            production=True,
        )
    message = str(exc_info.value)
    assert "a-real-secret-that-happens-to-be-64-chars-long" not in message
    assert DEFAULT_ADMIN_PASSWORD not in message


# ── H: CORS production configuration rejects wildcard ────────────────────


def test_H_production_wildcard_cors_origin_fails():
    with pytest.raises(RuntimeError, match="CORS"):
        validate_cors_origins(["*"])


def test_H_production_wildcard_among_other_origins_still_fails():
    with pytest.raises(RuntimeError, match="CORS"):
        validate_cors_origins(["https://app.example.com", "*"])


def test_H_production_specific_origins_pass():
    validate_cors_origins(["https://app.example.com", "https://admin.example.com"])  # must not raise


def test_H_localhost_default_origins_are_not_wildcards():
    # Sanity: the app's own unset-env default must never trip this check.
    validate_cors_origins(["http://localhost:3000", "http://127.0.0.1:3000"])  # must not raise


# ── Oracle staging database isolation ────────────────────────────────────


def test_staging_database_isolation_requires_production_markers():
    with pytest.raises(RuntimeError, match="FORTRESS_PRODUCTION_DB_MARKERS"):
        validate_staging_database_isolation(
            "staging",
            "postgresql://staging.example/staging_db",
            "",
        )


def test_staging_database_isolation_rejects_matching_production_marker():
    with pytest.raises(RuntimeError, match="production database marker"):
        validate_staging_database_isolation(
            "staging",
            "postgresql://prod-neon.example/fortress_prod",
            "prod-neon.example,fortress_prod",
        )


def test_staging_database_isolation_allows_separate_staging_database():
    validate_staging_database_isolation(
        "staging",
        "postgresql://staging-user:staging-credential@staging-neon.example/fortress_staging",
        "prod-neon.example,fortress_prod",
    )  # must not raise


def test_staging_database_isolation_is_inactive_outside_staging():
    validate_staging_database_isolation(
        "production",
        "postgresql://prod-neon.example/fortress_prod",
        "",
    )  # must not raise


# ── I: optional broker credentials remain optional ───────────────────────


def test_I_security_validation_does_not_require_broker_credentials(monkeypatch):
    """validate_security_configuration()/is_production_environment() must
    have no dependency on INDSTOCKS_*/broker env vars at all — broker
    functionality is optional and must not be forced on just to pass
    security validation."""
    for key in ("INDSTOCKS_TOKEN", "INDSTOCKS_CLIENT_ID", "INDSTOCKS_MPIN", "INDSTOCKS_TOTP_SECRET"):
        monkeypatch.delenv(key, raising=False)

    # Production validation succeeds with real JWT/password/CORS values
    # and zero broker credentials configured.
    validate_security_configuration(
        jwt_secret="a" * 64,
        admin_password="a-genuinely-random-admin-password-999",
        cors_origins=["https://app.example.com"],
        production=True,
    )  # must not raise


# ── validate_security_configuration: full integration of A-F ────────────


def test_production_validation_fails_on_jwt_before_checking_password():
    with pytest.raises(RuntimeError, match="FORTRESS_JWT_SECRET"):
        validate_security_configuration(
            jwt_secret=DEFAULT_JWT_SECRET,
            admin_password="this-is-fine-and-secure-999",
            cors_origins=["https://app.example.com"],
            production=True,
        )


def test_production_validation_fails_on_password_when_jwt_is_fine():
    with pytest.raises(RuntimeError, match="FORTRESS_APP_PASSWORD"):
        validate_security_configuration(
            jwt_secret="a" * 64,
            admin_password=DEFAULT_ADMIN_PASSWORD,
            cors_origins=["https://app.example.com"],
            production=True,
        )


def test_production_validation_fails_on_cors_when_secrets_are_fine():
    with pytest.raises(RuntimeError, match="CORS"):
        validate_security_configuration(
            jwt_secret="a" * 64,
            admin_password="a-genuinely-random-admin-password-999",
            cors_origins=["*"],
            production=True,
        )


def test_development_validation_never_raises_regardless_of_values(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="fortress.security"):
        validate_security_configuration(
            jwt_secret="",
            admin_password="",
            cors_origins=["*"],
            production=False,
        )  # must not raise, even with every value unsafe
    assert any("FORTRESS_JWT_SECRET" in r.message for r in caplog.records)
    assert any("FORTRESS_APP_PASSWORD" in r.message for r in caplog.records)
