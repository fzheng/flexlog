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
_IMAGE_LOAD_TIMEOUT_MS = 8_000    # max wait for forced image loads after scroll-prime
_VIEWPORT_WIDTH = 1280
_VIEWPORT_HEIGHT = 800
_TARGET_MAX_WIDTH = 640
_JPEG_QUALITY = 85


# Run in the page: force lazy/async images to load, then resolve once
# every <img> has either finished loading or errored. Most modern sites
# gate hero/feature images behind IntersectionObserver — they only load
# on scroll. We auto-scroll to the bottom in chunks (firing every
# observer), flip loading="lazy" → "eager" + decoding="sync" so images
# off-DOM-tree also fetch, scroll back to top, and resolve when every
# img.complete is true (or the per-image timeout fires).
_PRIME_IMAGES_JS = """
async ({ timeoutMs }) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // 1. Auto-scroll to bottom in chunks to trip IntersectionObserver
  //    lazy-loaders. Step is half the viewport height; small wait
  //    between steps so observer callbacks can fire.
  const step = Math.max(200, Math.floor(window.innerHeight / 2));
  let y = 0;
  const maxY = document.documentElement.scrollHeight;
  while (y < maxY) {
    window.scrollTo(0, y);
    y += step;
    await sleep(80);
  }
  window.scrollTo(0, 0);
  await sleep(120);

  // 2. Force-eager every <img> + <source>. Some libraries swap src on
  //    intersection — flipping the attributes here makes those load
  //    even though we're back at the top.
  const imgs = Array.from(document.images);
  for (const img of imgs) {
    try {
      if (img.loading === 'lazy') img.loading = 'eager';
      img.decoding = 'sync';
      // data-src / data-srcset swap (common lazy patterns)
      const ds = img.getAttribute('data-src');
      if (ds && !img.src) img.src = ds;
      const dss = img.getAttribute('data-srcset');
      if (dss && !img.srcset) img.srcset = dss;
    } catch (_) {}
  }

  // 3. Wait for each image to settle. Resolve on load OR error OR
  //    timeout, so one broken image can't hang the whole screenshot.
  const wait = (img) => new Promise((resolve) => {
    if (img.complete && img.naturalWidth > 0) { resolve(); return; }
    const done = () => {
      img.removeEventListener('load', done);
      img.removeEventListener('error', done);
      resolve();
    };
    img.addEventListener('load', done);
    img.addEventListener('error', done);
    setTimeout(done, timeoutMs);
  });
  await Promise.all(imgs.map(wait));

  // 4. Wait for webfonts so text doesn't FOUT in the screenshot.
  try { await document.fonts.ready; } catch (_) {}
}
"""


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

                # Force lazy/async images to load: scroll the full page
                # to fire IntersectionObserver callbacks, flip lazy attrs
                # to eager, wait for each <img> to settle, wait for
                # webfonts. Best-effort — if the JS fails we screenshot
                # whatever the page rendered.
                try:
                    page.evaluate(
                        _PRIME_IMAGES_JS,
                        {"timeoutMs": _IMAGE_LOAD_TIMEOUT_MS},
                    )
                except PlaywrightError:
                    pass

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
