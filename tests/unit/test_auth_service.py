"""Unit tests for the bootstrap state machine."""
from __future__ import annotations

from flexlog.services.auth import bootstrap_state


def _empty(tmp_path):
    """An empty data dir."""
    return tmp_path


def test_state_needs_setup_when_data_dir_empty(tmp_path):
    assert bootstrap_state(tmp_path) == "needs_setup"


def test_state_needs_recovery_when_plaintext_db_exists(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "encounters.db").write_bytes(b"SQLite format 3\x00")  # plaintext magic
    assert bootstrap_state(tmp_path) == "needs_recovery"


def test_state_needs_recovery_when_uploads_has_files_but_no_db(tmp_path):
    (tmp_path / "uploads" / "aa" / "bb").mkdir(parents=True)
    (tmp_path / "uploads" / "aa" / "bb" / "abc.jpg").write_bytes(b"\xff\xd8\xff")
    assert bootstrap_state(tmp_path) == "needs_recovery"


def test_state_needs_recovery_when_legacy_env_exists(tmp_path):
    (tmp_path / ".env").write_text("FLEXLOG_ADMIN_PASSWORD_SHA512=abc\n")
    assert bootstrap_state(tmp_path) == "needs_recovery"


def test_state_ready_when_kdf_params_and_encrypted_db_exist(tmp_path):
    # Encrypted DB does NOT have SQLite plaintext magic; SQLCipher produces
    # opaque bytes. We fake it with random bytes.
    import os
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "encounters.db").write_bytes(os.urandom(4096))
    (tmp_path / "kdf_params.json").write_text("{}")  # contents don't matter for state check
    assert bootstrap_state(tmp_path) == "ready"
