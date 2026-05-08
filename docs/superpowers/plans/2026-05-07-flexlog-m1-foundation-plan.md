# flexlog M1 Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the flexlog project skeleton — paths, config loader, hasher, app factory, base template with config-driven labels, dev runner, pytest scaffolding with the 85% coverage gate, and a placeholder dashboard route — so subsequent milestones (M2+) can plug domain models and blueprints into a working foundation.

**Architecture:** Local-only Flask 3.x app using the application factory pattern. No domain models in M1. All filesystem access goes through a sandboxed `paths.py`. Configuration is read once at startup from `$FLEXLOG_DATA_DIR/config.json` (with first-run bootstrap of a default file). User-facing labels reach templates via a context processor + a `ui` Jinja filter so no public-template wording is hardcoded. pytest with `pytest-cov --cov-fail-under=85` enforces the global coverage gate from day one.

**Tech Stack:** Python 3.11+, Flask 3.x, Jinja2, pytest, pytest-cov. (SQLAlchemy and Flask-WTF are deferred to M2 when the first models and POST forms appear.)

**Source spec:** `docs/superpowers/specs/2026-05-07-flexlog-design.md` §12 (M1).

---

## File structure

Files created in M1 (each with one clear responsibility):

| Path | Purpose |
|---|---|
| `pyproject.toml` | Project metadata, deps, console script entry point, pytest+coverage configuration |
| `.gitignore` | Standard Python ignores + `.coverage`, venv, etc. |
| `flexlog/__init__.py` | Empty package marker (carries `__version__`) |
| `flexlog/__main__.py` | Entry point for `python -m flexlog` and console script |
| `flexlog/app.py` | `create_app()` Flask factory; wires config + blueprints + filters + context processor |
| `flexlog/paths.py` | Sandboxed filesystem API: `data_dir()`, `db_path()`, `config_path()`, `uploads_dir()`, `tmp_uploads_dir()`, `resolve_file_key()`, `file_key_for()`, `ensure_layout()` |
| `flexlog/config_loader.py` | Loads + validates `config.json`; first-run bootstrap; exposes typed `Config` dataclass |
| `flexlog/hashing.py` | `sha256_hex_stream(reader)` — streaming SHA-256 over chunks |
| `flexlog/web/__init__.py` | Blueprint registry — `register_blueprints(app)` |
| `flexlog/web/home_bp.py` | Placeholder dashboard at `GET /` |
| `flexlog/web/filters.py` | `ui` Jinja filter + `inject_labels` context processor + `BUILTIN_UI_DEFAULTS` |
| `flexlog/templates/_base.html` | Base layout — page title, header with app/entity labels, content block |
| `flexlog/templates/home.html` | Placeholder dashboard — extends `_base.html` |
| `flexlog/static/css/main.css` | Minimal stylesheet (centered layout, typography defaults) |
| `tests/__init__.py` | Empty marker |
| `tests/conftest.py` | `tmp_data_dir`, `tmp_data_dir_no_config`, `app`, `client` fixtures |
| `tests/unit/__init__.py` | Empty marker |
| `tests/unit/test_hashing.py` | SHA-256 streaming tests |
| `tests/unit/test_paths.py` | env validation, child-dir creation, file-key API, sandboxing |
| `tests/unit/test_config_loader.py` | validation matrix, first-run bootstrap |
| `tests/unit/test_filters.py` | `ui` filter behavior + missing-key fallback |
| `tests/integration/__init__.py` | Empty marker |
| `tests/integration/test_app_factory.py` | startup error cases + happy path |
| `tests/integration/test_home_route.py` | placeholder dashboard renders with config-driven labels |
| `README.md` | Install, run, test instructions; `FLEXLOG_DATA_DIR` setup |

`flexlog/db/` and `flexlog/services/` directories are **not** created in M1 — M2 introduces them.

---

## Task 1: Project scaffolding + first module (hashing)

This task bootstraps the repo enough to run pytest with the coverage gate. We pair scaffolding with the smallest module so we have a real test from commit one — a project with no covered lines would fail the 85% gate.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `flexlog/__init__.py`
- Create: `flexlog/hashing.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_hashing.py`

