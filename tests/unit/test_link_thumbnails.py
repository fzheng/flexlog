"""link_thumbnails: og:image fetch + favicon fallback + SSRF guard."""
from __future__ import annotations

from unittest.mock import patch

from flexlog.services.link_thumbnails import _is_safe_url


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
    import socket
    with patch("socket.gethostbyname", side_effect=socket.gaierror("nope")):
        assert _is_safe_url("https://does-not-resolve.invalid/x") is False


def test_safe_url_rejects_garbage():
    assert _is_safe_url("") is False
    assert _is_safe_url("not a url") is False
    assert _is_safe_url(None) is False  # type: ignore[arg-type]


from unittest.mock import MagicMock

from bs4 import BeautifulSoup

from flexlog.services.link_thumbnails import (
    _extract_image_url,
    _fetch_html,
)


def _mock_response(text=None, content=None, status=200, headers=None):
    """Build a MagicMock that imitates requests.Response just enough for
    our streaming reads + parsing."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.url = "https://example.com/article"
    if text is not None:
        body_bytes = text.encode("utf-8")
    elif content is not None:
        body_bytes = content
    else:
        body_bytes = b""
    resp.iter_content = lambda chunk_size=8192: iter(
        [body_bytes[i : i + chunk_size] for i in range(0, len(body_bytes), chunk_size)]
    )
    resp.raise_for_status = MagicMock()
    return resp


def test_extract_og_image():
    html = """
    <html><head>
      <meta property="og:image" content="https://example.com/og.jpg">
      <meta name="twitter:image" content="https://example.com/tw.jpg">
    </head></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image_url(soup, "https://example.com/article") == "https://example.com/og.jpg"


def test_extract_twitter_image_fallback():
    html = """
    <html><head>
      <meta name="twitter:image" content="https://example.com/tw.jpg">
    </head></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image_url(soup, "https://example.com/article") == "https://example.com/tw.jpg"


def test_extract_link_icon_fallback():
    html = """
    <html><head>
      <link rel="icon" href="/favicon.png">
    </head></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image_url(soup, "https://example.com/article") == "https://example.com/favicon.png"


