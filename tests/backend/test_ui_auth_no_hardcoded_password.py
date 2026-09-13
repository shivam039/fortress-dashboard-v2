"""Regression test for a hardcoded-default-password bug found alongside
the LUNA MISSES CLOSEOUT Telegram-token incident (see
.agent-room/decisions.md): ui/components/auth.py's admin login previously
defaulted FORTRESS_APP_PASSWORD to the literal string "fortress123" when
unset, which also silently defeated its own "admin login disabled when
unconfigured" check (os.environ.get() with a non-empty default never
returns empty, so that branch could never trigger). Fixed to default to
"" so the disabled-login path is actually reachable.
"""

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clean_admin_password_env(monkeypatch):
    monkeypatch.delenv("FORTRESS_APP_PASSWORD", raising=False)
    monkeypatch.delenv("FORTRESS_APP_USERNAME", raising=False)


def test_admin_password_has_no_hardcoded_default():
    from ui.components import auth

    assert os.environ.get("FORTRESS_APP_PASSWORD") is None
    users = auth._configured_users()
    assert users["admin"]["password"] == ""


def test_authenticate_disables_admin_login_when_password_unset():
    from ui.components import auth

    with patch.object(auth, "st") as mock_st:
        result = auth.authenticate("admin", "fortress123")
    assert result is False
    mock_st.error.assert_called_once()


def test_authenticate_rejects_the_old_hardcoded_default_once_configured():
    from ui.components import auth

    os.environ["FORTRESS_APP_PASSWORD"] = "a-real-configured-password"
    try:
        with patch.object(auth, "st"):
            assert auth.authenticate("admin", "fortress123") is False
            assert auth.authenticate("admin", "a-real-configured-password") is True
    finally:
        del os.environ["FORTRESS_APP_PASSWORD"]