- [ ] **Step 1.1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "flexlog"
version = "0.1.0"
description = "Local-only single-user 1v1 session journal"
requires-python = ">=3.11"
dependencies = [
    "Flask>=3.0,<4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[project.scripts]
flexlog = "flexlog.__main__:main"

[tool.setuptools.packages.find]
include = ["flexlog*"]

[tool.setuptools.package-data]
flexlog = ["templates/*.html", "static/**/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=flexlog --cov-report=term-missing --cov-fail-under=85 -ra"

[tool.coverage.run]
branch = false
source = ["flexlog"]

[tool.coverage.report]
show_missing = true
skip_covered = false
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.:",
    "raise NotImplementedError",
]
```

- [ ] **Step 1.2: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
*.pyo
*.egg-info/
build/
dist/
.coverage
.coverage.*
htmlcov/
.pytest_cache/
.venv/
venv/
.idea/
.vscode/
.DS_Store
```

- [ ] **Step 1.3: Create empty markers**

```bash
mkdir -p flexlog tests/unit tests/integration
```

Write `flexlog/__init__.py`:

```python
__version__ = "0.1.0"
```

Write `tests/__init__.py` and `tests/unit/__init__.py` and `tests/integration/__init__.py` as empty files.

- [ ] **Step 1.4: Write the failing hashing test**

`tests/unit/test_hashing.py`:

```python
import io

import pytest

from flexlog.hashing import sha256_hex_stream


def test_sha256_hex_stream_empty_input_returns_known_digest():
    digest = sha256_hex_stream(io.BytesIO(b""))
    # SHA-256 of empty input
    assert digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_hex_stream_short_input_returns_known_digest():
    digest = sha256_hex_stream(io.BytesIO(b"abc"))
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_hex_stream_chunks_match_single_call():
    data = b"flexlog test payload " * 1000  # ~21KB
    one_shot = sha256_hex_stream(io.BytesIO(data))
    chunked = sha256_hex_stream(io.BytesIO(data), chunk_size=64)
    assert one_shot == chunked


def test_sha256_hex_stream_does_not_load_full_buffer(tmp_path):
    # Write ~2 MB to a real file; verify streaming reads it without OOM-style
    # patterns by comparing to a known digest computed via stdlib hashlib.
    import hashlib

    payload = (b"x" * 1024) * 2048  # 2 MiB
    f = tmp_path / "big.bin"
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    with f.open("rb") as r:
        got = sha256_hex_stream(r)
    assert got == expected


def test_sha256_hex_stream_rejects_non_binary_reader():
    text_reader = io.StringIO("not bytes")
    with pytest.raises(TypeError):
        sha256_hex_stream(text_reader)  # type: ignore[arg-type]
```

- [ ] **Step 1.5: Install in editable mode and run the failing test**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/unit/test_hashing.py -v
```

Expected: tests fail with `ModuleNotFoundError: No module named 'flexlog.hashing'`.

- [ ] **Step 1.6: Implement `flexlog/hashing.py`**

```python
"""Streaming SHA-256 helper for content-addressed storage."""

from __future__ import annotations

import hashlib
from typing import BinaryIO

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def sha256_hex_stream(reader: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Compute SHA-256 over `reader` in chunks, returning the hex digest.

    The reader must be binary; calling this on a text stream raises TypeError.
    Reads to EOF and does not seek back. Caller is responsible for stream
    positioning before/after.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    h = hashlib.sha256()
    while True:
        chunk = reader.read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError(
                f"sha256_hex_stream requires a binary reader; got chunk of type {type(chunk).__name__}"
            )
        h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 1.7: Run the test and verify pass + coverage gate**

```bash
pytest -v
```

Expected: 5 passing tests; coverage report shows `flexlog/hashing.py` at 100%; overall coverage well above 85%; exit code 0.

- [ ] **Step 1.8: Commit**

```bash
git add pyproject.toml .gitignore flexlog/__init__.py flexlog/hashing.py \
        tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py \
        tests/unit/test_hashing.py
git commit -m "M1: scaffold project + add streaming SHA-256 hasher

- pyproject.toml with Flask 3.x dep + pytest-cov 85% gate
- streaming sha256_hex_stream() — chunked, binary-only, deterministic"
```

---

## Task 2: `paths.py` — env var resolution + child dirs

**Files:**
- Create: `flexlog/paths.py`
- Create: `tests/unit/test_paths.py`

- [ ] **Step 2.1: Write the failing test**

`tests/unit/test_paths.py`:

```python
import os
from pathlib import Path

import pytest

from flexlog import paths
from flexlog.paths import (
    DataDirError,
    config_path,
    data_dir,
    db_path,
    ensure_layout,
    tmp_uploads_dir,
    uploads_dir,
)


def test_data_dir_unset_raises(monkeypatch):
    monkeypatch.delenv("FLEXLOG_DATA_DIR", raising=False)
    with pytest.raises(DataDirError, match="FLEXLOG_DATA_DIR is not set"):
        data_dir()


def test_data_dir_empty_raises(monkeypatch):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", "")
    with pytest.raises(DataDirError, match="FLEXLOG_DATA_DIR is not set"):
        data_dir()


def test_data_dir_relative_raises(monkeypatch):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", "relative/path")
    with pytest.raises(DataDirError, match="must be an absolute path"):
        data_dir()


def test_data_dir_missing_raises(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(missing))
    with pytest.raises(DataDirError, match="does not exist"):
        data_dir()


def test_data_dir_not_a_directory_raises(monkeypatch, tmp_path):
    f = tmp_path / "not-a-dir"
    f.write_text("oops")
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(f))
    with pytest.raises(DataDirError, match="is not a directory"):
        data_dir()


def test_data_dir_unwritable_raises(monkeypatch, tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o500)  # read+execute only
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(d))
    try:
        with pytest.raises(DataDirError, match="not writable"):
            data_dir()
    finally:
        d.chmod(0o700)  # restore so tmp_path cleanup works


def test_data_dir_happy_returns_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    got = data_dir()
    assert got == tmp_path
    assert isinstance(got, Path)


def test_child_paths_are_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    assert db_path() == tmp_path / "data" / "encounters.db"
    assert config_path() == tmp_path / "config.json"
    assert uploads_dir() == tmp_path / "uploads"
    assert tmp_uploads_dir() == tmp_path / "uploads" / ".tmp"


def test_ensure_layout_creates_missing_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "uploads" / ".tmp").is_dir()


def test_ensure_layout_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    # Drop a sentinel file inside; second call must not wipe it.
    sentinel = tmp_path / "data" / "sentinel.txt"
    sentinel.write_text("keep me")
    ensure_layout()
    assert sentinel.read_text() == "keep me"
```

- [ ] **Step 2.2: Run to verify it fails**

```bash
pytest tests/unit/test_paths.py -v
```

Expected: `ImportError: cannot import name 'data_dir' from 'flexlog.paths'`.

- [ ] **Step 2.3: Implement `flexlog/paths.py` (env validation + child dirs only)**

```python
"""Sandboxed filesystem API for flexlog.

All disk I/O elsewhere in the app must go through this module so we have a
single place that:
  - validates the FLEXLOG_DATA_DIR environment variable at startup
  - resolves child paths under that directory
  - rejects file keys that try to escape the uploads/ root

The full file-key API (resolve_file_key, file_key_for) is added in Task 3.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "FLEXLOG_DATA_DIR"


class DataDirError(RuntimeError):
    """Raised when FLEXLOG_DATA_DIR is missing or unusable."""


def data_dir() -> Path:
    """Return the validated FLEXLOG_DATA_DIR as a Path.

    Raises DataDirError if the variable is unset, empty, relative, missing,
    not a directory, or not writable.
    """
    raw = os.environ.get(ENV_DATA_DIR, "").strip()
    if not raw:
        raise DataDirError(
            f"{ENV_DATA_DIR} is not set. Set it to an absolute path to a writable directory."
        )
    p = Path(raw)
    if not p.is_absolute():
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} must be an absolute path."
        )
    if not p.exists():
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} does not exist. Create the directory before running flexlog."
        )
    if not p.is_dir():
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} is not a directory."
        )
    if not os.access(p, os.W_OK):
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} is not writable by the current user."
        )
    return p


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "data" / "encounters.db"


def uploads_dir() -> Path:
    return data_dir() / "uploads"


def tmp_uploads_dir() -> Path:
    return uploads_dir() / ".tmp"


def ensure_layout() -> None:
    """Create the standard child directories if missing. Idempotent."""
    (data_dir() / "data").mkdir(parents=True, exist_ok=True)
    uploads_dir().mkdir(parents=True, exist_ok=True)
    tmp_uploads_dir().mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2.4: Run tests, verify pass + coverage**

```bash
pytest -v
```

Expected: all tests pass; coverage stays above 85%.

- [ ] **Step 2.5: Commit**

```bash
git add flexlog/paths.py tests/unit/test_paths.py
git commit -m "M1: add paths.data_dir validation + child-dir layout

Validates FLEXLOG_DATA_DIR (set, absolute, exists, dir, writable),
exposes db_path/config_path/uploads_dir/tmp_uploads_dir, and provides
idempotent ensure_layout()."
```

---

## Task 3: `paths.py` — sandboxed file-key API

Adds `resolve_file_key()` (the security-critical function) and `file_key_for()` to the same module.

**Files:**
- Modify: `flexlog/paths.py`
- Modify: `tests/unit/test_paths.py`

- [ ] **Step 3.1: Append failing tests to `tests/unit/test_paths.py`**

```python
# --- File-key API ---

import pytest

from flexlog.paths import FileKeyError, file_key_for, resolve_file_key

VALID_SHA = "abcdef0123456789" * 4  # 64 hex chars


def test_file_key_for_jpeg_returns_sharded_path():
    key = file_key_for(VALID_SHA, "image/jpeg")
    assert key == f"{VALID_SHA[0:2]}/{VALID_SHA[2:4]}/{VALID_SHA}.jpg"


def test_file_key_for_known_mimes():
    cases = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
    }
    for mime, ext in cases.items():
        key = file_key_for(VALID_SHA, mime)
        assert key.endswith(f".{ext}"), f"{mime} -> {key}"


def test_file_key_for_unknown_mime_raises():
    with pytest.raises(FileKeyError, match="unsupported mime"):
        file_key_for(VALID_SHA, "application/zip")


def test_file_key_for_short_hash_raises():
    with pytest.raises(FileKeyError, match="sha256"):
        file_key_for("abc", "image/jpeg")


def test_file_key_for_non_hex_hash_raises():
    bad = "g" * 64
    with pytest.raises(FileKeyError, match="sha256"):
        file_key_for(bad, "image/jpeg")


def test_resolve_file_key_inside_uploads(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    key = f"{VALID_SHA[0:2]}/{VALID_SHA[2:4]}/{VALID_SHA}.jpg"
    resolved = resolve_file_key(key)
    assert resolved == (tmp_path / "uploads" / key).resolve()


def test_resolve_file_key_traversal_with_dotdot_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    with pytest.raises(FileKeyError, match="escapes uploads"):
        resolve_file_key("../etc/passwd")


def test_resolve_file_key_absolute_path_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    with pytest.raises(FileKeyError, match="absolute"):
        resolve_file_key("/etc/passwd")


def test_resolve_file_key_symlink_escape_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")
    link = tmp_path / "uploads" / "escape"
    link.symlink_to(outside)
    with pytest.raises(FileKeyError, match="escapes uploads"):
        resolve_file_key("escape/secret.txt")


def test_resolve_file_key_empty_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    with pytest.raises(FileKeyError, match="empty"):
        resolve_file_key("")
```

- [ ] **Step 3.2: Run tests, verify the new ones fail**

```bash
pytest tests/unit/test_paths.py -v
```

Expected: existing tests still pass; new tests fail with `ImportError: cannot import name 'FileKeyError'`.

- [ ] **Step 3.3: Extend `flexlog/paths.py`**

Append after `ensure_layout()`:

```python
# --- File-key API ---

# MIME → extension allowlist. Must match spec §4.4.
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}

_HEX = set("0123456789abcdef")


class FileKeyError(ValueError):
    """Raised when a file key is malformed or escapes the uploads sandbox."""


def file_key_for(sha256_hex: str, mime_type: str) -> str:
    """Produce the canonical file key for a uniquely-identified upload.

    Layout: "<aa>/<bb>/<full-sha>.<ext>" where aa and bb are the first two
    hex byte-pairs of the SHA-256 digest. The extension is chosen from a
    fixed allowlist of MIME types.
    """
    if (
        not isinstance(sha256_hex, str)
        or len(sha256_hex) != 64
        or any(c not in _HEX for c in sha256_hex)
    ):
        raise FileKeyError(
            f"invalid sha256 digest: must be 64 lowercase hex chars, got {sha256_hex!r}"
        )
    ext = _MIME_TO_EXT.get(mime_type)
    if ext is None:
        raise FileKeyError(f"unsupported mime type: {mime_type!r}")
    return f"{sha256_hex[0:2]}/{sha256_hex[2:4]}/{sha256_hex}.{ext}"


def resolve_file_key(file_key: str) -> Path:
    """Resolve a file key to an absolute path under uploads/ — sandboxed.

    Raises FileKeyError if the key is empty, absolute, or resolves outside
    the uploads root (including via symlinks).
    """
    if not isinstance(file_key, str) or file_key == "":
        raise FileKeyError("file key is empty")
    if file_key.startswith("/") or (len(file_key) > 1 and file_key[1] == ":"):
        # Block POSIX-absolute and Windows-style absolute keys.
        raise FileKeyError(f"file key must be relative, got absolute: {file_key!r}")
    base = uploads_dir().resolve()
    candidate = (base / file_key).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise FileKeyError(
            f"file key {file_key!r} escapes uploads sandbox"
        ) from exc
    return candidate
```

- [ ] **Step 3.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all tests pass; coverage on `flexlog/paths.py` is 100%.

- [ ] **Step 3.5: Commit**

```bash
git add flexlog/paths.py tests/unit/test_paths.py
git commit -m "M1: add sandboxed file-key API to paths

file_key_for() produces canonical content-addressed keys from a SHA-256 +
MIME allowlist. resolve_file_key() rejects empty, absolute, traversal,
and symlink-escape inputs."
```

---

## Task 4: `config_loader.py` — schema + validation

Loads `config.json`, validates it against the schema in spec §6.2, and exposes a typed frozen `Config` dataclass. First-run bootstrap (writing the default config) comes in Task 5.

**Files:**
- Create: `flexlog/config_loader.py`
- Create: `tests/unit/test_config_loader.py`

- [ ] **Step 4.1: Write the failing test file**

`tests/unit/test_config_loader.py`:

```python
import json
from pathlib import Path

import pytest

from flexlog.config_loader import (
    AppLabels,
    Config,
    ConfigError,
    Limits,
    RatingDimension,
    load_config,
)


def _valid_config_dict() -> dict:
    return {
        "app": {
            "name": "Interview Log",
            "entity_singular": "Guest",
            "entity_plural": "Guests",
            "session_singular": "Interview",
            "session_plural": "Interviews",
        },
        "ratings": [
            {
                "id": "overall_quality",
                "label": "Overall Quality",
                "description": "General impression",
                "scale_min": 0,
                "scale_max": 5,
                "enabled": True,
            },
            {
                "id": "clarity",
                "label": "Clarity",
                "scale_min": 0,
                "scale_max": 5,
                "enabled": True,
            },
        ],
        "ui_strings": {
            "new_person": "New Guest",
            "empty_dashboard": "No guests yet.",
        },
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 10,
            "max_video_files_per_session": 10,
            "max_photo_files_per_session": 50,
            "max_upload_mb_per_file": 500,
        },
    }