def test_extract_apple_touch_icon():
    html = """
    <html><head>
      <link rel="apple-touch-icon" href="/touch.png">
    </head></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image_url(soup, "https://example.com/article") == "https://example.com/touch.png"


def test_extract_default_favicon_when_nothing_in_html():
    html = "<html><head></head></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image_url(soup, "https://example.com/article") == "https://example.com/favicon.ico"


def test_extract_resolves_relative_og_image():
    html = """<html><head>
      <meta property="og:image" content="/img/og.jpg">
    </head></html>"""
    soup = BeautifulSoup(html, "html.parser")
    assert _extract_image_url(soup, "https://example.com/blog/2024/post") == "https://example.com/img/og.jpg"


def test_fetch_html_returns_soup_on_success():
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get") as get_mock:
        get_mock.return_value = _mock_response(
            text="<html><head><title>x</title></head></html>"
        )
        result = _fetch_html("https://example.com/article")
    assert result is not None
    assert result.title.string == "x"


def test_fetch_html_returns_none_on_unsafe_url():
    with patch("socket.gethostbyname", return_value="127.0.0.1"):
        assert _fetch_html("http://localhost/x") is None


def test_fetch_html_returns_none_on_http_error():
    import requests
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=requests.exceptions.RequestException("boom")):
        assert _fetch_html("https://example.com/x") is None


def test_fetch_html_truncates_oversize():
    """If the page is bigger than _MAX_HTML_BYTES, return None."""
    from flexlog.services.link_thumbnails import _MAX_HTML_BYTES
    big_html = "<html>" + ("x" * (_MAX_HTML_BYTES + 100)) + "</html>"
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get") as get_mock:
        get_mock.return_value = _mock_response(text=big_html)
        assert _fetch_html("https://example.com/x") is None


def test_fetch_html_returns_none_on_4xx():
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get") as get_mock:
        resp = _mock_response(text="not found", status=404)
        import requests
        resp.raise_for_status = MagicMock(
            side_effect=requests.exceptions.HTTPError("404")
        )
        get_mock.return_value = resp
        assert _fetch_html("https://example.com/x") is None


import io

from flexlog.services.link_thumbnails import _fetch_image, _to_jpeg


def _make_png_bytes(width: int, height: int, color=(200, 50, 80)) -> bytes:
    """Build PNG bytes with Pillow for testing the transcode helper."""
    from PIL import Image
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_fetch_image_returns_bytes_on_success():
    png = _make_png_bytes(100, 100)
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get") as get_mock:
        get_mock.return_value = _mock_response(content=png)
        result = _fetch_image("https://example.com/og.png")
    assert result == png


def test_fetch_image_returns_none_on_unsafe_url():
    with patch("socket.gethostbyname", return_value="10.0.0.5"):
        assert _fetch_image("http://internal/img.png") is None


def test_fetch_image_returns_none_on_oversize():
    """Image > _MAX_IMAGE_BYTES is rejected."""
    from flexlog.services.link_thumbnails import _MAX_IMAGE_BYTES
    big = b"\x00" * (_MAX_IMAGE_BYTES + 100)
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get") as get_mock:
        get_mock.return_value = _mock_response(content=big)
        assert _fetch_image("https://example.com/big.png") is None


def test_fetch_image_returns_none_on_http_error():
    import requests
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=requests.exceptions.RequestException("boom")):
        assert _fetch_image("https://example.com/img.png") is None


def test_to_jpeg_passes_through_small_image():
    """200x150 input stays 200x150 (no upscale)."""
    from PIL import Image
    png = _make_png_bytes(200, 150)
    jpeg = _to_jpeg(png)
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.size == (200, 150)
    assert out.format == "JPEG"


def test_to_jpeg_resizes_wide_image_preserving_aspect():
    """2000x1000 input → 400x200 output."""
    from PIL import Image
    png = _make_png_bytes(2000, 1000)
    jpeg = _to_jpeg(png)
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.size == (400, 200)


def test_to_jpeg_resizes_2000x1500():
    """2000x1500 → 400x300."""
    from PIL import Image
    png = _make_png_bytes(2000, 1500)
    jpeg = _to_jpeg(png)
    assert jpeg is not None
    out = Image.open(io.BytesIO(jpeg))
    assert out.size == (400, 300)


def test_to_jpeg_converts_rgba_to_rgb():
    """RGBA PNG (with transparency) saves as JPEG without crashing."""
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


from flexlog.services.link_thumbnails import fetch_thumbnail


def test_fetch_thumbnail_happy_path_og_image():
    """HTML has og:image → fetch HTML → fetch image → transcode → JPEG bytes."""
    from PIL import Image

    html = """<html><head>
      <meta property="og:image" content="https://example.com/og.png">
    </head></html>"""
    png = _make_png_bytes(800, 600)

    call_count = {"n": 0}
    def fake_get(url, **_kw):
        call_count["n"] += 1
        if "og.png" in url:
            return _mock_response(content=png)
        return _mock_response(text=html)

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        result = fetch_thumbnail("https://example.com/article")

    assert result is not None
    assert call_count["n"] == 2  # one HTML fetch + one image fetch
    out = Image.open(io.BytesIO(result))
    assert out.format == "JPEG"
    # 800-wide source resized to 400-wide
    assert out.size == (400, 300)


def test_fetch_thumbnail_favicon_fallback():
    """HTML has no image meta → fetches /favicon.ico → succeeds."""
    from PIL import Image

    html = "<html><head><title>x</title></head></html>"
    favicon = _make_png_bytes(64, 64)

    def fake_get(url, **_kw):
        if "favicon.ico" in url:
            return _mock_response(content=favicon)
        return _mock_response(text=html)

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        result = fetch_thumbnail("https://example.com/article")

    assert result is not None
    out = Image.open(io.BytesIO(result))
    assert out.format == "JPEG"


def test_fetch_thumbnail_returns_none_when_unsafe_url():
    with patch("socket.gethostbyname", return_value="10.0.0.5"):
        assert fetch_thumbnail("http://internal/x") is None


def test_fetch_thumbnail_returns_none_when_html_fetch_fails():
    import requests
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=requests.exceptions.Timeout("slow")):
        assert fetch_thumbnail("https://example.com/article") is None


def test_fetch_thumbnail_returns_none_when_image_fetch_fails():
    """HTML succeeds but the image URL 500s — still None, no crash."""
    html = """<html><head>
      <meta property="og:image" content="https://example.com/og.png">
    </head></html>"""

    def fake_get(url, **_kw):
        if "og.png" in url:
            import requests
            raise requests.exceptions.HTTPError("500")
        return _mock_response(text=html)

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        assert fetch_thumbnail("https://example.com/article") is None


def test_fetch_thumbnail_returns_none_when_image_undecodable():
    """HTML succeeds, image fetch succeeds, but bytes aren't an image."""
    html = """<html><head>
      <meta property="og:image" content="https://example.com/og.png">
    </head></html>"""

    def fake_get(url, **_kw):
        if "og.png" in url:
            return _mock_response(content=b"not an image")
        return _mock_response(text=html)

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        assert fetch_thumbnail("https://example.com/article") is None


