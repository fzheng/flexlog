"""HEIC upload support: magic-byte detection, transcode-to-JPEG with
resolution preserved, end-to-end pipeline returns a JPEG MediaFile row."""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from flexlog.services.media import (
    _HEIC_BRANDS,
    _detect_mime_from_bytes,
    _looks_like_heic,
    _transcode_heic_to_jpeg,
)


def _make_heic_bytes(width: int = 800, height: int = 600, color=(200, 50, 80)) -> bytes:
    """Build a real HEIC file in memory. Requires pillow-heif registered."""
    from PIL import Image
    import pillow_heif  # noqa: F401 — register_heif_opener already ran in services.media

    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="HEIF", quality=90)
    return buf.getvalue()


def test_looks_like_heic_on_real_bytes():
    head = _make_heic_bytes(width=10, height=10)[:64]
    assert _looks_like_heic(head)


def test_looks_like_heic_rejects_jpeg_head():
    # First 12 bytes of a JPEG: ffd8ffe0 0010 'JFIF'
    head = bytes.fromhex("ffd8ffe000104a464946000101")
    assert not _looks_like_heic(head)


def test_detect_mime_from_bytes_recognizes_heic():
    head = _make_heic_bytes(width=16, height=16)[:64]
    assert _detect_mime_from_bytes(head) == "image/heic"


def test_transcode_preserves_resolution(tmp_path):
    """The point of the conversion: a 1920x1080 HEIC becomes a 1920x1080
    JPEG — no resize, no aspect change."""
    from PIL import Image

    heic = _make_heic_bytes(width=1920, height=1080)
    src = tmp_path / "input.heic.part"
    src.write_bytes(heic)

    sha, size, head = _transcode_heic_to_jpeg(src)

    # Source path now contains JPEG bytes.
    assert head[:3] == b"\xff\xd8\xff"  # JPEG SOI
    assert size > 0
    assert len(sha) == 64

    # Verify pixel dimensions match the original.
    img = Image.open(src)
    assert img.size == (1920, 1080)
    img.close()


def test_transcode_preserves_resolution_for_non_power_of_two_sizes(tmp_path):
    """HEIC dimensions are often quirky (4032x3024 from iPhone). Make sure
    the transcoder doesn't round/pad to a nicer size."""
    from PIL import Image

    heic = _make_heic_bytes(width=4032, height=3024)
    src = tmp_path / "input.heic.part"
    src.write_bytes(heic)

    _transcode_heic_to_jpeg(src)
    img = Image.open(src)
    assert img.size == (4032, 3024)
    img.close()


def test_transcode_produces_valid_jpeg_with_visible_content(tmp_path):
    """Sanity: the transcoded JPEG should open with Pillow and the dominant
    color should match the input (within JPEG q=95 tolerance)."""
    from PIL import Image

    heic = _make_heic_bytes(width=200, height=200, color=(255, 100, 50))
    src = tmp_path / "input.heic.part"
    src.write_bytes(heic)

    _transcode_heic_to_jpeg(src)
    img = Image.open(src)
    # Sample the center pixel; JPEG q=95 + HEIF round-trip should keep it close.
    cx, cy = img.size[0] // 2, img.size[1] // 2
    r, g, b = img.getpixel((cx, cy))
    img.close()
    # Tolerance: HEIC encode + JPEG encode introduce small color drift.
    assert abs(r - 255) <= 8
    assert abs(g - 100) <= 8
    assert abs(b - 50) <= 8


def test_heic_brand_set_covers_common_iphone_variants():
    """Spot-check that the brand set includes what iPhones actually emit."""
    for brand in (b"heic", b"heix", b"mif1"):
        assert brand in _HEIC_BRANDS