def _write(tmp_path: Path, payload: dict | str) -> Path:
    p = tmp_path / "config.json"
    if isinstance(payload, str):
        p.write_text(payload)
    else:
        p.write_text(json.dumps(payload))
    return p


def test_load_config_happy_path(tmp_path):
    cfg_path = _write(tmp_path, _valid_config_dict())
    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert isinstance(cfg.app, AppLabels)
    assert cfg.app.name == "Interview Log"
    assert cfg.app.entity_singular == "Guest"
    assert isinstance(cfg.limits, Limits)
    assert cfg.limits.max_upload_mb_per_file == 500
    assert isinstance(cfg.ratings, tuple)
    assert all(isinstance(r, RatingDimension) for r in cfg.ratings)
    assert cfg.ratings[0].id == "overall_quality"
    assert cfg.ui_strings["new_person"] == "New Guest"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does-not-exist.json")


def test_load_config_malformed_json_raises(tmp_path):
    p = _write(tmp_path, "{ this is not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(p)


def test_load_config_top_level_must_be_object(tmp_path):
    p = _write(tmp_path, "[1, 2, 3]")
    with pytest.raises(ConfigError, match="must be a JSON object"):
        load_config(p)


def test_load_config_missing_app_section(tmp_path):
    d = _valid_config_dict()
    del d["app"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="app"):
        load_config(p)


def test_load_config_app_field_required(tmp_path):
    d = _valid_config_dict()
    del d["app"]["entity_singular"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="entity_singular"):
        load_config(p)


def test_load_config_app_field_must_be_nonempty_string(tmp_path):
    d = _valid_config_dict()
    d["app"]["entity_singular"] = ""
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="entity_singular"):
        load_config(p)


