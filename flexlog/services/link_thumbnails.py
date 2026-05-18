"""Open Graph image / favicon fetcher for SessionLink thumbnails.

Public API: fetch_thumbnail(url) -> bytes | None

Every failure path returns None. The caller (services.sessions
_fetch_and_store_thumbnail) treats None as "no thumbnail" without
blocking the session save.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


_UA = (
    "Mozilla/5.0 (compatible; flexlog-link-preview/1.0; "
    "+https://github.com/fzheng/flexlog)"
)
_HTML_TIMEOUT_S = 5.0
_IMAGE_TIMEOUT_S = 5.0
_MAX_REDIRECTS = 3
_MAX_HTML_BYTES = 1 * 1024 * 1024     # 1 MiB
_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MiB
_TARGET_MAX_WIDTH = 400
_JPEG_QUALITY = 85


def _is_safe_url(url) -> bool:
    """Reject non-http(s) schemes, private IPs, loopback, link-local,
    multicast, and reserved address ranges. Resolves the hostname via
    socket.gethostbyname; DNS failures return False."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        ip_str = socket.gethostbyname(host)
    except (socket.gaierror, OSError, UnicodeError):
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    return True
