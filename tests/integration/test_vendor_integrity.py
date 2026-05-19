"""Verify that flexlog/static/vendor/INTEGRITY.txt is in sync with
the files on disk, AND that every vendored file referenced from a
template has a corresponding SRI hash in vendor_integrity.SRI_HASHES."""
from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = REPO_ROOT / "flexlog" / "static" / "vendor"
INTEGRITY_TXT = VENDOR_DIR / "INTEGRITY.txt"


def _sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_manifest() -> dict[str, str]:
    """INTEGRITY.txt format: '<sha256>  <relpath>' per line."""
    out: dict[str, str] = {}
    for line in INTEGRITY_TXT.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # sha256sum format uses TWO spaces between hash and path.
        sha, _, rel = line.partition("  ")
        if not sha or not rel:
            continue
        out[rel] = sha
    return out


def test_integrity_manifest_exists():
    assert INTEGRITY_TXT.exists(), (
        f"INTEGRITY.txt missing at {INTEGRITY_TXT}. "
        f"Regenerate via: python scripts/regen_vendor_integrity.py"
    )


def test_every_vendor_file_is_in_manifest():
    """Every regular file under vendor/ (except INTEGRITY.txt itself
    and dotfiles) must have an entry in the manifest."""
    manifest = _parse_manifest()
    on_disk = {
        p.relative_to(VENDOR_DIR).as_posix()
        for p in VENDOR_DIR.rglob("*")
        if p.is_file()
        and p.name != "INTEGRITY.txt"
        and not p.name.startswith(".")
    }
    missing_from_manifest = on_disk - set(manifest.keys())
    extra_in_manifest = set(manifest.keys()) - on_disk
    assert not missing_from_manifest, (
        f"vendor files not in manifest: {missing_from_manifest}. "
        f"Re-run scripts/regen_vendor_integrity.py."
    )
    assert not extra_in_manifest, (
        f"manifest references missing files: {extra_in_manifest}"
    )


def test_every_manifest_hash_matches_disk():
    manifest = _parse_manifest()
    for rel, expected_sha in manifest.items():
        path = VENDOR_DIR / rel
        actual_sha = _sha256_hex(path)
        assert actual_sha == expected_sha, (
            f"{rel}: hash drift\n"
            f"  manifest: {expected_sha}\n"
            f"  on disk:  {actual_sha}\n"
            f"Re-run scripts/regen_vendor_integrity.py and commit."
        )


def test_sri_hashes_module_covers_all_vendor_files():
    """Every vendor file must also be in SRI_HASHES (for the SRI
    Jinja filter)."""
    from flexlog.web.vendor_integrity import SRI_HASHES
    on_disk_static_paths = {
        p.relative_to(VENDOR_DIR.parent).as_posix()
        for p in VENDOR_DIR.rglob("*")
        if p.is_file()
        and p.name != "INTEGRITY.txt"
        and not p.name.startswith(".")
    }
    missing = on_disk_static_paths - set(SRI_HASHES.keys())
    assert not missing, (
        f"vendor files missing from SRI_HASHES: {missing}. "
        f"Re-run scripts/regen_vendor_integrity.py."
    )


def test_sri_hashes_format_is_sha384_base64():
    """Every entry in SRI_HASHES must use the sha384- prefix per the
    SRI spec, followed by base64."""
    import base64
    from flexlog.web.vendor_integrity import SRI_HASHES
    for path, sri in SRI_HASHES.items():
        assert sri.startswith("sha384-"), (
            f"{path}: SRI value must start with 'sha384-', got {sri[:20]!r}"
        )
        b64 = sri[len("sha384-"):]
        # Decoding must succeed and yield 48 bytes (sha384 output size).
        decoded = base64.b64decode(b64, validate=True)
        assert len(decoded) == 48, (
            f"{path}: decoded SRI is {len(decoded)} bytes; expected 48"
        )


def test_vendor_sri_filter_returns_integrity_attribute():
    """The Jinja filter that templates use to emit integrity="..."
    must produce a non-empty attribute fragment for a known vendor
    file, and an empty string for an unknown one."""
    from flexlog.web.filters import vendor_sri
    out = vendor_sri("vendor/photoswipe/photoswipe.umd.min.js")
    assert 'integrity="sha384-' in out
    assert 'crossorigin="anonymous"' in out
    assert vendor_sri("vendor/does-not-exist.js") == ""


def test_session_detail_renders_sri_attribute(authed_client, person, db_session):
    """End-to-end: a session detail page (which loads PhotoSwipe)
    must include integrity= on the vendored <script> tags."""
    from flexlog.services.sessions import create_session
    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-18",
        ratings={"energy": 4}, notes=None, link_urls=[], link_thumb_keys=[],
    )
    db_session.commit()
    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    # PhotoSwipe should be referenced with an integrity attribute.
    assert "photoswipe.umd.min.js" in body
    # Find the script tag containing photoswipe.umd.min.js and verify
    # an integrity= is present on the same tag.
    for line in body.splitlines():
        if "photoswipe.umd.min.js" in line:
            assert 'integrity="sha384-' in line, (
                f"SRI missing on photoswipe script tag: {line!r}"
            )
            break
