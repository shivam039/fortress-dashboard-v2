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


def test_generate_totp_code_reports_which_characters_are_invalid(monkeypatch):
    # '0', '1', '8', '9' are never valid base32 digits — a very common
    # transcription mistake (visually confusable with O, I/l, B/g). Naming
    # them in the error saves a round trip of "which part is wrong?".
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "JBSW90DPEHPK3PXP")
    with pytest.raises(EnvironmentError) as exc_info:
        ic._generate_totp_code()
    message = str(exc_info.value)
    assert "'9'" in message
    assert "'0'" in message


def test_generate_totp_code_parses_a_full_otpauth_uri(monkeypatch):
    # Some dashboards show (or let you copy) the full QR-code provisioning
    # URI instead of the bare secret — handle that directly rather than
    # failing the base32 check on the surrounding "otpauth://..." text.
    monkeypatch.setenv(
        "INDSTOCKS_TOTP_SECRET",
        "otpauth://totp/INDstocks:me?secret=JBSWY3DPEHPK3PXP&issuer=INDstocks",
    )
    code = ic._generate_totp_code()
    assert code.isdigit()
    assert len(code) == 6


def test_generate_totp_code_raises_clear_error_for_malformed_otpauth_uri(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "otpauth://totp/not-a-real-uri")
    with pytest.raises(EnvironmentError, match="looks like a QR-code provisioning URI"):
        ic._generate_totp_code()
