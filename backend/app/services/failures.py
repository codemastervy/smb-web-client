"""Translating raw SMB errors into something worth showing a person.

This is a direct port of `BrowseFailure` from the native app, and it carries
the same responsibility: it is the single place where an errno or an SMB
status code becomes a sentence. Anything unrecognised keeps the underlying
description rather than being flattened into a useless "unknown error".

The two `suggests_*` flags are what let the failure modal put the *useful*
button first: a rejected password leads with Edit Connection, a timeout leads
with the recovery link.
"""
from __future__ import annotations

import errno
import socket
from dataclasses import dataclass
from typing import Any, Optional

# smbprotocol raises a family of typed exceptions; import defensively so the
# module is still usable (and testable) without the package installed.
try:
    from smbprotocol.exceptions import SMBException, SMBOSError  # type: ignore
except Exception:  # noqa: BLE001 - optional at import time
    SMBException = SMBOSError = ()  # type: ignore


KINDS = (
    "timed_out", "host_unreachable", "connection_refused",
    "authentication_failed", "share_not_found", "permission_denied",
    "not_found", "already_exists", "directory_not_empty", "out_of_space",
    "invalid_configuration", "cancelled", "too_large", "other",
)

_TITLES = {
    "timed_out": "Connection Timed Out",
    "host_unreachable": "Server Unreachable",
    "connection_refused": "Connection Refused",
    "authentication_failed": "Sign-In Failed",
    "share_not_found": "Share Not Found",
    "permission_denied": "Permission Denied",
    "not_found": "Not Found",
    "already_exists": "Item Already Exists",
    "directory_not_empty": "Folder Not Empty",
    "out_of_space": "Out of Space",
    "invalid_configuration": "Invalid Connection Details",
    "too_large": "File Too Large",
    "cancelled": "Cancelled",
    "other": "Couldn't Connect",
}

# Editing the connection is a plausible fix for these.
_SUGGESTS_EDIT = {"authentication_failed", "share_not_found",
                  "invalid_configuration", "connection_refused"}
# A VPN/tunnel is a plausible fix for these.
_SUGGESTS_RECOVERY = {"timed_out", "host_unreachable", "connection_refused"}

_ERRNO_KINDS = {
    errno.ETIMEDOUT: "timed_out",
    errno.EHOSTUNREACH: "host_unreachable",
    errno.EHOSTDOWN: "host_unreachable",
    errno.ENETUNREACH: "host_unreachable",
    errno.ENETDOWN: "host_unreachable",
    errno.ECONNREFUSED: "connection_refused",
    errno.EACCES: "authentication_failed",
    errno.EPERM: "authentication_failed",
    errno.ENOTCONN: "authentication_failed",
    errno.ECONNRESET: "authentication_failed",
    errno.ENODEV: "share_not_found",
    errno.ENXIO: "share_not_found",
    errno.EROFS: "permission_denied",
    errno.ENOENT: "not_found",
    errno.EEXIST: "already_exists",
    errno.ENOTEMPTY: "directory_not_empty",
    errno.ENOSPC: "out_of_space",
    errno.EDQUOT: "out_of_space",
    errno.EINVAL: "invalid_configuration",
    errno.ECANCELED: "cancelled",
}

