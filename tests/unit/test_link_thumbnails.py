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
        get_mock.return_value.__enter__.return_value = _mock_response(
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
        get_mock.return_value.__enter__.return_value = _mock_response(text=big_html)
        assert _fetch_html("https://example.com/x") is None


def test_fetch_html_returns_none_on_4xx():
    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get") as get_mock:
        resp = _mock_response(text="not found", status=404)
        import requests
        resp.raise_for_status = MagicMock(
            side_effect=requests.exceptions.HTTPError("404")
        )
        get_mock.return_value.__enter__.return_value = resp
        assert _fetch_html("https://example.com/x") is None