def test_load_config_too_many_enabled_ratings(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": f"r{i}", "label": f"R{i}", "scale_min": 0, "scale_max": 5, "enabled": True}
        for i in range(7)
    ]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="at most 6"):
        load_config(p)


def test_load_config_disabled_ratings_dont_count(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": f"r{i}", "label": f"R{i}", "scale_min": 0, "scale_max": 5, "enabled": True}
        for i in range(6)
    ] + [
        {"id": "extra", "label": "Extra", "scale_min": 0, "scale_max": 5, "enabled": False}
    ]
    p = _write(tmp_path, d)
    cfg = load_config(p)
    assert len(cfg.ratings) == 7  # all preserved; only enabled count is gated


def test_load_config_duplicate_rating_id(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": "dup", "label": "A", "scale_min": 0, "scale_max": 5, "enabled": True},
        {"id": "dup", "label": "B", "scale_min": 0, "scale_max": 5, "enabled": True},
    ]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="duplicate rating id"):
        load_config(p)


def test_load_config_rating_id_slug_shape(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["id"] = "Has Spaces"
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="rating id"):
        load_config(p)


def test_load_config_rating_scale_out_of_range(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["scale_max"] = 6
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="scale_max"):
        load_config(p)


def test_load_config_rating_scale_min_negative(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["scale_min"] = -1
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="scale_min"):
        load_config(p)


def test_load_config_collects_multiple_errors(tmp_path):
    d = _valid_config_dict()
    d["app"]["name"] = ""
    d["app"]["entity_singular"] = ""
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    msg = str(exc.value)
    assert "name" in msg
    assert "entity_singular" in msg


def test_load_config_limits_must_be_positive_ints(tmp_path):
    d = _valid_config_dict()
    d["limits"]["max_upload_mb_per_file"] = -10
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="max_upload_mb_per_file"):
        load_config(p)


def test_load_config_max_custom_rating_dimensions_capped_at_six(tmp_path):
    d = _valid_config_dict()
    d["limits"]["max_custom_rating_dimensions"] = 7
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="max_custom_rating_dimensions"):
        load_config(p)


def test_load_config_ui_strings_optional(tmp_path):
    d = _valid_config_dict()
    del d["ui_strings"]
    p = _write(tmp_path, d)
    cfg = load_config(p)
    assert cfg.ui_strings == {}