# NT status codes, matched numerically.
#
# smbprotocol's SMBResponseException subclasses carry the raw status as
# `.status` (verified: LogonFailure -> 0xC000006D, AccessDenied -> 0xC0000022).
# Matching the number is exact; matching the message text is not, because the
# wording differs between exception classes and library versions. Names are
# kept in comments so this table can be read.
_STATUS_KINDS = {
    0xC000006D: "authentication_failed",   # STATUS_LOGON_FAILURE
    0xC000006E: "authentication_failed",   # STATUS_ACCOUNT_RESTRICTION
    0xC000006F: "authentication_failed",   # STATUS_INVALID_LOGON_HOURS
    0xC0000070: "authentication_failed",   # STATUS_INVALID_WORKSTATION
    0xC0000071: "authentication_failed",   # STATUS_PASSWORD_EXPIRED
    0xC0000072: "authentication_failed",   # STATUS_ACCOUNT_DISABLED
    0xC0000224: "authentication_failed",   # STATUS_PASSWORD_MUST_CHANGE
    0xC0000234: "authentication_failed",   # STATUS_ACCOUNT_LOCKED_OUT
    0xC000015B: "authentication_failed",   # STATUS_LOGON_TYPE_NOT_GRANTED

    0xC0000022: "permission_denied",       # STATUS_ACCESS_DENIED
    0xC0000043: "permission_denied",       # STATUS_SHARING_VIOLATION
    0xC00000A2: "permission_denied",       # STATUS_MEDIA_WRITE_PROTECTED

    0xC00000CC: "share_not_found",         # STATUS_BAD_NETWORK_NAME
    0xC00000BE: "share_not_found",         # STATUS_BAD_NETWORK_PATH
    0xC00000C9: "share_not_found",         # STATUS_NETWORK_NAME_DELETED

    0xC0000034: "not_found",               # STATUS_OBJECT_NAME_NOT_FOUND
    0xC000003A: "not_found",               # STATUS_OBJECT_PATH_NOT_FOUND
    0xC0000039: "not_found",               # STATUS_OBJECT_PATH_INVALID

    0xC0000035: "already_exists",          # STATUS_OBJECT_NAME_COLLISION
    0xC0000101: "directory_not_empty",     # STATUS_DIRECTORY_NOT_EMPTY
    0xC000007F: "out_of_space",            # STATUS_DISK_FULL

    0xC00000B5: "timed_out",               # STATUS_IO_TIMEOUT
    0xC0000236: "connection_refused",      # STATUS_CONNECTION_REFUSED
    0xC000020C: "host_unreachable",        # STATUS_CONNECTION_DISCONNECTED
    0xC000023A: "host_unreachable",        # STATUS_HOST_UNREACHABLE

    0xC00000BB: "invalid_configuration",   # STATUS_NOT_SUPPORTED
    0xC0000120: "cancelled",               # STATUS_CANCELLED
}

# Fallback for exceptions carrying no numeric status, keyed by class name.
_CLASS_KINDS = {
    "SMBAuthenticationError": "authentication_failed",
    "LogonFailure": "authentication_failed",
    "AccessDenied": "permission_denied",
    "BadNetworkName": "share_not_found",
    "NotFound": "not_found",
    "ObjectNameNotFound": "not_found",
    "ObjectNameCollision": "already_exists",
    "DirectoryNotEmpty": "directory_not_empty",
    "DiskFull": "out_of_space",
    "SMBConnectionClosed": "host_unreachable",
}


