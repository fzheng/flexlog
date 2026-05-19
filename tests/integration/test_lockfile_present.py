"""The hash-pinned lockfile must exist and contain hashes.

This is a tripwire — if someone deletes it or commits a non-hashed
version, the suite goes red and we see it before shipping."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_requirements_lock_exists():
    lock = REPO_ROOT / "requirements.lock"
    assert lock.exists(), (
        f"requirements.lock missing at {lock}. Regenerate via `make lock`."
    )


def test_requirements_lock_has_hashes():
    """Every non-comment, non-blank line that pins a version must be
    followed by at least one --hash=sha256:... line. We check the
    simplest invariant: the file contains many sha256 hash lines."""
    lock = (REPO_ROOT / "requirements.lock").read_text()
    hash_lines = [
        ln for ln in lock.splitlines()
        if ln.strip().startswith("--hash=sha256:")
    ]
    assert len(hash_lines) >= 10, (
        f"Expected ≥10 sha256 hash lines in requirements.lock, got "
        f"{len(hash_lines)}. Did you regenerate with --generate-hashes?"
    )


def test_requirements_lock_pins_flask():
    """Sanity: Flask is one of our explicit deps; it must be in the lock."""
    lock = (REPO_ROOT / "requirements.lock").read_text().lower()
    assert "flask==" in lock, "requirements.lock missing flask=="
