"""link_thumbnails: SSRF guard + Pillow transcode + screenshot orchestration.

The Playwright screenshot itself is mocked in the orchestration tests;
the integration test_link_thumbnails_e2e suite covers the wired-into-
session-save path (also mocked at the fetch_thumbnail boundary)."""
from __future__ import annotations

import io
from unittest.mock import patch

from flexlog.services.link_thumbnails import (
    _is_safe_url,
    _to_jpeg,
    fetch_thumbnail,
)


# ----------------------------------------------------------- _is_safe_url

def test_safe_url_https_public():
    with patch("socket.gethostbyname", return_value="93.184.216.34"):
        assert _is_safe_url("https://example.com/article") is True


def test_safe_url_http_public():
    with patch("socket.gethostbyname", return_value="93.184.216.34"):
        assert _is_safe_url("http://example.com/article") is True


def test_safe_url_rejects_ftp_scheme():
    assert _is_safe_url("ftp://example.com/file") is False


def test_safe_url_rejects_file_scheme():
    assert _is_safe_url("file:///etc/passwd") is False


def test_safe_url_rejects_data_scheme():
    assert _is_safe_url("data:text/html,<html>...") is False


def test_safe_url_rejects_javascript_scheme():
    assert _is_safe_url("javascript:alert(1)") is False


def test_safe_url_rejects_missing_scheme():
    assert _is_safe_url("example.com/foo") is False


def test_safe_url_rejects_missing_host():
    assert _is_safe_url("https:///path") is False


def test_safe_url_rejects_loopback_ipv4():
    with patch("socket.gethostbyname", return_value="127.0.0.1"):
        assert _is_safe_url("http://localhost/x") is False


def test_safe_url_rejects_private_10():
    with patch("socket.gethostbyname", return_value="10.0.0.5"):
        assert _is_safe_url("http://internal/x") is False


def test_safe_url_rejects_private_192_168():
    with patch("socket.gethostbyname", return_value="192.168.1.5"):
        assert _is_safe_url("http://router/x") is False


def test_safe_url_rejects_private_172_16():
    with patch("socket.gethostbyname", return_value="172.20.0.5"):
        assert _is_safe_url("http://internal/x") is False


def test_safe_url_rejects_link_local_aws_metadata():
    with patch("socket.gethostbyname", return_value="169.254.169.254"):
        assert _is_safe_url("http://metadata/x") is False


def test_safe_url_rejects_dns_failure():
    with patch("socket.gethostbyname", side_effect=socket.gaierror("nope")):
        assert _is_safe_url("https://does-not-resolve.invalid/x") is False


def test_safe_url_rejects_garbage():
    assert _is_safe_url("") is False
    assert _is_safe_url("not a url") is False
    assert _is_safe_url(None) is False  # type: ignore[arg-type]


import socket  # noqa: E402 — used by test_safe_url_rejects_dns_failure


# ------------------------------------------------------------- _to_jpeg

def _make_png_bytes(width: int, height: int, color=(200, 50, 80)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_to_jpeg_passes_through_small_image():
    from PIL import Image
    png = _make_png_bytes(200, 150)
    jpeg = _to_jpeg(png)
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.size == (200, 150)
    assert out.format == "JPEG"


def test_to_jpeg_resizes_wide_image_preserving_aspect():
    from PIL import Image
    png = _make_png_bytes(2000, 1000)
    jpeg = _to_jpeg(png)
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.size == (640, 320)


def test_to_jpeg_resizes_1280x800_viewport():
    """The Playwright viewport produces 1280x800 PNGs; verify the
    resize chain produces 640x400."""
    from PIL import Image
    png = _make_png_bytes(1280, 800)
    jpeg = _to_jpeg(png)
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.size == (640, 400)


def test_to_jpeg_converts_rgba_to_rgb():
    from PIL import Image
    img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    jpeg = _to_jpeg(buf.getvalue())
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.mode == "RGB"


def test_to_jpeg_returns_none_on_garbage():
    assert _to_jpeg(b"this is not an image") is None


def test_to_jpeg_returns_none_on_empty():
    assert _to_jpeg(b"") is None


# ----------------------------------------------- fetch_thumbnail orchestration

def test_fetch_thumbnail_happy_path():
    """Safe URL + mocked screenshot bytes → JPEG bytes out."""
    from PIL import Image
    png = _make_png_bytes(1280, 800)
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("flexlog.services.link_thumbnails._screenshot_url", return_value=png):
        result = fetch_thumbnail("https://example.com/article")
    assert result is not None
    out = Image.open(io.BytesIO(result))
    assert out.format == "JPEG"
    assert out.size == (640, 400)  # 1280x800 viewport resized to 640 wide


def test_fetch_thumbnail_returns_none_for_unsafe_url():
    """Unsafe URL → no screenshot attempted → None."""
    with patch("socket.gethostbyname", return_value="10.0.0.5"), \
         patch(
             "flexlog.services.link_thumbnails._screenshot_url",
             side_effect=AssertionError("should not be called for unsafe URLs"),
         ):
        assert fetch_thumbnail("http://internal/x") is None


def test_fetch_thumbnail_returns_none_when_screenshot_fails():
    """Safe URL but Playwright failed (timeout, crash, etc.) → None."""
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("flexlog.services.link_thumbnails._screenshot_url", return_value=None):
        assert fetch_thumbnail("https://example.com/article") is None


def test_fetch_thumbnail_returns_none_when_screenshot_undecodable():
    """Screenshot returned garbage bytes → _to_jpeg fails → None."""
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch(
             "flexlog.services.link_thumbnails._screenshot_url",
             return_value=b"not an image",
         ):
        assert fetch_thumbnail("https://example.com/article") is None