```

- [ ] **Step 4.2: Run failing tests**

```bash
pytest tests/unit/test_config_loader.py -v
```

Expected: import error from missing module.

- [ ] **Step 4.3: Implement `flexlog/config_loader.py` (validation only — no bootstrap yet)**

```python
"""Load and validate the user config.json from $FLEXLOG_DATA_DIR.

Loaded once at app startup; the resulting frozen Config object is stashed on
app.config["FLEXLOG"]. There is no runtime reload — users restart after
editing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_ENABLED_RATINGS = 6


class ConfigError(RuntimeError):
    """Raised when config.json is missing, malformed, or fails validation.

    The message lists every issue found (not just the first).
    """


@dataclass(frozen=True)
class AppLabels:
    name: str
    entity_singular: str
    entity_plural: str
    session_singular: str
    session_plural: str


@dataclass(frozen=True)
class RatingDimension:
    id: str
    label: str
    description: str | None
    scale_min: int
    scale_max: int
    enabled: bool


@dataclass(frozen=True)
class Limits:
    max_custom_rating_dimensions: int
    max_audio_files_per_session: int
    max_video_files_per_session: int
    max_photo_files_per_session: int
    max_upload_mb_per_file: int


@dataclass(frozen=True)
class Config:
    app: AppLabels
    ratings: tuple[RatingDimension, ...]
    ui_strings: dict[str, str]
    limits: Limits


def load_config(path: Path) -> Config:
    """Load and validate config.json. Raises ConfigError with full report."""
    if not path.exists():
        raise ConfigError(f"config.json not found at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json at {path} is not valid JSON: {exc.msg} (line {exc.lineno})") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config.json at {path} must be a JSON object at the top level")

    errors: list[str] = []
    app = _parse_app(raw.get("app"), errors)
    ratings = _parse_ratings(raw.get("ratings"), errors)
    ui_strings = _parse_ui_strings(raw.get("ui_strings"), errors)
    limits = _parse_limits(raw.get("limits"), errors)

    if errors:
        joined = "\n  - ".join(errors)
        raise ConfigError(f"config.json at {path} has validation errors:\n  - {joined}")

    # Type checker can't see that errors == [] => all parsers returned non-None.
    assert app is not None and ratings is not None and limits is not None
    return Config(app=app, ratings=ratings, ui_strings=ui_strings, limits=limits)


def _parse_app(value: Any, errors: list[str]) -> AppLabels | None:
    if not isinstance(value, dict):
        errors.append("`app` section is missing or not an object")
        return None
    fields = ("name", "entity_singular", "entity_plural", "session_singular", "session_plural")
    parsed: dict[str, str] = {}
    ok = True
    for f in fields:
        v = value.get(f)
        if not isinstance(v, str) or v.strip() == "":
            errors.append(f"`app.{f}` must be a non-empty string")
            ok = False
        else:
            parsed[f] = v
    if not ok:
        return None
    return AppLabels(**parsed)


def _parse_ratings(value: Any, errors: list[str]) -> tuple[RatingDimension, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        errors.append("`ratings` must be a list")
        return None
    out: list[RatingDimension] = []
    seen_ids: set[str] = set()
    enabled_count = 0
    for i, entry in enumerate(value):
        prefix = f"ratings[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        rid = entry.get("id")
        if not isinstance(rid, str) or not _SLUG_RE.match(rid):
            errors.append(f"{prefix}.id: rating id must be a slug-shaped string (lowercase, digits, underscore)")
            continue
        if rid in seen_ids:
            errors.append(f"{prefix}.id: duplicate rating id {rid!r}")
            continue
        seen_ids.add(rid)
        label = entry.get("label")
        if not isinstance(label, str) or label.strip() == "":
            errors.append(f"{prefix}.label must be a non-empty string")
            continue
        description = entry.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"{prefix}.description must be a string or omitted")
            continue
        scale_min = entry.get("scale_min")
        scale_max = entry.get("scale_max")
        if not isinstance(scale_min, int) or scale_min < 0:
            errors.append(f"{prefix}.scale_min must be an integer >= 0")
            continue
        if not isinstance(scale_max, int) or scale_max > 5 or scale_max <= scale_min:
            errors.append(f"{prefix}.scale_max must be an integer in (scale_min, 5]")
            continue
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{prefix}.enabled must be a boolean")
            continue
        if enabled:
            enabled_count += 1
        out.append(
            RatingDimension(
                id=rid,
                label=label,
                description=description,
                scale_min=scale_min,
                scale_max=scale_max,
                enabled=enabled,
            )
        )
    if enabled_count > _MAX_ENABLED_RATINGS:
        errors.append(
            f"at most {_MAX_ENABLED_RATINGS} enabled rating dimensions allowed; got {enabled_count}"
        )
    return tuple(out)


def _parse_ui_strings(value: Any, errors: list[str]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append("`ui_strings` must be an object of string→string")
        return {}
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            errors.append(f"`ui_strings` entry {k!r} must map a string key to a string value")
            continue
        out[k] = v
    return out


def _parse_limits(value: Any, errors: list[str]) -> Limits | None:
    if not isinstance(value, dict):
        errors.append("`limits` section is missing or not an object")
        return None
    fields = (
        "max_custom_rating_dimensions",
        "max_audio_files_per_session",
        "max_video_files_per_session",
        "max_photo_files_per_session",
        "max_upload_mb_per_file",
    )
    parsed: dict[str, int] = {}
    ok = True
    for f in fields:
        v = value.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            errors.append(f"`limits.{f}` must be a positive integer")
            ok = False
            continue
        parsed[f] = v
    if ok and parsed["max_custom_rating_dimensions"] > _MAX_ENABLED_RATINGS:
        errors.append(
            f"`limits.max_custom_rating_dimensions` must be <= {_MAX_ENABLED_RATINGS}"
        )
        ok = False
    if not ok:
        return None
    return Limits(**parsed)
```

- [ ] **Step 4.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all tests pass; coverage above 85%.

- [ ] **Step 4.5: Commit**

```bash
git add flexlog/config_loader.py tests/unit/test_config_loader.py
git commit -m "M1: add config_loader with full validation matrix

Frozen Config/AppLabels/RatingDimension/Limits dataclasses; load_config()
collects all validation errors before raising. Enforces ≤6 enabled
ratings, slug-shaped IDs, scale ranges, positive limits."
```

---

## Task 5: `config_loader.py` — first-run bootstrap

Adds the helper that writes a default `config.json` if missing, then loads it. Spec §6.2.

**Files:**
- Modify: `flexlog/config_loader.py`
- Modify: `tests/unit/test_config_loader.py`

- [ ] **Step 5.1: Append failing tests**

`tests/unit/test_config_loader.py`:

```python
# --- First-run bootstrap ---

from flexlog.config_loader import DEFAULT_CONFIG_JSON, load_or_bootstrap


def test_load_or_bootstrap_writes_default_when_missing(tmp_path):
    p = tmp_path / "config.json"
    assert not p.exists()
    cfg = load_or_bootstrap(p)
    # File is now present
    assert p.exists()
    # Content matches the canonical default
    assert json.loads(p.read_text()) == json.loads(DEFAULT_CONFIG_JSON)
    # And the loaded Config is consistent
    assert cfg.app.name == "Interview Log"


def test_load_or_bootstrap_existing_valid_file_unchanged(tmp_path):
    p = tmp_path / "config.json"
    payload = _valid_config_dict()
    payload["app"]["name"] = "My Custom Name"
    p.write_text(json.dumps(payload))
    cfg = load_or_bootstrap(p)
    assert cfg.app.name == "My Custom Name"
    # Bootstrap must not overwrite an existing file
    assert json.loads(p.read_text())["app"]["name"] == "My Custom Name"


def test_load_or_bootstrap_existing_malformed_file_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ broken")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_or_bootstrap(p)
    # Must not have overwritten the user's broken file
    assert p.read_text() == "{ broken"


def test_default_config_is_self_consistent(tmp_path):
    """Sanity: the canonical default must validate cleanly."""
    p = tmp_path / "config.json"
    p.write_text(DEFAULT_CONFIG_JSON)
    cfg = load_config(p)
    assert cfg.app.name == "Interview Log"
    assert any(r.id == "overall_quality" for r in cfg.ratings)
```

- [ ] **Step 5.2: Run failing tests**

```bash
pytest tests/unit/test_config_loader.py -v
```

Expected: import error on `DEFAULT_CONFIG_JSON` and `load_or_bootstrap`.

- [ ] **Step 5.3: Append to `flexlog/config_loader.py`**

Add these definitions at the end of the file:

```python
# Canonical default config.json — used at first-run bootstrap.
# Mirrors the example in PRD §6.1.
DEFAULT_CONFIG_JSON = """{
  "app": {
    "name": "Interview Log",
    "entity_singular": "Guest",
    "entity_plural": "Guests",
    "session_singular": "Interview",
    "session_plural": "Interviews"
  },
  "ratings": [
    {
      "id": "overall_quality",
      "label": "Overall Quality",
      "description": "General impression of the session",
      "scale_min": 0,
      "scale_max": 5,
      "enabled": true
    },
    {
      "id": "clarity",
      "label": "Clarity",
      "description": "How clear and articulate the person was",
      "scale_min": 0,
      "scale_max": 5,
      "enabled": true
    }
  ],
  "ui_strings": {
    "new_person": "New Guest",
    "add_session": "Add Interview",
    "search_placeholder": "Search guests or tags",
    "empty_dashboard": "No guests yet. Add your first guest to begin."
  },
  "limits": {
    "max_custom_rating_dimensions": 6,
    "max_audio_files_per_session": 10,
    "max_video_files_per_session": 10,
    "max_photo_files_per_session": 50,
    "max_upload_mb_per_file": 500
  }
}
"""


def load_or_bootstrap(path: Path) -> Config:
    """Load config.json. If absent, write the default first, then load.

    Existing-but-malformed files are NOT overwritten — they raise so the user
    can fix their hand-edited file.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    return load_config(path)
```

- [ ] **Step 5.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all green; coverage on `config_loader.py` ≥95%.

- [ ] **Step 5.5: Commit**

```bash
git add flexlog/config_loader.py tests/unit/test_config_loader.py
git commit -m "M1: add first-run bootstrap of default config.json

load_or_bootstrap() writes the canonical default if config.json is
missing, then loads. Existing malformed files are NOT overwritten —
they raise so the user can fix the hand edit."
```

---

## Task 6: `web/filters.py` — `ui` filter + label context processor

Provides the Jinja filter that maps short keys to user/builtin UI strings, plus a context processor that injects `labels` into every template. Spec §6.3.

**Files:**
- Create: `flexlog/web/__init__.py` (placeholder; full registry comes in Task 7)
- Create: `flexlog/web/filters.py`
- Create: `tests/unit/test_filters.py`

- [ ] **Step 6.1: Write the failing test**

`tests/unit/test_filters.py`:

```python
from unittest.mock import MagicMock

import pytest

from flexlog.config_loader import AppLabels, Config, Limits
from flexlog.web.filters import (
    BUILTIN_UI_DEFAULTS,
    build_labels_context,
    ui_filter,
)


def _config(ui_strings: dict[str, str] | None = None) -> Config:
    return Config(
        app=AppLabels(
            name="Interview Log",
            entity_singular="Guest",
            entity_plural="Guests",
            session_singular="Interview",
            session_plural="Interviews",
        ),
        ratings=(),
        ui_strings=ui_strings or {},
        limits=Limits(
            max_custom_rating_dimensions=6,
            max_audio_files_per_session=10,
            max_video_files_per_session=10,
            max_photo_files_per_session=50,
            max_upload_mb_per_file=500,
        ),
    )


def test_ui_filter_returns_user_value_when_present():
    cfg = _config({"new_person": "New Guest"})
    assert ui_filter("new_person", cfg) == "New Guest"


def test_ui_filter_falls_back_to_builtin_when_user_omits_key():
    cfg = _config({})
    assert ui_filter("new_person", cfg) == BUILTIN_UI_DEFAULTS["new_person"]