@dataclass
class Failure(Exception):
    kind: str
    target: str
    underlying: Optional[str] = None
    # Replaces the stock message for this kind. Used where the generic wording
    # would actively mislead -- an undecryptable stored password is not the
    # server "rejecting your credentials", and telling someone to check their
    # password would send them chasing the wrong thing.
    override_message: Optional[str] = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    # ---------------------------------------------------------------- text

    @property
    def title(self) -> str:
        return _TITLES.get(self.kind, _TITLES["other"])

    @property
    def message(self) -> str:
        """Names the target, because "timed out" alone doesn't tell anyone
        which machine went quiet."""
        if self.override_message:
            return self.override_message
        label = self.target or "the server"
        return {
            "timed_out":
                f"Couldn't reach {label} — the connection timed out. Check "
                f"that the server is powered on and on the same network, and "
                f"that any VPN or tunnel you need is connected.",
            "host_unreachable":
                f"{label} couldn't be found on the network. Check the address, "
                f"and whether you need a VPN or tunnel to reach it.",
            "connection_refused":
                f"{label} refused the connection. File sharing may be turned "
                f"off, or SMB may be listening on a different port.",
            "authentication_failed":
                f"{label} rejected the username or password. Check your "
                f"credentials and try again.",
            "share_not_found":
                f"{label} is reachable, but the share couldn't be opened. "
                f"Check the share name.",
            "permission_denied": f"You don't have permission to do that on {label}.",
            "not_found": f"That item no longer exists on {label}.",
            "already_exists": "An item with that name already exists.",
            "directory_not_empty": "That folder still has items in it.",
            "out_of_space": f"There isn't enough free space on {label}.",
            "invalid_configuration":
                f"The connection details for {label} aren't valid. Check the "
                f"host, port, and share name.",
            "cancelled": "The operation was cancelled.",
            "too_large":
                f"That file is larger than this server allows in a single "
                f"upload. Raise MAX_UPLOAD_BYTES if you need bigger uploads.",
        }.get(self.kind,
              f"Couldn't connect to {label}. {self.underlying}"
              if self.underlying else f"Couldn't connect to {label}.")

    @property
    def suggests_editing_connection(self) -> bool:
        return self.kind in _SUGGESTS_EDIT

    @property
    def suggests_recovery_app(self) -> bool:
        return self.kind in _SUGGESTS_RECOVERY

    @property
    def http_status(self) -> int:
        return {
            "authentication_failed": 401,
            "permission_denied": 403,
            "not_found": 404,
            "share_not_found": 404,
            "already_exists": 409,
            "directory_not_empty": 409,
            "out_of_space": 507,
            "invalid_configuration": 400,
            "timed_out": 504,
            "too_large": 413,
            "host_unreachable": 502,
            "connection_refused": 502,
        }.get(self.kind, 502)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "message": self.message,
            "target": self.target,
            "underlying": self.underlying,
            "suggests_editing_connection": self.suggests_editing_connection,
            "suggests_recovery_app": self.suggests_recovery_app,
        }


def from_exception(exc: BaseException, target: str) -> Failure:
    """Map anything smbprotocol (or the socket layer) can raise.

    Ordered most-authoritative first: the numeric NT status, then errno, then
    the exception class, and only then the message text.
    """
    if isinstance(exc, Failure):
        return exc

    text = str(exc) or exc.__class__.__name__

    # 1. The NT status code. Exact, and stable across library versions.
    status = getattr(exc, "status", None)
    if isinstance(status, int) and status in _STATUS_KINDS:
        return Failure(_STATUS_KINDS[status], target, text)

    # 2. errno, which SMBOSError carries instead of a status.
    code = getattr(exc, "errno", None)
    if isinstance(code, int) and code in _ERRNO_KINDS:
        return Failure(_ERRNO_KINDS[code], target, text)

    # 3. socket-level failures -- how an unreachable host actually shows up.
    if isinstance(exc, socket.timeout):
        return Failure("timed_out", target, text)
    if isinstance(exc, socket.gaierror):
        return Failure("host_unreachable", target, text)
    if isinstance(exc, ConnectionRefusedError):
        return Failure("connection_refused", target, text)
    if isinstance(exc, ConnectionResetError):
        return Failure("authentication_failed", target, text)

    # 4. the exception class, for the ones carrying neither status nor errno.
    kind = _CLASS_KINDS.get(type(exc).__name__)
    if kind:
        return Failure(kind, target, text)

    # 5. last resort: the message. Checked for an embedded STATUS_ name first,
    #    then for plain-language phrases.
    upper = text.upper()
    for code_value, mapped in _STATUS_KINDS.items():
        if f"({code_value})" in text or f"{code_value:#X}"[2:] in upper:
            return Failure(mapped, target, text)

    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return Failure("timed_out", target, text)
    if ("name or service not known" in lowered or "no address" in lowered
            or "unreachable" in lowered or "temporary failure in name" in lowered):
        return Failure("host_unreachable", target, text)
    if "refused" in lowered:
        return Failure("connection_refused", target, text)
    if ("password" in lowered or "credential" in lowered
            or "logon" in lowered or "authenticate" in lowered):
        return Failure("authentication_failed", target, text)

    return Failure("other", target, text)
