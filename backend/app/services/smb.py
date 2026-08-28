"""The SMB client itself.

This module is the only place that talks SMB. It is a *client*: it connects
out to file servers, and it never listens, never exports a share, and never
touches the container's own disks.

Sessions
--------
smbprotocol keeps a connection pool keyed by server name, so a session is
registered once per profile and reused. An idle reaper closes sessions that
have gone unused, so a NAS that spins its disks down is not held awake by a
browser tab nobody is looking at.

Paths
-----
The API speaks in POSIX-looking paths relative to the share root
(`/Documents/report.pdf`). They are converted to UNC (`\\\\host\\share\\...`)
here and nowhere else. Every path is checked for traversal before use -- a
saved profile pins the share, and a request must not be able to wander out of
it into `\\\\host\\C$`.
"""
from __future__ import annotations

import logging
import posixpath
import stat as stat_module
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import smbclient
from smbclient import path as smb_path
from smbclient._os import SMBDirEntry  # noqa: F401  (typing/documentation)

from ..config import SMB_ENCRYPT, SMB_IDLE_SECONDS, SMB_TIMEOUT
from . import servers
from .failures import Failure, from_exception

log = logging.getLogger(__name__)

_lock = threading.RLock()


@dataclass
class Session:
    server_id: str
    host: str
    port: int
    share: str
    username: str
    connected_at: float
    last_used: float = field(default_factory=time.monotonic)
    error: Optional[dict[str, Any]] = None


_sessions: dict[str, Session] = {}


# --------------------------------------------------------------------------
# Path handling
# --------------------------------------------------------------------------

def normalise(path: str) -> str:
    """Collapse a client path and refuse anything that escapes the share."""
    cleaned = (path or "/").replace("\\", "/")
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned

    parts: list[str] = []
    for segment in cleaned.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            # Refuse rather than pop: a request should never be *trying* to
            # climb out, and silently normalising hides a client bug or an
            # attempt to reach another share on the same host.
            raise Failure("permission_denied", "",
                          "path may not contain '..'")
        if "\x00" in segment:
            raise Failure("invalid_configuration", "", "path contains a null byte")
        parts.append(segment)
    return "/" + "/".join(parts)


def _unc(session: Session, path: str) -> str:
    relative = normalise(path).lstrip("/").replace("/", "\\")
    base = rf"\\{session.host}\{session.share}"
    return f"{base}\\{relative}" if relative else base


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------

def _register(host: str, port: int, username: str, password: str,
              domain: str) -> None:
    # smbprotocol wants the domain folded into the username when present.
    user = f"{domain}\\{username}" if domain and username else username

    kwargs: dict[str, Any] = {
        "username": user or None,
        "password": password or None,
        "port": port,
        "connection_timeout": SMB_TIMEOUT,
    }
    # Pass `encrypt` ONLY to turn encryption on. Passing encrypt=False against
    # a connection that has already negotiated raises
    #     ValueError: Cannot disable encryption on an already negotiated session
    # so a second register_session for the same host -- which happens on every
    # reconnect, and after the "Test" button has opened one -- would fail.
    # Omitting it leaves negotiation alone and makes re-registration idempotent.
    if SMB_ENCRYPT:
        kwargs["encrypt"] = True

    smbclient.register_session(host, **kwargs)


def connect(server_id: str, one_off_password: Optional[str] = None) -> Session:
    """Open (or reuse) a session for a saved profile."""
    profile = servers.raw(server_id)
    if not profile:
        raise Failure("invalid_configuration", "", "no such saved server")

    host = profile["host"]
    port = profile.get("port", 445)
    share = (profile.get("share_name") or "").strip("/\\")
    target = profile.get("name") or host

    if not share:
        raise Failure("invalid_configuration", target,
                      "no share name is set for this server")

    username, saved_password, domain = servers.credentials(server_id)
    password = one_off_password or saved_password or ""

    if profile.get("password_enc") and saved_password is None \
            and not one_off_password:
        # Stored but undecryptable: ADMIN_PASSWORD changed. Say so plainly
        # rather than presenting it as a rejected password.
        raise Failure(
            "authentication_failed", target,
            underlying="saved credential could not be decrypted with the "
                       "current ADMIN_PASSWORD",
            override_message=(
                f"The saved password for {target} can no longer be read. This "
                f"happens when ADMIN_PASSWORD changes, because the encryption "
                f"key is derived from it. Choose Edit Connection and enter the "
                f"password again — the server has not rejected anything."),
        )

    with _lock:
        existing = _sessions.get(server_id)
        if existing and existing.error is None:
            existing.last_used = time.monotonic()
            return existing

        try:
            _register(host, port, username, password, domain)
            # register_session proves the server accepted us, not that the
            # share is reachable. Open the share root so a wrong share name
            # surfaces here as share_not_found, and a share we may not touch
            # as permission_denied, instead of on the first listing.
            #
            # scandir, not isdir: isdir() catches errors internally and just
            # returns False, which would turn every one of those into the same
            # useless "not a directory".
            candidate = Session(server_id, host, port, share, username, time.time())
            next(iter(smbclient.scandir(_unc(candidate, "/"))), None)
        except Exception as exc:  # noqa: BLE001 - translated below
            failure = _as_share_failure(exc, target)
            log.info("connect to %s failed: %s (%s)", target, failure.kind,
                     failure.underlying)
            raise failure

        session = Session(server_id, host, port, share, username, time.time())
        _sessions[server_id] = session
        log.info("connected to %s as %s", target, username or "guest")
        return session


