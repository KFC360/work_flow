from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.settings import get_settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"
COOKIE_NAME = "access_token"
CSRF_FORM_FIELD = "csrf_token"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return password_hash.verify(plain, hashed)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])


def csrf_token_for_jti(jti: str) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        f"csrf:{jti}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def verify_csrf(jti: str, submitted: str | None) -> bool:
    if not submitted:
        return False
    expected = csrf_token_for_jti(jti)
    return hmac.compare_digest(expected, submitted)


def verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
