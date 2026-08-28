"""Error translation.

These assertions matter beyond cosmetics: `suggests_editing_connection` and
`suggests_recovery_app` decide which button the full-screen failure modal puts
first, so getting the classification wrong means offering the wrong fix.

The NT status codes below are the real ones observed from a live Samba server
(smbprotocol exposes them as `.status`).
"""
import errno
import socket

import pytest

from app.services.failures import Failure, from_exception


class FakeSMBError(Exception):
    """Stands in for smbprotocol's SMBResponseException subclasses."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class FakeSMBOSError(OSError):
    pass


# --------------------------------------------------------------- statuses

@pytest.mark.parametrize("status, expected", [
    (0xC000006D, "authentication_failed"),   # STATUS_LOGON_FAILURE
    (0xC0000072, "authentication_failed"),   # STATUS_ACCOUNT_DISABLED
    (0xC0000234, "authentication_failed"),   # STATUS_ACCOUNT_LOCKED_OUT
    (0xC0000022, "permission_denied"),       # STATUS_ACCESS_DENIED
    (0xC00000CC, "share_not_found"),         # STATUS_BAD_NETWORK_NAME
    (0xC0000034, "not_found"),               # STATUS_OBJECT_NAME_NOT_FOUND
    (0xC0000035, "already_exists"),          # STATUS_OBJECT_NAME_COLLISION
    (0xC0000101, "directory_not_empty"),     # STATUS_DIRECTORY_NOT_EMPTY
    (0xC000007F, "out_of_space"),            # STATUS_DISK_FULL
    (0xC0000120, "cancelled"),               # STATUS_CANCELLED
])
def test_nt_status_is_mapped_numerically(status, expected):
    failure = from_exception(FakeSMBError(status, "server said no"), "nas")
    assert failure.kind == expected


def test_unknown_status_falls_through_to_other():
    failure = from_exception(FakeSMBError(0xC0000999, "weird"), "nas")
    assert failure.kind == "other"
    # The raw text must survive rather than being flattened away.
    assert failure.underlying == "weird"


# --------------------------------------------------------------- errno

@pytest.mark.parametrize("code, expected", [
    (errno.ETIMEDOUT, "timed_out"),
    (errno.EHOSTUNREACH, "host_unreachable"),
    (errno.ECONNREFUSED, "connection_refused"),
    (errno.ENOENT, "not_found"),
    (errno.EEXIST, "already_exists"),
    (errno.ENOSPC, "out_of_space"),
])
def test_errno_is_mapped(code, expected):
    exc = FakeSMBOSError(code, "os level")
    assert from_exception(exc, "nas").kind == expected


def test_socket_errors():
    assert from_exception(socket.timeout("slow"), "nas").kind == "timed_out"
    assert from_exception(socket.gaierror("no dns"), "nas").kind == "host_unreachable"
    assert from_exception(ConnectionRefusedError("nope"), "nas").kind == "connection_refused"


# --------------------------------------------------------------- buttons

def test_a_rejected_password_leads_with_edit_connection():
    failure = Failure("authentication_failed", "nas")
    assert failure.suggests_editing_connection is True
    assert failure.suggests_recovery_app is False


def test_a_timeout_leads_with_the_recovery_link():
    failure = Failure("timed_out", "nas")
    assert failure.suggests_recovery_app is True
    assert failure.suggests_editing_connection is False


def test_connection_refused_offers_both():
    """SMB may be off, or you may not be on the VPN -- both are plausible."""
    failure = Failure("connection_refused", "nas")
    assert failure.suggests_editing_connection is True
    assert failure.suggests_recovery_app is True


def test_permission_denied_offers_neither():
    """Nothing about editing the connection or a VPN fixes a permissions
    problem, so neither button should claim the prominent slot."""
    failure = Failure("permission_denied", "nas")
    assert failure.suggests_editing_connection is False
    assert failure.suggests_recovery_app is False


# --------------------------------------------------------------- messages

def test_the_message_names_the_server():
    """"Timed out" alone does not say which machine went quiet."""
    message = Failure("timed_out", "raspberrypi.local").message
    assert "raspberrypi.local" in message


def test_message_falls_back_when_target_is_empty():
    assert "the server" in Failure("timed_out", "").message


def test_other_keeps_the_underlying_description():
    failure = Failure("other", "nas", "libsmb2 said something specific")
    assert "libsmb2 said something specific" in failure.message


def test_http_status_mapping():
    assert Failure("authentication_failed", "n").http_status == 401
    assert Failure("permission_denied", "n").http_status == 403
    assert Failure("not_found", "n").http_status == 404
    assert Failure("already_exists", "n").http_status == 409
    assert Failure("out_of_space", "n").http_status == 507
    assert Failure("timed_out", "n").http_status == 504


def test_every_kind_has_a_title_and_message():
    from app.services.failures import KINDS
    for kind in KINDS:
        failure = Failure(kind, "nas")
        assert failure.title
        assert failure.message
        assert "None" not in failure.message