def require(server_id: str) -> Session:
    with _lock:
        session = _sessions.get(server_id)
    if session is None:
        # Reconnect transparently -- a browser refresh should not force the
        # user to click Connect again when credentials are saved.
        return connect(server_id)
    session.last_used = time.monotonic()
    return session


def disconnect(server_id: str) -> bool:
    with _lock:
        session = _sessions.pop(server_id, None)
    if session is None:
        return False
    try:
        smbclient.delete_session(session.host, port=session.port)
    except Exception as exc:  # noqa: BLE001
        log.debug("error closing session to %s: %s", session.host, exc)
    return True


def status(server_id: str) -> dict[str, Any]:
    with _lock:
        session = _sessions.get(server_id)
    if session is None:
        return {"state": "idle"}
    if session.error:
        return {"state": "failed", "failure": session.error}
    return {"state": "connected",
            "connectedAt": session.connected_at,
            "username": session.username}


def all_status() -> dict[str, dict[str, Any]]:
    return {sid: status(sid) for sid in
            [s["id"] for s in servers.list_servers()]}


def reap_idle() -> None:
    """Close sessions nobody has used for a while."""
    now = time.monotonic()
    stale = []
    with _lock:
        for sid, session in list(_sessions.items()):
            if now - session.last_used > SMB_IDLE_SECONDS:
                stale.append(sid)
    for sid in stale:
        log.info("closing idle session %s", sid)
        disconnect(sid)


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------

def _as_share_failure(exc: BaseException, target: str) -> Failure:
    """Translate an error raised while opening the SHARE ROOT.

    Context changes the right message. A server that answers
    STATUS_OBJECT_NAME_NOT_FOUND for `\\\\host\\Typo` means "no such share",
    not "that file is gone" -- and the useful action is Edit Connection, so
    the generic not_found is remapped here where we know what was opened.
    """
    failure = from_exception(exc, target)
    if failure.kind == "not_found":
        return Failure("share_not_found", target, failure.underlying)
    return failure


def _target(session: Session) -> str:
    profile = servers.raw(session.server_id) or {}
    return profile.get("name") or session.host


def _describe(entry, parent_virtual: str) -> dict[str, Any]:
    try:
        info = entry.stat()
        is_dir = entry.is_dir()
    except Exception:  # noqa: BLE001 - a vanished entry must not kill a listing
        return {}

    name = entry.name
    return {
        "name": name,
        "path": posixpath.join(parent_virtual, name),
        "isDir": is_dir,
        "size": None if is_dir else info.st_size,
        "modified": info.st_mtime,
        "created": getattr(info, "st_ctime", None),
        "hidden": name.startswith(".") or bool(
            getattr(info, "st_file_attributes", 0) & 0x2),
        "readOnly": bool(getattr(info, "st_file_attributes", 0) & 0x1),
    }


def listdir(server_id: str, path: str, show_hidden: bool = False
            ) -> dict[str, Any]:
    session = require(server_id)
    virtual = normalise(path)
    try:
        entries = []
        for entry in smbclient.scandir(_unc(session, virtual)):
            described = _describe(entry, virtual)
            if not described:
                continue
            if not show_hidden and described["hidden"]:
                continue
            entries.append(described)
    except Exception as exc:  # noqa: BLE001
        raise from_exception(exc, _target(session))

    return {"serverId": server_id, "path": virtual, "entries": entries}


