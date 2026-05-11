"""Atomic read/write of the kdf_params.json sidecar file.

The file holds bootstrap secrets needed BEFORE the encrypted SQLCipher DB
can be opened: kek_salt, kek_nonce, wrapped_master_key, and Argon2id
parameters. None of these are useful without the user's password.

Mode 0600 is baked in at tmp-file creation time via
os.open(tmp, O_WRONLY|O_CREAT|O_EXCL, 0o600), so the file is
owner-only-readable from the moment it exists. O_EXCL refuses to clobber
an existing file at the random tmp path (symlink-race defense). A best-
effort chmod after os.replace covers the Windows case where O_EXCL
doesn't apply mode bits.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KdfParams:
    version: int
    kek_salt: bytes
    kek_nonce: bytes
    wrapped_master_key: bytes
    argon2_time: int
    argon2_memory_kib: int
    argon2_parallelism: int


class CorruptKdfParamsError(RuntimeError):
    """Raised when the kdf_params.json file exists but is unreadable or
    structurally invalid. The boot flow treats this as an unrecoverable
    state — refusing to start is safer than guessing."""


_REQUIRED = ("version", "kek_salt", "kek_nonce", "wrapped_master_key", "argon2")


def load_kdf_params(path: Path) -> KdfParams | None:
    """Read and validate. Returns None if the file doesn't exist; raises
    CorruptKdfParamsError on any structural problem."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CorruptKdfParamsError(f"kdf_params.json is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise CorruptKdfParamsError("kdf_params.json must be a JSON object")
    for k in _REQUIRED:
        if k not in data:
            raise CorruptKdfParamsError(f"kdf_params.json missing key: {k!r}")
    try:
        argon = data["argon2"]
        return KdfParams(
            version=int(data["version"]),
            kek_salt=bytes.fromhex(data["kek_salt"]),
            kek_nonce=bytes.fromhex(data["kek_nonce"]),
            wrapped_master_key=bytes.fromhex(data["wrapped_master_key"]),
            argon2_time=int(argon["time"]),
            argon2_memory_kib=int(argon["mem_kib"]),
            argon2_parallelism=int(argon["parallelism"]),
        )
    except (ValueError, KeyError, TypeError) as e:
        raise CorruptKdfParamsError(f"kdf_params.json has invalid field shape: {e}") from e


def write_kdf_params(path: Path, params: KdfParams) -> None:
    """Atomically write `params` to `path` with mode 0o600 baked in.

    The tmp file is created via os.open(..., O_WRONLY|O_CREAT|O_EXCL, 0o600)
    — the explicit mode arg (combined with the usual umask, which has
    no bits set for 0o600 anyway) guarantees the file is owner-only-
    readable from the moment it exists. O_EXCL refuses to clobber an
    existing tmp file at the random name (symlink-race defense).

    After fsync, os.replace atomically swaps the tmp over the live
    file. A best-effort chmod after the rename guards against the
    Windows case where O_EXCL doesn't apply mode bits.
    """
    payload = {
        "version": params.version,
        "kek_salt": params.kek_salt.hex(),
        "kek_nonce": params.kek_nonce.hex(),
        "wrapped_master_key": params.wrapped_master_key.hex(),
        "argon2": {
            "time": params.argon2_time,
            "mem_kib": params.argon2_memory_kib,
            "parallelism": params.argon2_parallelism,
        },
    }
    tmp_name = f".{path.name}.tmp.{secrets.token_hex(8)}"
    tmp = path.parent / tmp_name
    try:
        fd = os.open(
            tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        # Belt + braces: re-apply 0600 after rename. Most platforms keep
        # the source mode through os.replace, but Windows preserves the
        # target's pre-existing mode.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
