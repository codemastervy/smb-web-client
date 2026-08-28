"""Path normalisation.

A saved profile pins one share. These checks are what stop a crafted request
wandering out of it -- into a sibling share, or into `\\\\host\\C$`.
"""
import pytest

from app.services.failures import Failure
from app.services.smb import normalise


@pytest.mark.parametrize("given, expected", [
    ("/", "/"),
    ("", "/"),
    ("Documents", "/Documents"),
    ("/Documents/", "/Documents"),
    ("/Documents//report.pdf", "/Documents/report.pdf"),
    ("/Documents/./report.pdf", "/Documents/report.pdf"),
    ("\\Documents\\report.pdf", "/Documents/report.pdf"),
    ("/a/b/c", "/a/b/c"),
])
def test_ordinary_paths_normalise(given, expected):
    assert normalise(given) == expected


@pytest.mark.parametrize("attempt", [
    "/..",
    "/../",
    "/../../etc",
    "/Documents/../../..",
    "..\\..\\Windows",
    "/a/../../b",
])
def test_dotdot_is_refused_not_collapsed(attempt):
    """Refused, deliberately, rather than normalised away.

    A request should never be *trying* to climb out of its share. Silently
    collapsing it would hide either a client bug or an attempt to reach
    another share on the same host.
    """
    with pytest.raises(Failure) as exc:
        normalise(attempt)
    assert exc.value.kind == "permission_denied"


def test_null_byte_is_refused():
    with pytest.raises(Failure):
        normalise("/Documents/re\x00port.pdf")


def test_unicode_and_spaces_survive():
    assert normalise("/Holiday Photos/café/naïve.txt") == "/Holiday Photos/café/naïve.txt"