def test_ui_filter_unknown_key_returns_key_itself():
    cfg = _config({})
    # Unknown key — neither user nor builtin defines it. Return the key so
    # the missing-string is visible during development without raising.
    assert ui_filter("totally_unknown_key", cfg) == "totally_unknown_key"


def test_builtin_ui_defaults_includes_minimum_keys():
    # M1 expects at least these keys to render the placeholder dashboard
    for required in ("new_person", "empty_dashboard"):
        assert required in BUILTIN_UI_DEFAULTS


def test_build_labels_context_shape():
    cfg = _config()
    labels = build_labels_context(cfg)
    assert labels["app_name"] == "Interview Log"
    assert labels["entity"]["singular"] == "Guest"
    assert labels["entity"]["plural"] == "Guests"
    assert labels["session"]["singular"] == "Interview"
    assert labels["session"]["plural"] == "Interviews"
```

- [ ] **Step 6.2: Run failing tests**

```bash
pytest tests/unit/test_filters.py -v
```

Expected: import error on missing module.

- [ ] **Step 6.3: Implement `flexlog/web/__init__.py` and `flexlog/web/filters.py`**

`flexlog/web/__init__.py`:

```python
"""flexlog blueprints + Flask wiring helpers."""
```

(Empty package docstring for now; the `register_blueprints` registry comes in Task 7.)

`flexlog/web/filters.py`:

```python
"""Jinja filters and context processors for config-driven UI labels.

The `ui` filter maps short keys to user-supplied strings (from config.json)
with a built-in fallback. The labels context processor exposes app/entity/
session labels under a single `labels` namespace that templates can read.
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from flexlog.config_loader import Config

# Keys used by templates anywhere in the app. M1 needs only what the
# placeholder dashboard renders. Subsequent milestones extend this map.
BUILTIN_UI_DEFAULTS: dict[str, str] = {
    "new_person": "New Person",
    "empty_dashboard": "Nothing here yet.",
    "search_placeholder": "Search",
    "add_session": "Add Session",
}


def ui_filter(key: str, config: Config | None = None) -> str:
    """Look up `key` first in the user's ui_strings, then BUILTIN_UI_DEFAULTS,
    else return `key` itself so missing strings are visible during dev.

    `config` is injectable for unit testing; in production the registered
    Jinja filter pulls it from `current_app.config["FLEXLOG"]`.
    """
    if config is None:
        config = current_app.config["FLEXLOG"]
    if key in config.ui_strings:
        return config.ui_strings[key]
    return BUILTIN_UI_DEFAULTS.get(key, key)


def build_labels_context(config: Config) -> dict[str, Any]:
    """Build the `labels` dict injected into every template."""
    return {
        "app_name": config.app.name,
        "entity": {
            "singular": config.app.entity_singular,
            "plural": config.app.entity_plural,
        },
        "session": {
            "singular": config.app.session_singular,
            "plural": config.app.session_plural,
        },
    }
```

- [ ] **Step 6.4: Run tests**

```bash
pytest -v
```

Expected: all green.

- [ ] **Step 6.5: Commit**

```bash
git add flexlog/web/__init__.py flexlog/web/filters.py tests/unit/test_filters.py
git commit -m "M1: add ui Jinja filter + labels context processor

ui_filter() looks up user > builtin > raw key. build_labels_context()
exposes app/entity/session labels to every template under labels.*."
```

---

## Task 7: App factory + base template + placeholder home route

Wires everything together: `create_app()` validates the data dir, loads config, ensures layout, registers the `ui` filter and `labels` context processor, and registers a placeholder home blueprint that renders the dashboard.

**Files:**
- Create: `flexlog/app.py`
- Modify: `flexlog/web/__init__.py`
- Create: `flexlog/web/home_bp.py`
- Create: `flexlog/templates/_base.html`
- Create: `flexlog/templates/home.html`
- Create: `flexlog/static/css/main.css`
- Modify: `tests/conftest.py` (create with full fixtures)
- Create: `tests/integration/test_app_factory.py`
- Create: `tests/integration/test_home_route.py`

- [ ] **Step 7.1: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures for flexlog tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flexlog.config_loader import DEFAULT_CONFIG_JSON


@pytest.fixture
def tmp_data_dir_no_config(tmp_path, monkeypatch):
    """An existing, writable data dir with NO config.json yet."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """An existing, writable data dir with the canonical default config.json."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    return tmp_path


@pytest.fixture
def app(tmp_data_dir):
    from flexlog.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 7.2: Write the failing app-factory tests**

`tests/integration/test_app_factory.py`:

```python
from pathlib import Path

import pytest

from flexlog.app import create_app
from flexlog.config_loader import ConfigError
from flexlog.paths import DataDirError


def test_create_app_happy_path(tmp_data_dir):
    app = create_app()
    assert app.name == "flexlog"
    # Config is stashed
    cfg = app.config["FLEXLOG"]
    assert cfg.app.name == "Interview Log"
    # Layout was ensured
    assert (tmp_data_dir / "data").is_dir()
    assert (tmp_data_dir / "uploads").is_dir()
    assert (tmp_data_dir / "uploads" / ".tmp").is_dir()


def test_create_app_bootstraps_default_config_when_missing(tmp_data_dir_no_config):
    app = create_app()
    cfg_file = tmp_data_dir_no_config / "config.json"
    assert cfg_file.exists()
    assert app.config["FLEXLOG"].app.name == "Interview Log"


def test_create_app_unset_data_dir_raises(monkeypatch):
    monkeypatch.delenv("FLEXLOG_DATA_DIR", raising=False)
    with pytest.raises(DataDirError):
        create_app()


def test_create_app_relative_data_dir_raises(monkeypatch):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", "relative/path")
    with pytest.raises(DataDirError, match="absolute"):
        create_app()


def test_create_app_nonexistent_data_dir_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path / "nope"))
    with pytest.raises(DataDirError, match="does not exist"):
        create_app()


def test_create_app_malformed_config_raises(tmp_data_dir_no_config):
    (tmp_data_dir_no_config / "config.json").write_text("{ not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        create_app()


def test_create_app_csp_friendly_no_debug_by_default(tmp_data_dir):
    app = create_app()
    assert app.debug is False


def test_create_app_debug_enabled_via_env(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("FLEXLOG_DEBUG", "1")
    app = create_app()
    assert app.debug is True
```

`tests/integration/test_home_route.py`:

```python
def test_home_renders_with_default_labels(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # App name from config.app.name
    assert "Interview Log" in body
    # Entity plural from config.app.entity_plural
    assert "Guests" in body
    # ui filter — empty_dashboard default from config.json
    assert "No guests yet. Add your first guest to begin." in body


def test_home_uses_builtin_default_when_user_omits_key(tmp_data_dir):
    """If config.json's ui_strings drops a key, the builtin default fills in."""
    import json
    from flexlog.app import create_app

    cfg_path = tmp_data_dir / "config.json"
    payload = json.loads(cfg_path.read_text())
    payload["ui_strings"] = {}  # wipe all user-supplied keys
    cfg_path.write_text(json.dumps(payload))

    app = create_app()
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Falls back to BUILTIN_UI_DEFAULTS["empty_dashboard"]
    assert "Nothing here yet." in body


def test_home_xss_safe_app_name(tmp_data_dir):
    """An app name containing HTML must be escaped, not rendered as markup."""
    import json
    from flexlog.app import create_app

    cfg_path = tmp_data_dir / "config.json"
    payload = json.loads(cfg_path.read_text())
    payload["app"]["name"] = "<script>alert(1)</script>"
    cfg_path.write_text(json.dumps(payload))

    app = create_app()
    client = app.test_client()
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
```