def search(server_id: str, path: str, query: str, recursive: bool = False,
           show_hidden: bool = False, limit: int = 500) -> dict[str, Any]:
    """Filter the current folder, or walk the tree when recursive.

    Bounded by a result limit and a wall-clock deadline: a recursive search
    over a large share is a lot of round trips, and an unbounded one would
    hang the request.
    """
    session = require(server_id)
    virtual = normalise(path)
    needle = query.strip().lower()
    if not needle:
        return {"serverId": server_id, "path": virtual, "entries": [],
                "truncated": False}

    results: list[dict[str, Any]] = []
    truncated = False
    deadline = time.monotonic() + 25.0
    queue = [virtual]

    try:
        while queue:
            if time.monotonic() > deadline or len(results) >= limit:
                truncated = True
                break
            current = queue.pop(0)
            for entry in smbclient.scandir(_unc(session, current)):
                described = _describe(entry, current)
                if not described:
                    continue
                if not show_hidden and described["hidden"]:
                    continue
                if needle in described["name"].lower():
                    results.append(described)
                    if len(results) >= limit:
                        truncated = True
                        break
                if recursive and described["isDir"]:
                    queue.append(described["path"])
            if truncated:
                break
    except Exception as exc:  # noqa: BLE001
        raise from_exception(exc, _target(session))

    return {"serverId": server_id, "path": virtual, "entries": results,
            "truncated": truncated, "query": query}


def stat(server_id: str, path: str) -> dict[str, Any]:
    session = require(server_id)
    virtual = normalise(path)
    try:
        info = smbclient.stat(_unc(session, virtual))
        is_dir = stat_module.S_ISDIR(info.st_mode)
    except Exception as exc:  # noqa: BLE001
        raise from_exception(exc, _target(session))
    return {"path": virtual, "name": posixpath.basename(virtual),
            "isDir": is_dir, "size": None if is_dir else info.st_size,
            "modified": info.st_mtime}


def mkdir(server_id: str, parent: str, name: str) -> dict[str, Any]:
    _reject_bad_name(name)
    session = require(server_id)
    virtual = posixpath.join(normalise(parent), name)
    try:
        smbclient.mkdir(_unc(session, virtual))
    except Exception as exc:  # noqa: BLE001
        raise from_exception(exc, _target(session))
    return {"path": virtual, "name": name, "isDir": True}


def rename(server_id: str, path: str, new_name: str) -> dict[str, Any]:
    _reject_bad_name(new_name)
    session = require(server_id)
    source = normalise(path)
    destination = posixpath.join(posixpath.dirname(source), new_name)
    try:
        if smb_path.exists(_unc(session, destination)):
            raise Failure("already_exists", _target(session))
        smbclient.rename(_unc(session, source), _unc(session, destination))
    except Failure:
        raise
    except Exception as exc:  # noqa: BLE001
        raise from_exception(exc, _target(session))
    return {"path": destination, "name": new_name}


def _reject_bad_name(name: str) -> None:
    if not name or name in {".", ".."}:
        raise Failure("invalid_configuration", "", "invalid name")
    if any(c in name for c in '\\/:*?"<>|') or "\x00" in name:
        raise Failure("invalid_configuration", "",
                      'a name may not contain \\ / : * ? " < > |')


def unique_name(session: Session, directory: str, name: str) -> str:
    """`report.pdf` -> `report 2.pdf`, matching the native app's behaviour."""
    candidate = name
    counter = 2
    while smb_path.exists(_unc(session, posixpath.join(directory, candidate))):
        if "." in name:
            stem, _, suffix = name.rpartition(".")
            candidate = f"{stem} {counter}.{suffix}"
        else:
            candidate = f"{name} {counter}"
        counter += 1
    return candidate


