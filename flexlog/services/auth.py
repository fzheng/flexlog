"""Bootstrap state machine for the encryption-at-rest feature.

`bootstrap_state(data_dir)` returns one of three strings:
  * "needs_setup"     - fresh install, no password set, no data exists.
                        First GET / renders the set-password form.
  * "needs_recovery"  - plaintext data exists (legacy install OR partial
                        delete). Refuse to proceed; render the recovery
                        page with backup instructions.
  * "ready"           - kdf_params.json + encounters.db both exist. Run
                        the normal Google-clone login flow.

The decision is made from on-disk presence checks only; this function
does not read or decrypt anything.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

State = Literal["needs_setup", "needs_recovery", "ready"]

# Plaintext SQLite files start with this magic
_PLAINTEXT_SQLITE_MAGIC = b"SQLite format 3\x00"


def bootstrap_state(data_dir: Path) -> State:
    kdf_path = data_dir / "kdf_params.json"
    db_path = data_dir / "data" / "encounters.db"
    uploads_dir = data_dir / "uploads"
    legacy_env = data_dir / ".env"

    kdf_exists = kdf_path.exists()
    db_exists = db_path.exists()

    # Legacy v0.1.0 install: .env present -> recovery
    if legacy_env.exists():
        return "needs_recovery"

    # DB exists. Is it plaintext (legacy) or encrypted (ours)?
    if db_exists:
        try:
            with db_path.open("rb") as f:
                head = f.read(16)
            if head == _PLAINTEXT_SQLITE_MAGIC:
                return "needs_recovery"
        except OSError:
            return "needs_recovery"

    # Uploads dir has files but no encrypted DB -> orphaned plaintext data
    if uploads_dir.exists():
        for _ in uploads_dir.rglob("*"):
            if _.is_file():
                if not (kdf_exists and db_exists):
                    return "needs_recovery"
                break

    if kdf_exists and db_exists:
        return "ready"

    return "needs_setup"
