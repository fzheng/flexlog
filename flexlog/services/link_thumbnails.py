"""Page-screenshot thumbnail fetcher for SessionLink thumbnails.

Public API: fetch_thumbnail(url) -> bytes | None

Launches a headless Chromium via Playwright, navigates to the URL,
captures a viewport screenshot, resizes to ≤640px wide, and returns
the JPEG bytes. Every failure path returns None. The caller
(services.sessions._fetch_and_store_thumbnail) treats None as
"no thumbnail" without blocking the session save.
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import socket
from urllib.parse import urlparse

from PIL import Image


_NAV_TIMEOUT_MS = 15_000          # initial goto timeout
_NETWORKIDLE_TIMEOUT_MS = 8_000   # post-prime wait-for-idle (most lazy fetches done)
_SETTLE_DELAY_MS = 800            # post-load grace for JS-driven layout shifts
_VIEWPORT_WIDTH = 1280
_VIEWPORT_HEIGHT = 800
_TARGET_MAX_WIDTH = 640
_JPEG_QUALITY = 85

# When set, raw viewport PNG bytes get saved here for inspection.
# Useful for diagnosing why a thumbnail looks blank without the
# user having to re-run anything. e.g.
#     FLEXLOG_THUMBNAIL_DEBUG=/tmp/thumbs make run
_DEBUG_DIR_ENV = "FLEXLOG_THUMBNAIL_DEBUG"


# Force-eager every <img>: flip loading="lazy" → "eager", set
# decoding="sync", swap data-src/data-srcset onto src/srcset. Many lazy
# libraries swap attributes on intersection; this makes them load even
# without scrolling there. Runs synchronously so we can call without
# evaluate-promise plumbing.
_FORCE_EAGER_JS = """
() => {
  for (const img of document.images) {
    try {
      if (img.loading === 'lazy') img.loading = 'eager';
      img.decoding = 'sync';
      const ds = img.getAttribute('data-src');
      if (ds && !img.src) img.src = ds;
      const dss = img.getAttribute('data-srcset');
      if (dss && !img.srcset) img.srcset = dss;
    } catch (_) {}
  }
}
"""


def _save_debug_png(url: str, png_bytes: bytes) -> None:
    """If FLEXLOG_THUMBNAIL_DEBUG is set, dump the raw viewport PNG to
    <dir>/<host>-<sha8>.png so the user can inspect what Chromium
    actually captured. Best-effort; silent on any failure."""
    debug_dir = os.environ.get(_DEBUG_DIR_ENV)
    if not debug_dir or not png_bytes:
        return
    try:
        os.makedirs(debug_dir, exist_ok=True)
        host = (urlparse(url).hostname or "unknown").replace("/", "_")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        path = os.path.join(debug_dir, f"{host}-{digest}.png")
        with open(path, "wb") as f:
            f.write(png_bytes)
    except Exception:
        pass


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
    """Launch Chromium via Playwright, navigate to `url`, force lazy
    images to load, return the viewport PNG bytes. Returns None on any
    failure (DNS, timeout, JS crash, redirect to private IP, etc.).

    Strategy for getting lazy-loaded images to appear:
    1. goto with wait_until="load" (faster, doesn't require idle)
    2. Imperatively flip every <img>.loading from lazy to eager,
       swap data-src onto src — covers attribute-swap lazy patterns
    3. Take a full_page=True screenshot — Playwright internally scrolls
       through the entire document to stitch it, which trips every
       IntersectionObserver-based lazy-loader on the page. We discard
       the result; the side effect (images now loaded) is what we want.
    4. Scroll back to top, wait_for_load_state("networkidle") to let
       all the newly-fired image requests complete
    5. Settle delay for any post-load JS (cookie banners, crossfades)
    6. Final viewport screenshot

    Reuses no browser state — each call launches and closes its own
    Chromium. ~3-8s per call (longer than before because of the
    scroll-prime, but with usefully-loaded images)."""
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

                # Step 1: navigate. wait_until="load" fires when window.load
                # has fired (all initial resources). We don't need
                # networkidle here — the prime step + post-prime idle wait
                # handles lazy-loaded content.
                try:
                    page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="load")
                except PlaywrightError:
                    # Fall through with whatever has rendered.
                    pass

                # Safety: re-check final URL in case of redirects to
                # private IPs (initial URL was vetted by the caller).
                try:
                    final_url = page.url
                except PlaywrightError:
                    return None
                if final_url and final_url != url and not _is_safe_url(final_url):
                    return None

                # Step 2: flip lazy attrs eagerly.
                try:
                    page.evaluate(_FORCE_EAGER_JS)
                except PlaywrightError:
                    pass

                # Step 3: take a full-page screenshot purely as a primer.
                # Playwright scrolls the document height to stitch, which
                # trips IntersectionObserver lazy-loaders. Discard result.
                try:
                    page.screenshot(type="png", full_page=True)
                except PlaywrightError:
                    pass

                # Step 4: scroll back to top, wait for the lazy-image
                # requests to complete.
                try:
                    page.evaluate("window.scrollTo(0, 0)")
                except PlaywrightError:
                    pass
                try:
                    page.wait_for_load_state(
                        "networkidle", timeout=_NETWORKIDLE_TIMEOUT_MS
                    )
                except PlaywrightError:
                    pass

                # Step 5: brief settle for post-load layout shifts.
                try:
                    page.wait_for_timeout(_SETTLE_DELAY_MS)
                except PlaywrightError:
                    pass

                # Step 6: the actual screenshot.
                try:
                    png = page.screenshot(type="png", full_page=False)
                except PlaywrightError:
                    return None
                _save_debug_png(url, png)
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
