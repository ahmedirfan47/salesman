import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _create_token(
    subject: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    token_type: str,
    expires_delta: timedelta,
    version: int = 0,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
        # the user's token_version: raising it on the user ends every older session
        "ver": version,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: uuid.UUID, tenant_id: uuid.UUID, role: str, version: int = 0) -> str:
    return _create_token(
        subject, tenant_id, role, "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), version,
    )


def create_refresh_token(subject: uuid.UUID, tenant_id: uuid.UUID, role: str, version: int = 0) -> str:
    return _create_token(
        subject, tenant_id, role, "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), version,
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])