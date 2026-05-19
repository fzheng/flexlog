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


def test_bootstrap_state_recovery_when_db_is_plaintext_sqlite(tmp_path):
    """If encounters.db on disk has the SQLite plaintext magic header,
    the user is sitting on un-encrypted data from a legacy version —
    route them to recovery."""
    from flexlog.services.auth import bootstrap_state
    (tmp_path / "data").mkdir()
    # Plaintext SQLite magic is "SQLite format 3\x00"
    (tmp_path / "data" / "encounters.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    assert bootstrap_state(tmp_path) == "needs_recovery"


def test_bootstrap_state_recovery_on_db_read_oserror(tmp_path, monkeypatch):
    """Unreadable encounters.db (e.g. permission denied) should route to
    recovery, not crash."""
    from flexlog.services.auth import bootstrap_state
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "encounters.db").write_bytes(b"\x00" * 100)

    real_open = type(tmp_path).open
    def selective_open(self, *a, **kw):
        if "encounters.db" in str(self):
            raise PermissionError("simulated")
        return real_open(self, *a, **kw)
    from pathlib import Path
    monkeypatch.setattr(Path, "open", selective_open)
    assert bootstrap_state(tmp_path) == "needs_recovery"


def test_bootstrap_state_recovery_when_uploads_exist_but_no_kdf(tmp_path):
    """Orphaned plaintext data: uploads/ has files but no kdf_params.json
    and no encrypted DB. Treat as needs_recovery."""
    from flexlog.services.auth import bootstrap_state
    uploads = tmp_path / "uploads" / "ab" / "cd"
    uploads.mkdir(parents=True)
    (uploads / "abcd.jpg").write_bytes(b"some bytes")
    # No kdf_params.json, no encounters.db
    assert bootstrap_state(tmp_path) == "needs_recovery"
