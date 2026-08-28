"""Encryption for stored SMB passwords.

Threat model, stated plainly so the guarantee is not overestimated
-----------------------------------------------------------------
The key is derived from ADMIN_PASSWORD with PBKDF2-HMAC-SHA256 (600k
iterations, per OWASP's current guidance) against a random salt kept in the
data volume. The key itself is never written to disk.

What this DOES protect:
  * the data volume at rest -- a stolen backup, a snapshot, a copied
    `servers.json`, or anyone who can read the file but not the process
    environment. Without the admin password those passwords are unreadable.

What this does NOT protect:
  * anyone who can read the container's environment (`docker inspect`, /proc,
    a shell in the container) has ADMIN_PASSWORD and can therefore derive the
    key. That is unavoidable for a service that must reconnect unattended.

The consequence, which the README repeats: **changing ADMIN_PASSWORD makes
saved SMB passwords undecryptable.** They are dropped and must be re-entered.
That is the correct behaviour for a key derived from a password -- silently
keeping them would mean the old password still unlocked them.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import ADMIN_PASSWORD, DATA_DIR

log = logging.getLogger(__name__)

SALT_PATH = DATA_DIR / ".credential_salt"
PBKDF2_ITERATIONS = 600_000

_fernet: Optional[Fernet] = None


def _salt() -> bytes:
    try:
        raw = SALT_PATH.read_bytes()
        if len(raw) >= 16:
            return raw
    except OSError:
        pass

    salt = secrets.token_bytes(32)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SALT_PATH.write_bytes(salt)
    try:
        os.chmod(SALT_PATH, 0o600)
    except OSError:
        pass
    log.info("generated a new credential salt")
    return salt


def _key() -> Optional[Fernet]:
    global _fernet
    if _fernet is not None:
        return _fernet
    secret = ADMIN_PASSWORD or os.environ.get("SESSION_SECRET", "")
    if not secret:
        # With nothing to derive from, refuse rather than "encrypting" with a
        # constant, which would be worse than plaintext because it looks safe.
        return None
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=_salt(), iterations=PBKDF2_ITERATIONS)
    _fernet = Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode())))
    return _fernet


def available() -> bool:
    return _key() is not None


def encrypt(plaintext: str) -> Optional[str]:
    """Returns the ciphertext, or None when no key can be derived."""
    if not plaintext:
        return None
    fernet = _key()
    if fernet is None:
        log.error("cannot encrypt: no ADMIN_PASSWORD to derive a key from")
        return None
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Returns the plaintext, or None if it cannot be decrypted.

    A None here after a password change is expected, not a bug: the key no
    longer matches. Callers treat it as "no saved password" and prompt.
    """
    if not ciphertext:
        return None
    fernet = _key()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        log.warning("a saved SMB password could not be decrypted -- "
                    "ADMIN_PASSWORD has probably changed since it was saved")
        return None
