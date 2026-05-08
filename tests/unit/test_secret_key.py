import os
import stat
from pathlib import Path

import pytest

from flexlog.secret_key import (
    SecretKeyError,
    load_or_create_secret_key,
)


def test_load_or_create_creates_when_missing(tmp_path):
    key_file = tmp_path / ".secret_key"
    assert not key_file.exists()
    secret = load_or_create_secret_key(key_file)
    assert isinstance(secret, str)
    assert len(secret) >= 32  # token_hex(32) = 64 hex chars
    assert key_file.exists()
    # Permissions are 0600
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_load_or_create_reuses_existing(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("existing-secret-value")
    key_file.chmod(0o600)
    got = load_or_create_secret_key(key_file)
    assert got == "existing-secret-value"


def test_load_or_create_rejects_world_readable(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("leaky-secret")
    key_file.chmod(0o644)  # group + world readable
    with pytest.raises(SecretKeyError, match="permissions"):
        load_or_create_secret_key(key_file)


def test_load_or_create_rejects_empty_file(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("")
    key_file.chmod(0o600)
    with pytest.raises(SecretKeyError, match="empty"):
        load_or_create_secret_key(key_file)


def test_load_or_create_strips_trailing_newline(tmp_path):
    """A user editing the file may leave a newline; tolerate it."""
    key_file = tmp_path / ".secret_key"
    key_file.write_text("user-edited-secret\n")
    key_file.chmod(0o600)
    got = load_or_create_secret_key(key_file)
    assert got == "user-edited-secret"


def test_two_invocations_yield_same_secret(tmp_path):
    """First call generates; second call reads what the first wrote."""
    key_file = tmp_path / ".secret_key"
    first = load_or_create_secret_key(key_file)
    second = load_or_create_secret_key(key_file)
    assert first == second


def test_generated_secrets_are_unique_per_directory(tmp_path):
    a = load_or_create_secret_key(tmp_path / "a.key")
    b = load_or_create_secret_key(tmp_path / "b.key")
    assert a != b


def test_load_or_create_cleanup_on_write_failure(tmp_path, monkeypatch):
    """If the write fails mid-stream, the .tmp file is unlinked."""
    key_file = tmp_path / ".secret_key"
    real_fdopen = os.fdopen

    def boom(*args, **kwargs):
        # Close the fd cleanly so the OS doesn't leak it, then raise
        f = real_fdopen(*args, **kwargs)
        f.close()
        raise OSError("disk full")

    monkeypatch.setattr("flexlog.secret_key.os.fdopen", boom)
    with pytest.raises(OSError, match="disk full"):
        load_or_create_secret_key(key_file)
    # The tmp file must not be left behind
    assert not (key_file.with_suffix(".secret_key.tmp")).exists()
