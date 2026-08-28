"""Saved SMB server profiles.

Mirrors `ServerProfile` from the native app: only non-secret metadata is kept
in the clear, and the password is stored separately and encrypted, so anything
that serialises a profile for the API cannot leak it.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from .. import crypto
from ..models import DEFAULT_PORT
from .store import servers_store

log = logging.getLogger(__name__)


def _public(profile: dict[str, Any]) -> dict[str, Any]:
    """The shape sent to the browser. Never includes a password."""
    host = profile["host"]
    port = profile.get("port", DEFAULT_PORT)
    host_part = host if port == DEFAULT_PORT else f"{host}:{port}"
    share = profile.get("share_name") or ""

    return {
        "id": profile["id"],
        "name": profile.get("name") or host,
        "host": host,
        "port": port,
        "shareName": share,
        "username": profile.get("username", ""),
        "domain": profile.get("domain", ""),
        "saveCredentials": profile.get("save_credentials", True),
        # Distinguishes "no password saved" from "saved but undecryptable",
        # which is what happens after ADMIN_PASSWORD changes.
        "hasSavedPassword": bool(profile.get("password_enc")),
        "passwordRecoverable": (
            crypto.decrypt(profile.get("password_enc")) is not None
            if profile.get("password_enc") else True
        ),
        "subtitle": f"{host_part}/{share}" if share else host_part,
        "createdAt": profile.get("created_at"),
    }


def list_servers() -> list[dict[str, Any]]:
    data = servers_store.read()
    return [_public(p) for p in data.get("servers", [])]


def raw(server_id: str) -> Optional[dict[str, Any]]:
    for profile in servers_store.read().get("servers", []):
        if profile["id"] == server_id:
            return profile
    return None


def get(server_id: str) -> Optional[dict[str, Any]]:
    profile = raw(server_id)
    return _public(profile) if profile else None


def create(payload: dict[str, Any]) -> dict[str, Any]:
    profile = {
        "id": uuid.uuid4().hex[:12],
        "name": (payload.get("name") or "").strip(),
        "host": payload["host"].strip(),
        "port": payload.get("port", DEFAULT_PORT),
        "share_name": (payload.get("share_name") or "").strip().strip("/\\"),
        "username": (payload.get("username") or "").strip(),
        "domain": (payload.get("domain") or "").strip(),
        "save_credentials": bool(payload.get("save_credentials", True)),
        "created_at": time.time(),
    }

    password = payload.get("password") or ""
    if password and profile["save_credentials"]:
        profile["password_enc"] = crypto.encrypt(password)

    def mutate(data):
        data.setdefault("servers", []).append(profile)

    servers_store.update(mutate)
    log.info("added server profile %s (%s)", profile["id"], profile["host"])
    return _public(profile)


def update(server_id: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    field_map = {
        "name": "name", "host": "host", "port": "port",
        "share_name": "share_name", "username": "username", "domain": "domain",
        "save_credentials": "save_credentials",
    }

    def mutate(data):
        for profile in data.get("servers", []):
            if profile["id"] != server_id:
                continue
            for incoming, stored in field_map.items():
                value = payload.get(incoming)
                if value is None:
                    continue
                profile[stored] = value.strip() if isinstance(value, str) else value

            if payload.get("password"):
                profile["password_enc"] = crypto.encrypt(payload["password"])
            # Turning off "save credentials" must actually delete the stored
            # password, not merely stop using it.
            if profile.get("save_credentials") is False:
                profile.pop("password_enc", None)
            return

    servers_store.update(mutate)
    return get(server_id)


def delete(server_id: str) -> bool:
    existed = raw(server_id) is not None

    def mutate(data):
        data["servers"] = [p for p in data.get("servers", [])
                           if p["id"] != server_id]

    servers_store.update(mutate)
    return existed


def credentials(server_id: str) -> tuple[str, Optional[str], str]:
    """(username, password, domain) for a connection attempt."""
    profile = raw(server_id)
    if not profile:
        return "", None, ""
    return (
        profile.get("username", ""),
        crypto.decrypt(profile.get("password_enc")),
        profile.get("domain", ""),
    )
