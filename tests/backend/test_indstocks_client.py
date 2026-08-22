"""Tests for engine/utils/indstocks_client.py.

Regression coverage for a real-world bug hit while testing the TOTP
auto-refresh path: TOTP setup keys are commonly *displayed* by dashboards in
space-separated groups (e.g. "ABCD EFGH IJKL...") for readability, and it's
easy to copy that formatting along with the secret. Base32 only allows
A-Z/2-7, so an un-sanitized secret makes pyotp raise an opaque
"Non-base32 digit found" error and the whole TOTP auto-refresh path silently
falls back to yfinance (the exact failure mode this module exists to avoid).

No live network calls.
"""

import pytest

from engine.utils import indstocks_client as ic


def test_generate_totp_code_strips_internal_whitespace(monkeypatch):
    # A secret copied straight from a dashboard's space-grouped display.
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "jbsw y3dp ehpk 3pxp")
    code = ic._generate_totp_code()
    assert code.isdigit()
    assert len(code) == 6


def test_generate_totp_code_strips_newlines_and_lowercase(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "\n  jbswy3dpehpk3pxp\t\n")
    code = ic._generate_totp_code()
    assert code.isdigit()
    assert len(code) == 6


def test_generate_totp_code_raises_clear_error_for_garbage(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "not-a-valid-secret!!")
    with pytest.raises(EnvironmentError, match="does not look like a valid base32"):
        ic._generate_totp_code()


def test_generate_totp_code_raises_clear_error_when_empty(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "   ")
    with pytest.raises(EnvironmentError, match="empty after stripping whitespace"):
        ic._generate_totp_code()
