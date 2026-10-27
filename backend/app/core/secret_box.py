"""Encrypt secrets before they are stored (ZATCA private keys and API secrets).

Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from SECRETS_KEY, or
from JWT_SECRET when SECRETS_KEY is not set. Changing the key makes stored
secrets unreadable, so set SECRETS_KEY once and keep it.
"""
import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    secret = settings.SECRETS_KEY or settings.JWT_SECRET
    key = base64.urlsafe_b64encode(hashlib.sha256(f"salesman-secrets:{secret}".encode()).digest())
    return Fernet(key)


def seal(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def open_(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("A stored secret can't be decrypted: SECRETS_KEY (or JWT_SECRET) has changed") from exc