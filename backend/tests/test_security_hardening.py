"""Regression tests for preview safety and input validation."""
import pytest
from pydantic import ValidationError

from app.models import Preferences, ServerCreate, ServerUpdate
from app.routes import files as files_routes


@pytest.mark.parametrize("media_type,expected", [
    ("image/png", True),
    ("video/mp4", True),
    ("audio/mpeg", True),
    ("application/pdf", True),
    ("text/plain", True),
    ("text/html", False),
    ("image/svg+xml", False),
    ("application/xhtml+xml", False),
    ("text/javascript", False),
    ("application/octet-stream", False),
])
def test_only_inert_types_are_served_inline(media_type, expected):
    assert files_routes._inline_safe(media_type) is expected


@pytest.mark.parametrize("host", ["nas.local", "192.168.1.10", "fe80::1", "[fe80::1]", "NAS-01"])
def test_ordinary_hosts_are_accepted(host):
    assert ServerCreate(host=host).host == host


@pytest.mark.parametrize("host", ["", "   ", "smb://nas", "nas\\share", "nas share", "nas\nevil", "a@b"])
def test_malformed_hosts_are_rejected(host):
    with pytest.raises(ValidationError):
        ServerCreate(host=host)
    if host.strip():
        with pytest.raises(ValidationError):
            ServerUpdate(host=host)


def test_share_name_cannot_smuggle_a_path():
    assert ServerCreate(host="nas", shareName="/Documents/").share_name == "Documents"
    for bad in ["Documents\\..\\C$", "a/b"]:
        with pytest.raises(ValidationError):
            ServerCreate(host="nas", shareName=bad)
        with pytest.raises(ValidationError):
            ServerUpdate(shareName=bad)


def test_update_port_is_range_checked():
    with pytest.raises(ValidationError):
        ServerUpdate(port=70000)
    assert ServerUpdate(port=445).port == 445


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "//evil"])
def test_recovery_link_must_be_http(url):
    with pytest.raises(ValidationError):
        Preferences(recoveryLinkUrl=url)


def test_recovery_link_accepts_http_and_empty():
    assert Preferences(recoveryLinkUrl="https://router.lan/wol").recovery_link_url
    assert Preferences().recovery_link_url == ""
