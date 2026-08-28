"""Runtime configuration.

This app is an SMB *client*. It never serves SMB, never creates shares, and
never manages local disks -- see the README. The only state it keeps is the
list of servers you told it about.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Persistent state: saved server profiles (with encrypted credentials),
# preferences, and the session secret.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

# Access control for this web app itself. It is exposed on your LAN and holds
# credentials to your file server, so it is gated by default.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
AUTH_ENABLED = _env_bool("AUTH_ENABLED", True)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))

# SMB behaviour
SMB_TIMEOUT = int(os.environ.get("SMB_TIMEOUT", "20"))
SMB_ENCRYPT = _env_bool("SMB_ENCRYPT", False)
# Idle connections are torn down after this long, so a sleeping NAS is not
# held awake by a browser tab nobody is looking at.
SMB_IDLE_SECONDS = int(os.environ.get("SMB_IDLE_SECONDS", "300"))

# Upload guard rails
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(20 * 1024 ** 3)))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
