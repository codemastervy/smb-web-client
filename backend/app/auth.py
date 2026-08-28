"""Access control for this web app.

Why this exists at all: the native app ran on your device, where the OS
protected its keychain. This runs as a server on your LAN, holding credentials
to your file server, reachable by anything that can route to the container --
a guest's phone, a smart TV, an IoT device. Unauthenticated, it would be a
file-server credential store with an open web UI in front of it.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import (ADMIN_PASSWORD, AUTH_ENABLED, SESSION_SECRET,
                     SESSION_TTL_SECONDS)
from .services.store import settings_store

log = logging.getLogger(__name__)

COOKIE_NAME = "smbweb_session"

_failures: dict[str, list[float]] = {}
_MAX_FAILURES = 8
_WINDOW = 300.0


def _secret() -> str:
    if SESSION_SECRET:
        return SESSION_SECRET
    data = settings_store.read()
    secret = data.get("session_secret")
    if not secret:
        secret = secrets.token_urlsafe(48)
        data["session_secret"] = secret
        settings_store.write(data)
    return secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="smbweb-session")


def auth_configured() -> bool:
    return bool(ADMIN_PASSWORD)


def auth_required() -> bool:
    return AUTH_ENABLED and auth_configured()


def throttled(client: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _failures.get(client, []) if now - t < _WINDOW]
    _failures[client] = recent
    return len(recent) >= _MAX_FAILURES


def record_failure(client: str) -> None:
    _failures.setdefault(client, []).append(time.monotonic())


def clear_failures(client: str) -> None:
    _failures.pop(client, None)


def verify_password(candidate: str) -> bool:
    if not ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(
        hashlib.sha256(candidate.encode()).digest(),
        hashlib.sha256(ADMIN_PASSWORD.encode()).digest(),
    )


def issue_session(response: Response, secure: bool = False) -> None:
    token = _serializer().dumps({"sub": "admin", "iat": int(time.time())})
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS,
                        httponly=True, samesite="lax", secure=secure, path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def session_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        _serializer().loads(token, max_age=SESSION_TTL_SECONDS)
        return True
    except (BadSignature, SignatureExpired):
        return False


async def require_auth(
    smbweb_session: Optional[str] = Cookie(default=None),
) -> None:
    if not auth_required():
        return
    if not session_valid(smbweb_session):
        raise HTTPException(status_code=401, detail="authentication required")
