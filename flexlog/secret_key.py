"""Load or generate the Flask SECRET_KEY for CSRF + session signing.

The key lives at $FLEXLOG_DATA_DIR/.secret_key with mode 0600. On first run
flexlog generates 32 random bytes (hex-encoded) and writes the file. On
subsequent runs the existing key is reused so CSRF tokens remain valid
across restarts.

This module is intentionally tiny: a single function with hard guards
around file permissions and emptiness. The path is supplied by the caller
(typically flexlog.paths.data_dir() / ".secret_key") so this module has no
dependency on flexlog.paths and can be unit-tested in isolation.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

# Hex token of 32 bytes = 64 chars; plenty for HMAC-SHA256 CSRF tokens.
_KEY_BYTES = 32


class SecretKeyError(RuntimeError):
    """Raised when the secret key file is unusable (bad permissions, empty, etc.)."""


def load_or_create_secret_key(path: Path) -> str:
    """Read the key at `path`, or generate one if missing.

    Hard rules:
      - If the file exists, its mode must be exactly 0600.
      - If the file exists and is empty after stripping whitespace, raise.
      - On generation, the file is written 0600 atomically.
    """
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise SecretKeyError(
                f"secret key file at {path} has permissions {oct(mode)}; expected 0600. "
                "Refusing to load. Run: chmod 600 <path>"
            )
        contents = path.read_text(encoding="utf-8").strip()
        if not contents:
            raise SecretKeyError(f"secret key file at {path} is empty")
        return contents
    # First-run generation. Delegate to the shared atomic-write helper
    # which uses a randomized tmp suffix — a fixed `.secret_key.tmp`
    # left over from a prior crash used to crash-loop the app on next
    # boot via FileExistsError on the O_EXCL create.
    from flexlog.paths import atomic_write_text

    new_key = secrets.token_hex(_KEY_BYTES)
    atomic_write_text(path, new_key, mode=0o600)
    return new_key
