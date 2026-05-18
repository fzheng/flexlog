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