def _copy_file(session: Session, source: str, destination: str) -> None:
    with smbclient.open_file(_unc(session, source), mode="rb") as src, \
            smbclient.open_file(_unc(session, destination), mode="wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)


def _copy_tree(session: Session, source: str, destination: str) -> None:
    smbclient.mkdir(_unc(session, destination))
    for entry in smbclient.scandir(_unc(session, source)):
        child_src = posixpath.join(source, entry.name)
        child_dst = posixpath.join(destination, entry.name)
        if entry.is_dir():
            _copy_tree(session, child_src, child_dst)
        else:
            _copy_file(session, child_src, child_dst)


def transfer(server_id: str, sources: list[str], destination: str,
             move: bool) -> dict[str, Any]:
    """Server-side copy or move. Partial success is reported, not hidden."""
    session = require(server_id)
    dest_dir = normalise(destination)
    done, failed = [], []

    for source in sources:
        try:
            src = normalise(source)
            if move and dest_dir.startswith(src.rstrip("/") + "/"):
                raise Failure("invalid_configuration", _target(session),
                              "cannot move a folder into itself")
            name = posixpath.basename(src)
            target_name = unique_name(session, dest_dir, name)
            target = posixpath.join(dest_dir, target_name)

            if move:
                smbclient.rename(_unc(session, src), _unc(session, target))
            elif smb_path.isdir(_unc(session, src)):
                _copy_tree(session, src, target)
            else:
                _copy_file(session, src, target)
            done.append({"source": src, "name": target_name})
        except Failure as failure:
            failed.append({"source": source, "error": failure.message})
        except Exception as exc:  # noqa: BLE001
            failed.append({"source": source,
                           "error": from_exception(exc, _target(session)).message})

    return {"moved" if move else "copied": done, "failed": failed}


def delete(server_id: str, paths: list[str]) -> dict[str, Any]:
    session = require(server_id)
    deleted, failed = [], []

    for path in paths:
        try:
            virtual = normalise(path)
            if virtual == "/":
                raise Failure("permission_denied", _target(session),
                              "refusing to delete the share root")
            unc = _unc(session, virtual)
            if smb_path.isdir(unc):
                _remove_tree(session, virtual)
            else:
                smbclient.remove(unc)
            deleted.append(virtual)
        except Failure as failure:
            failed.append({"path": path, "error": failure.message})
        except Exception as exc:  # noqa: BLE001
            failed.append({"path": path,
                           "error": from_exception(exc, _target(session)).message})

    return {"deleted": deleted, "failed": failed}


def _remove_tree(session: Session, path: str) -> None:
    """SMB rmdir requires an empty directory, so recurse depth-first."""
    for entry in smbclient.scandir(_unc(session, path)):
        child = posixpath.join(path, entry.name)
        if entry.is_dir():
            _remove_tree(session, child)
        else:
            smbclient.remove(_unc(session, child))
    smbclient.rmdir(_unc(session, path))


def read_file(server_id: str, path: str, chunk_size: int = 512 * 1024
              ) -> Iterator[bytes]:
    session = require(server_id)
    virtual = normalise(path)
    handle = smbclient.open_file(_unc(session, virtual), mode="rb")
    try:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        handle.close()


def write_file(server_id: str, parent: str, filename: str, stream,
               on_progress=None) -> dict[str, Any]:
    """Stream an upload straight through to the server.

    Written to a temporary name and renamed into place, so an interrupted
    upload never leaves a half-file that looks complete.
    """
    _reject_bad_name(filename)
    session = require(server_id)
    parent_dir = normalise(parent)
    final_name = unique_name(session, parent_dir, filename)
    temp_name = f".{final_name}.part"
    temp_path = posixpath.join(parent_dir, temp_name)
    final_path = posixpath.join(parent_dir, final_name)

    written = 0
    try:
        with smbclient.open_file(_unc(session, temp_path), mode="wb") as handle:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if on_progress:
                    on_progress(written)
        smbclient.rename(_unc(session, temp_path), _unc(session, final_path))
    except Exception as exc:  # noqa: BLE001
        try:
            smbclient.remove(_unc(session, temp_path))
        except Exception:  # noqa: BLE001 - cleanup is best effort
            pass
        raise from_exception(exc, _target(session))

    return {"path": final_path, "name": final_name, "size": written}


def probe(host: str, port: int, username: str, password: str, domain: str,
          share: str) -> dict[str, Any]:
    """Test a connection without saving anything. Used by 'Test connection'.

    The session cache MUST be cleared for this host first. smbprotocol reuses
    an existing session for the same (server, user) and returns it *without
    re-authenticating*, so testing a deliberately wrong password against a host
    you are already connected to would report success. Verified: registering
    with a wrong password on top of a live session returns the cached Session
    object rather than raising LogonFailure.

    Clearing costs a reconnect for any profile already using this host, which
    `require()` performs transparently on the next request.
    """
    target = host
    _drop_host(host, port)
    try:
        _register(host, port, username, password, domain)
        if share:
            unc = rf"\\{host}\{share.strip('/')}"
            # isdir() swallows errors and returns False, so the share is
            # opened directly: a missing share must surface as share_not_found
            # and a forbidden one as permission_denied, not as a bare False.
            next(iter(smbclient.scandir(unc)), None)
        return {"ok": True}
    except Failure as failure:
        return {"ok": False, "failure": failure.to_dict()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "failure": _as_share_failure(exc, target).to_dict()}
    finally:
        # Never leave the tested credentials cached for this host.
        _drop_host(host, port)


def _drop_host(host: str, port: int) -> None:
    """Forget every cached session for a host, ours and smbprotocol's."""
    try:
        smbclient.delete_session(host, port=port)
    except Exception:  # noqa: BLE001 - nothing registered yet is fine
        pass
    with _lock:
        for sid, session in list(_sessions.items()):
            if session.host == host and session.port == port:
                _sessions.pop(sid, None)
