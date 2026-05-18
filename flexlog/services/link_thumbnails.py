"""Page-screenshot thumbnail fetcher for SessionLink thumbnails.

Public API: fetch_thumbnail(url) -> bytes | None

Launches a headless Chromium via Playwright, navigates to the URL,
captures a viewport screenshot, resizes to ≤640px wide, and returns
the JPEG bytes. Every failure path returns None. The caller
(services.sessions._fetch_and_store_thumbnail) treats None as
"no thumbnail" without blocking the session save.
"""
from __future__ import annotations

import io
import ipaddress
import socket
from urllib.parse import urlparse

from PIL import Image


_NAV_TIMEOUT_MS = 15_000          # generous: networkidle on chatty sites
_SETTLE_DELAY_MS = 800            # post-load grace for JS-driven layout shifts
_VIEWPORT_WIDTH = 1280
_VIEWPORT_HEIGHT = 800
_TARGET_MAX_WIDTH = 640
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


def _screenshot_url(url: str) -> bytes | None:
    """Launch Chromium via Playwright, navigate to `url`, capture a
    viewport-sized PNG screenshot, return the bytes. Returns None on any
    failure (DNS, timeout, JS crash, redirect to private IP, etc.).

    Reuses no browser state — each call launches and closes its own
    Chromium. ~1-3s per call after the first cold launch."""
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": _VIEWPORT_WIDTH, "height": _VIEWPORT_HEIGHT},
                )
                page = context.new_page()
                # Try networkidle (catches lazy images + JS rendering). If
                # the page never goes idle (long-polling, websockets), the
                # navigation timeout fires — but we still try to screenshot
                # whatever has rendered so far rather than abort the whole
                # fetch. Worst case: a partial-but-still-useful thumbnail.
                try:
                    page.goto(
                        url,
                        timeout=_NAV_TIMEOUT_MS,
                        wait_until="networkidle",
                    )
                except PlaywrightError:
                    # Fall through with whatever the page has so far.
                    pass

                # Defense: if Chromium followed a redirect to a private
                # IP, abort. (Initial URL was already safety-checked by
                # the caller; this catches redirect bypasses.)
                try:
                    final_url = page.url
                except PlaywrightError:
                    return None
                if final_url and final_url != url and not _is_safe_url(final_url):
                    return None

                # Brief settle for post-load JS that nudges layout (e.g.
                # cookie banners, hero images crossfading in).
                try:
                    page.wait_for_timeout(_SETTLE_DELAY_MS)
                except PlaywrightError:
                    pass

                try:
                    png = page.screenshot(type="png", full_page=False)
                except PlaywrightError:
                    return None
                return png
            finally:
                browser.close()
    except Exception:
        return None


def _to_jpeg(raw_bytes: bytes) -> bytes | None:
    """Open `raw_bytes` with Pillow, resize to ≤640px wide preserving
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


def fetch_thumbnail(url: str) -> bytes | None:
    """Return JPEG bytes for the link's thumbnail, or None on any failure.

    Captures a viewport screenshot of the page via headless Chromium,
    resizes to ≤640px wide, transcodes to JPEG q=85.
    """
    try:
        if not _is_safe_url(url):
            return None
        png = _screenshot_url(url)
        if png is None:
            return None
        return _to_jpeg(png)
    except Exception:
        return None