- [ ] **Step 7.3: Run failing tests**

```bash
pytest tests/integration -v
```

Expected: import error on `flexlog.app.create_app`.

- [ ] **Step 7.4: Implement `flexlog/web/home_bp.py`**

```python
"""Placeholder home/dashboard route for M1.

In M2 this is replaced by the real people-list dashboard. M1 keeps just
enough to verify the app factory wires up config-driven labels correctly.
"""

from __future__ import annotations

from flask import Blueprint, render_template

home_bp = Blueprint("home", __name__)


@home_bp.get("/")
def home():
    return render_template("home.html")
```

- [ ] **Step 7.5: Replace `flexlog/web/__init__.py` with the registry**

```python
"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.home_bp import home_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(home_bp)
```

- [ ] **Step 7.6: Implement `flexlog/app.py`**

```python
"""Flask application factory for flexlog."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

from flexlog import paths
from flexlog.config_loader import Config, load_or_bootstrap
from flexlog.web import register_blueprints
from flexlog.web.filters import build_labels_context, ui_filter


def create_app() -> Flask:
    """Build and return the configured Flask app.

    Reads FLEXLOG_DATA_DIR (required), loads/bootstraps config.json, and
    raises (DataDirError or ConfigError) if anything is wrong. No fallback
    values — startup failures are loud and explicit.
    """
    _configure_logging()

    # 1. Validate data dir + create child layout
    data_dir = paths.data_dir()  # raises DataDirError on failure
    paths.ensure_layout()

    # 2. Load (or bootstrap) config.json
    config: Config = load_or_bootstrap(paths.config_path())

    # 3. Build the Flask app
    app = Flask(
        "flexlog",
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["FLEXLOG"] = config
    app.config["FLEXLOG_DATA_DIR"] = str(data_dir)
    app.debug = os.environ.get("FLEXLOG_DEBUG", "") == "1"

    # 4. Wire up filters + context processor
    app.jinja_env.filters["ui"] = lambda key: ui_filter(key)

    @app.context_processor
    def _inject_labels() -> dict[str, object]:
        return {"labels": build_labels_context(config)}

    # 5. Register blueprints
    register_blueprints(app)

    return app


def _configure_logging() -> None:
    # stdlib logging to stderr at INFO. Idempotent — only configure once.
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
```

- [ ] **Step 7.7: Write `flexlog/templates/_base.html`**

```jinja
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}{{ labels.app_name }}{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/main.css') }}">
</head>
<body>
  <header class="site-header">
    <h1 class="site-title">{{ labels.app_name }}</h1>
    <nav class="site-nav">
      <a href="{{ url_for('home.home') }}">{{ labels.entity.plural }}</a>
    </nav>
  </header>
  <main class="site-main">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 7.8: Write `flexlog/templates/home.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ labels.entity.plural }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="dashboard">
  <header class="dashboard-header">
    <h2>{{ labels.entity.plural }}</h2>
    <a class="btn btn-primary" href="#" aria-disabled="true">{{ "new_person" | ui }}</a>
  </header>
  <p class="empty-state">{{ "empty_dashboard" | ui }}</p>
</section>
{% endblock %}
```

- [ ] **Step 7.9: Write minimal `flexlog/static/css/main.css`**

```css
:root {
  --fg: #1f2328;
  --muted: #57606a;
  --accent: #0969da;
  --bg: #ffffff;
  --bg-soft: #f6f8fa;
  --border: #d0d7de;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.5;
}

.site-header {
  border-bottom: 1px solid var(--border);
  padding: 1rem 2rem;
  display: flex;
  align-items: baseline;
  gap: 2rem;
}

.site-title {
  margin: 0;
  font-size: 1.25rem;
}

.site-nav a {
  color: var(--accent);
  text-decoration: none;
  margin-right: 1rem;
}