def test_safe_get_follows_public_redirect():
    """Public URL -> 302 -> another public URL succeeds (follows once)."""
    from flexlog.services.link_thumbnails import _safe_get

    call_count = {"n": 0}
    def fake_get(url, **_kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            resp = MagicMock()
            resp.status_code = 302
            resp.headers = {"Location": "https://example.com/dest"}
            resp.close = MagicMock()
            return resp
        else:
            return _mock_response(text="<html><title>dest</title></html>")

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        resp = _safe_get("https://example.com/start", timeout=5.0, headers={})
    assert resp is not None
    assert call_count["n"] == 2


def test_safe_get_blocks_redirect_to_private_ip():
    """Public URL -> 302 -> 169.254.169.254 is rejected. The second
    requests.get should NEVER be called (the safety check fires first)."""
    from flexlog.services.link_thumbnails import _safe_get

    def fake_gethostbyname(host):
        # First call (start): public IP. Second call (target): metadata.
        return "93.184.216.34" if "start" in host or host == "example.com" else "169.254.169.254"

    call_count = {"n": 0}
    def fake_get(url, **_kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            resp = MagicMock()
            resp.status_code = 302
            resp.headers = {"Location": "http://metadata.example/foo"}
            resp.close = MagicMock()
            return resp
        # If we get here, the SSRF guard FAILED.
        raise AssertionError("requests.get was called for the redirect target")

    with patch("socket.gethostbyname", side_effect=fake_gethostbyname), \
         patch("requests.get", side_effect=fake_get):
        resp = _safe_get("https://example.com/start", timeout=5.0, headers={})
    assert resp is None
    assert call_count["n"] == 1  # Only the first request was made


def test_safe_get_caps_redirect_chain():
    """Redirect chain > _MAX_REDIRECTS aborts."""
    from flexlog.services.link_thumbnails import _safe_get, _MAX_REDIRECTS

    call_count = {"n": 0}
    def fake_get(url, **_kw):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 302
        resp.headers = {"Location": f"https://example.com/hop{call_count['n']}"}
        resp.close = MagicMock()
        return resp

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        resp = _safe_get("https://example.com/start", timeout=5.0, headers={})

    assert resp is None
    # Made exactly _MAX_REDIRECTS + 1 requests before giving up
    # (initial + _MAX_REDIRECTS redirects)
    assert call_count["n"] == _MAX_REDIRECTS + 1


def test_safe_get_returns_none_on_unsafe_initial_url():
    """Initial URL fails safety check -> no requests.get call at all."""
    from flexlog.services.link_thumbnails import _safe_get

    with patch("socket.gethostbyname", return_value="10.0.0.5"), \
         patch("requests.get", side_effect=AssertionError("should not be called")):
        resp = _safe_get("http://internal/x", timeout=5.0, headers={})
    assert resp is None


def test_safe_get_returns_none_on_4xx():
    """Non-redirect non-2xx -> raise_for_status fires -> return None."""
    from flexlog.services.link_thumbnails import _safe_get

    def fake_get(url, **_kw):
        resp = MagicMock()
        resp.status_code = 404
        resp.headers = {}
        resp.close = MagicMock()
        resp.raise_for_status = MagicMock(
            side_effect=requests.exceptions.HTTPError("404")
        )
        return resp

    import requests
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        resp = _safe_get("https://example.com/x", timeout=5.0, headers={})
    assert resp is None
