"""Token encryption helpers for optional enhanced broker features."""

from cryptography.fernet import Fernet
from utils.security import _derive_fernet_key, _get_secret_seed


def get_token_fernet() -> Fernet:
    """Return the shared Fernet instance derived from configured Fortress secret."""
    return Fernet(_derive_fernet_key(_get_secret_seed()))


def encrypt_broker_token(token: str) -> str:
    if not token:
        return ""
    return get_token_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_broker_token(token_encrypted: str) -> str:
    if not token_encrypted:
        return ""
    return get_token_fernet().decrypt(token_encrypted.encode("utf-8")).decode("utf-8")