.site-main {
  max-width: 1100px;
  margin: 2rem auto;
  padding: 0 2rem;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.btn {
  display: inline-block;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  text-decoration: none;
  border: 1px solid var(--border);
  color: var(--fg);
  background: var(--bg-soft);
}

.btn-primary {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}

.empty-state {
  color: var(--muted);
  padding: 2rem;
  text-align: center;
  border: 1px dashed var(--border);
  border-radius: 6px;
}
```

- [ ] **Step 7.10: Run tests, verify pass**

```bash
pytest -v
```

Expected: all tests pass; coverage ≥85%.

- [ ] **Step 7.11: Commit**

```bash
git add flexlog/app.py flexlog/web/__init__.py flexlog/web/home_bp.py \
        flexlog/templates/_base.html flexlog/templates/home.html \
        flexlog/static/css/main.css \
        tests/conftest.py tests/integration/test_app_factory.py \
        tests/integration/test_home_route.py
git commit -m "M1: app factory + base template + placeholder dashboard

create_app() validates FLEXLOG_DATA_DIR, ensures child layout, loads or
bootstraps config.json, registers ui filter + labels context processor,
mounts home blueprint. Placeholder dashboard renders config-driven labels
and empty state."
```

---

## Task 8: `__main__.py` runner + console script

**Files:**
- Create: `flexlog/__main__.py`
- Create: `tests/integration/test_main_entry.py`

- [ ] **Step 8.1: Write the failing test**

`tests/integration/test_main_entry.py`:

```python
import importlib

import flexlog.__main__ as main_mod


def test_main_module_exposes_main_function():
    assert hasattr(main_mod, "main"), "__main__ must export main()"
    assert callable(main_mod.main)


def test_main_uses_loopback_host_and_default_port(monkeypatch, tmp_data_dir):
    captured = {}

    def fake_run(self, host, port, threaded, debug):
        captured["host"] = host
        captured["port"] = port
        captured["threaded"] = threaded
        captured["debug"] = debug

    monkeypatch.setattr("flask.Flask.run", fake_run, raising=True)
    main_mod.main()
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 5050
    assert captured["threaded"] is True


def test_main_respects_flexlog_port_env(monkeypatch, tmp_data_dir):
    captured = {}

    def fake_run(self, host, port, threaded, debug):
        captured["port"] = port

    monkeypatch.setattr("flask.Flask.run", fake_run, raising=True)
    monkeypatch.setenv("FLEXLOG_PORT", "6060")
    main_mod.main()
    assert captured["port"] == 6060


def test_main_rejects_invalid_port(monkeypatch, tmp_data_dir, capsys):
    monkeypatch.setenv("FLEXLOG_PORT", "not-a-number")
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert "FLEXLOG_PORT" in captured.err


# Reload safety — make sure subsequent imports still work
def test_main_module_reimports_cleanly():
    mod = importlib.reload(main_mod)
    assert callable(mod.main)


import pytest  # noqa: E402  (placed at end so name is available above where used)
```

- [ ] **Step 8.2: Run failing tests**

```bash
pytest tests/integration/test_main_entry.py -v
```

Expected: import error on `flexlog.__main__`.

- [ ] **Step 8.3: Implement `flexlog/__main__.py`**

```python
"""Command-line entry point: `python -m flexlog` or the `flexlog` console script."""

from __future__ import annotations

import os
import sys

from flexlog.app import create_app

DEFAULT_PORT = 5050


def main() -> None:
    port_raw = os.environ.get("FLEXLOG_PORT", str(DEFAULT_PORT))
    try:
        port = int(port_raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        print(
            f"FLEXLOG_PORT={port_raw!r} is not a valid TCP port number (1..65535)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    app = create_app()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=app.debug)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.4: Run tests**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 8.5: Smoke-test the entry point manually**

```bash
export FLEXLOG_DATA_DIR="$(mktemp -d)"
flexlog &
APP_PID=$!
sleep 1
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5050/
kill $APP_PID
unset FLEXLOG_DATA_DIR
```

Expected: prints `200`. (Run in a scratch shell — do not commit any data dir output.)

- [ ] **Step 8.6: Commit**

```bash
git add flexlog/__main__.py tests/integration/test_main_entry.py
git commit -m "M1: add python -m flexlog runner + console script

Binds 127.0.0.1, port from FLEXLOG_PORT (default 5050), threaded for
local concurrency. Invalid port exits 2 with a clear stderr message."
```

---

## Task 9: README + final verification sweep

**Files:**
- Create: `README.md`

- [ ] **Step 9.1: Write `README.md`**

```markdown
# flexlog

Local-only, single-user web app for recording recurring 1v1 sessions with people.

Internal codename for the **1v1 Journal** product spec — see
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md`.

This is the **M1 Foundation** milestone: the app starts, validates its data
directory, loads (or bootstraps) `config.json`, and serves a placeholder
dashboard. Domain models and CRUD come in subsequent milestones.

## Requirements

- Python 3.11 or newer
- A directory you control where flexlog can store its database, uploads, and config

## Install

```bash
git clone <this repo> flexlog
cd flexlog
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure your data directory

flexlog refuses to start unless `FLEXLOG_DATA_DIR` points at an absolute,
existing, writable directory. The directory is **not** created for you —
this is deliberate so flexlog never writes data into a place you didn't pick.

```bash
mkdir -p ~/flexlog-data
export FLEXLOG_DATA_DIR=~/flexlog-data   # use an absolute path; ~ is fine in shell
```

On first run, flexlog writes a default `config.json` into that directory if
none exists. Edit it freely and restart to apply changes.

## Run

```bash
flexlog
# or equivalently:
python -m flexlog
```

Then open http://127.0.0.1:5050/ in a browser. The bind host is always
loopback. Set `FLEXLOG_PORT=...` to choose a different port.

Set `FLEXLOG_DEBUG=1` to enable Flask debug mode (do not do this when
serving real data).

## Customizing labels

The `app`, `ui_strings`, and `ratings` sections of `config.json` rethread
every user-facing label. The same codebase covers interview logs, coaching
journals, language exchange logs, etc. without code changes. See
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md` §6.1 for the
schema and `flexlog/config_loader.py` for the validator.

## Backup / restore

Stop the app, then copy the entire `$FLEXLOG_DATA_DIR` directory. To
restore: place the directory on the new machine, set `FLEXLOG_DATA_DIR`
to its absolute path, and run `flexlog`. Both the SQLite database (M2+)
and uploaded media (M4+) are inside that directory.

## Run the test suite

```bash
pytest
```

The configuration in `pyproject.toml` enforces a global 85% line-coverage
floor. Tests must include enough coverage to cross that threshold or the
suite fails.

## What's next

Subsequent milestones:

- M2: people + tags
- M3: sessions + ratings + notes
- M4: media + Media Library + hash dedup
- M5: avatar cropper + sort + polish

See `docs/superpowers/specs/2026-05-07-flexlog-design.md` §12 for the full
roadmap.
```

- [ ] **Step 9.2: Run the full suite with coverage report**

```bash
pytest -v
```

Expected: all tests pass; coverage ≥85% reported in terminal output. If a module is below ≥95% (specifically `paths`, `hashing`, `config_loader`), add tests to push it higher per spec §11.4 — re-run until clean.

- [ ] **Step 9.3: Manual end-to-end smoke**

```bash
# 1. fresh data dir, no config — bootstrap should create one
SCRATCH=$(mktemp -d)
FLEXLOG_DATA_DIR="$SCRATCH" flexlog &
APP_PID=$!
sleep 1

# Confirm bootstrap created the file
ls "$SCRATCH/config.json" "$SCRATCH/data" "$SCRATCH/uploads" "$SCRATCH/uploads/.tmp"

# Confirm dashboard renders
curl -s http://127.0.0.1:5050/ | grep -q "Interview Log" && echo "OK: app name visible"
curl -s http://127.0.0.1:5050/ | grep -q "Guests" && echo "OK: entity plural visible"

kill $APP_PID

# 2. malformed config — should fail loudly
echo "{ broken json" > "$SCRATCH/config.json"
FLEXLOG_DATA_DIR="$SCRATCH" flexlog 2>&1 | grep -q "not valid JSON" && echo "OK: malformed config rejected"

# Cleanup
rm -rf "$SCRATCH"
```

Expected: every `OK:` line prints. The malformed-config run exits non-zero.

- [ ] **Step 9.4: Commit**

```bash
git add README.md
git commit -m "M1: add README with install / run / config / test instructions"
```

- [ ] **Step 9.5: Tag the milestone (optional)**

```bash
git tag m1-foundation
```

---

## Self-review notes (post-write)

**Spec coverage check:**

| Spec §12 M1 deliverable | Implemented in |
|---|---|
| Project skeleton | Task 1 (pyproject, gitignore, package layout) |
| `paths.py` | Tasks 2 + 3 |
| `config_loader.py` | Tasks 4 + 5 |
| `hashing.py` | Task 1 |
| App factory | Task 7 |
| Base template `_base.html` with config-driven labels | Task 7 |
| `pyproject` | Task 1 |
| pytest scaffolding with coverage gate | Task 1 |
| `python -m flexlog` runner | Task 8 |
| Placeholder dashboard | Task 7 |
| Fails fast on bad config | Tasks 2, 4, 7 (covered by tests) |

**Cross-task type consistency:** `Config`, `AppLabels`, `RatingDimension`, `Limits`, `DEFAULT_CONFIG_JSON`, `load_config`, `load_or_bootstrap`, `ConfigError` — all defined in Task 4/5 and consumed in Task 7 with matching names. `data_dir`, `ensure_layout`, `config_path`, `db_path`, `uploads_dir`, `tmp_uploads_dir`, `resolve_file_key`, `file_key_for`, `DataDirError`, `FileKeyError` — defined in Tasks 2/3, consumed in Task 7. `BUILTIN_UI_DEFAULTS`, `ui_filter`, `build_labels_context` — defined in Task 6, consumed in Task 7. No drift detected.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" remain. Every step has runnable code or a runnable command.

**Scope check:** M1 is bounded to the foundation pieces — no domain models, no media pipeline, no auth, no SQLAlchemy. Each subsequent milestone has its own plan in the design spec §12. Plan is the right size for a single subagent-driven cycle.

---

**End of M1 plan.**
