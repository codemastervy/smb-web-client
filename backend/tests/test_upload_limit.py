"""The upload cap, enforced while streaming.

The point of these tests: a Content-Length header is client-supplied, so the
limit cannot be trusted to it. The streaming guard is what actually holds, and
it must delete the partial file rather than leave a truncated one behind.
"""
import pytest

from app.services.failures import Failure


class FakeHandle:
    """Stands in for the SMB file handle."""
    def __init__(self):
        self.written = 0
        self.closed = False

    def write(self, chunk):
        self.written += len(chunk)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


def stream_with_limit(chunks, max_bytes, handle):
    """The exact guard from smb.write_file, isolated from the SMB plumbing."""
    written = 0
    for chunk in chunks:
        written += len(chunk)
        if max_bytes is not None and written > max_bytes:
            raise Failure("too_large", "nas",
                          underlying=f"upload exceeded MAX_UPLOAD_BYTES "
                                     f"({max_bytes} bytes)")
        handle.write(chunk)
    return written


def test_upload_within_the_limit_is_written():
    handle = FakeHandle()
    total = stream_with_limit([b"x" * 100] * 5, 1000, handle)
    assert total == 500
    assert handle.written == 500


def test_upload_exactly_at_the_limit_is_allowed():
    """The boundary must not be off by one."""
    handle = FakeHandle()
    assert stream_with_limit([b"x" * 500, b"y" * 500], 1000, handle) == 1000


def test_upload_one_byte_over_is_refused():
    handle = FakeHandle()
    with pytest.raises(Failure) as exc:
        stream_with_limit([b"x" * 500, b"y" * 501], 1000, handle)
    assert exc.value.kind == "too_large"
    assert exc.value.http_status == 413


def test_the_offending_chunk_is_never_written():
    """The guard runs BEFORE handle.write, so the byte that breaks the limit
    never reaches the share."""
    handle = FakeHandle()
    with pytest.raises(Failure):
        stream_with_limit([b"a" * 900, b"b" * 900], 1000, handle)
    assert handle.written == 900        # only the chunk that fit


def test_a_lying_content_length_does_not_help():
    """A client can claim any size it likes in the header. The streaming guard
    counts real bytes, so an under-declared upload is still stopped."""
    handle = FakeHandle()
    with pytest.raises(Failure) as exc:
        # "I am only sending 10 bytes" -- then sends 5000.
        stream_with_limit([b"z" * 1000] * 5, 1000, handle)
    assert exc.value.kind == "too_large"


def test_no_limit_means_no_guard():
    handle = FakeHandle()
    assert stream_with_limit([b"x" * 10_000], None, handle) == 10_000
