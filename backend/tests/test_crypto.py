"""Credential encryption at rest."""
import importlib

import pytest


@pytest.fixture()
def crypto(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "an-admin-password")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config
    importlib.reload(app.config)
    import app.crypto
    importlib.reload(app.crypto)
    return app.crypto


def test_round_trip(crypto):
    assert crypto.decrypt(crypto.encrypt("hunter2")) == "hunter2"


def test_ciphertext_does_not_contain_the_plaintext(crypto):
    token = crypto.encrypt("SuperSecret123")
    assert "SuperSecret123" not in token


def test_two_encryptions_differ(crypto):
    """Fernet includes a random IV, so identical inputs must not collide --
    otherwise equal ciphertexts would reveal equal passwords."""
    assert crypto.encrypt("same") != crypto.encrypt("same")


def test_empty_password_encrypts_to_nothing(crypto):
    assert crypto.encrypt("") is None
    assert crypto.decrypt(None) is None


def test_a_changed_admin_password_cannot_decrypt(tmp_path, monkeypatch):
    """The documented consequence of deriving the key from ADMIN_PASSWORD.

    Decryption must fail cleanly (None) rather than raise, so the app can say
    "enter the password again" instead of crashing.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_PASSWORD", "first-password")
    import app.config, app.crypto
    importlib.reload(app.config); importlib.reload(app.crypto)
    token = app.crypto.encrypt("smb-password")

    monkeypatch.setenv("ADMIN_PASSWORD", "second-password")
    importlib.reload(app.config); importlib.reload(app.crypto)
    assert app.crypto.decrypt(token) is None


def test_no_admin_password_means_no_encryption(tmp_path, monkeypatch):
    """Refuse rather than 'encrypt' with a constant, which would be worse than
    plaintext because it looks safe."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setenv("SESSION_SECRET", "")
    import app.config, app.crypto
    importlib.reload(app.config); importlib.reload(app.crypto)
    assert app.crypto.available() is False
    assert app.crypto.encrypt("anything") is None
