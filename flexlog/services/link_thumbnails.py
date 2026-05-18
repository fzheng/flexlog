"""Open Graph image / favicon fetcher for SessionLink thumbnails.

Public API: fetch_thumbnail(url) -> bytes | None

Every failure path returns None. The caller (services.sessions
_fetch_and_store_thumbnail) treats None as "no thumbnail" without
blocking the session save.
"""
from __future__ import annotations

import io
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image


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


def _fetch_html(url: str) -> BeautifulSoup | None:
    """GET the URL with safety + size + redirect caps. Returns parsed
    BeautifulSoup or None on any failure."""
    if not _is_safe_url(url):
        return None
    try:
        with requests.get(
            url,
            timeout=_HTML_TIMEOUT_S,
            allow_redirects=True,
            stream=True,
            headers={"User-Agent": _UA, "Accept": "text/html,*/*;q=0.8"},
        ) as resp:
            resp.raise_for_status()
            # Read up to _MAX_HTML_BYTES + 1; if we hit the cap, give up.
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    buf.extend(chunk)
                    if len(buf) > _MAX_HTML_BYTES:
                        return None
            return BeautifulSoup(buf.decode("utf-8", errors="replace"), "html.parser")
    except (requests.RequestException, ValueError):
        return None


def _extract_image_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Walk the parsed HTML for og:image -> twitter:image -> <link rel=icon>
    -> fallback to base_url's /favicon.ico. Resolves relative URLs."""
    # 1. og:image
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return urljoin(base_url, og["content"].strip())
    # 2. twitter:image
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return urljoin(base_url, tw["content"].strip())
    # 3. <link rel="icon"> or apple-touch-icon
    for rel in ("icon", "shortcut icon", "apple-touch-icon"):
        link = soup.find("link", attrs={"rel": rel})
        if link and link.get("href"):
            return urljoin(base_url, link["href"].strip())
    # 4. Default favicon path on the same origin
    parsed = urlparse(base_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    return None


def _fetch_image(url: str) -> bytes | None:
    """GET the image URL with safety + size caps. Returns raw bytes or None."""
    if not _is_safe_url(url):
        return None
    try:
        with requests.get(
            url,
            timeout=_IMAGE_TIMEOUT_S,
            allow_redirects=True,
            stream=True,
            headers={"User-Agent": _UA, "Accept": "image/*"},
        ) as resp:
            resp.raise_for_status()
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    buf.extend(chunk)
                    if len(buf) > _MAX_IMAGE_BYTES:
                        return None
            return bytes(buf)
    except (requests.RequestException, ValueError):
        return None


def _to_jpeg(raw_bytes: bytes) -> bytes | None:
    """Open `raw_bytes` with Pillow, resize to ≤400px wide preserving
    aspect, transcode to JPEG q=85. Returns the JPEG bytes or None."""
    if not raw_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception:
        return None
    if img.mode not in ("RGB", "L", "CMYK"):
        img = img.convert("RGB")
    if img.width > _TARGET_MAX_WIDTH:
        new_height = max(1, round(img.height * _TARGET_MAX_WIDTH / img.width))
        img = img.resize(
            (_TARGET_MAX_WIDTH, new_height),
            Image.Resampling.LANCZOS,
        )
    out = io.BytesIO()
    try:
        img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    except Exception:
        return None
    return out.getvalue()
