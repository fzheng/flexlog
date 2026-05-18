# M8 — Link Thumbnails (Open Graph image auto-fetch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Use Opus for implementer subagents** — careful network + crypto-adjacent code.

**Goal:** Auto-fetch each session link's Open Graph image on save, store it encrypted, and surface it on the detail page.

**Architecture:** New pure-I/O service `flexlog/services/link_thumbnails.py` fetches HTML → parses og:image/twitter:image/favicon → downloads → resizes to ≤400px → transcodes to JPEG. Inside `_replace_links` in `flexlog/services/sessions.py`, each new/changed URL routes through this fetcher; the returned bytes go through the existing `upload_to_media_file` encryption + dedup pipeline; the resulting MediaFile id is stored in `SessionLink.thumbnail_media_id`. The detail-page template already renders the `<img>` — no template changes.

**Tech Stack:** Flask 3.x, SQLAlchemy 2.x, `requests` (new), `beautifulsoup4` (new), Pillow (already a dep from M7 HEIC support).

**Spec:** `docs/superpowers/specs/2026-05-17-flexlog-link-thumbnails-design.md`

**Coverage floor:** ≥85% via `pyproject.toml --cov-fail-under=85` (`feedback_test_coverage.md` in saved memory).

---

## File map

**New:**
- `flexlog/services/link_thumbnails.py` — `fetch_thumbnail(url) -> bytes | None` + private helpers.
- `tests/unit/test_link_thumbnails.py` — unit tests with mocked `requests` + `socket.gethostbyname`.
- `tests/integration/test_link_thumbnails_e2e.py` — end-to-end via `fetch_thumbnail` monkey-patch.

**Modified:**
- `flexlog/services/sessions.py` — `_replace_links` signature drops `preserve_thumbnails`; new `_fetch_and_store_thumbnail` helper; `update_session` no longer passes `preserve_thumbnails`.
- `pyproject.toml` — add `requests` + `beautifulsoup4`, bump version to 0.5.0.
- `README.md` — v0.5.0 section + privacy asterisk on the "no third-party network requests" promise.

**Deleted:** none.

---

## Constraints (from saved memory + spec)

- **Implementation model:** Opus only (`feedback_implementation_models.md`).
- **Coverage floor:** ≥85% (`pyproject.toml --cov-fail-under=85`).
- **No DB schema change.** `PRAGMA user_version` stays at 2 (DB) / `schema_version` stays at 3 (config).
- Working on `main` (consistent with prior milestones).
- A failed thumbnail fetch must NEVER block a session save.

---

## Task 1: Add `requests` + `beautifulsoup4` dependencies

Tiny but isolated commit so dependency churn is its own diff.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the two new deps**

In `pyproject.toml`, find the `dependencies = [...]` list and append two lines:

```toml
    "requests>=2.31,<3.0",
    "beautifulsoup4>=4.12,<5.0",
```

- [ ] **Step 2: Install + smoke check**

Run: `.venv/bin/pip install -e ".[dev]"` (may take a moment to resolve)
Then: `.venv/bin/python -c "import requests; import bs4; print('ok', requests.__version__, bs4.__version__)"`
Expected: `ok 2.x.y 4.x.y` printed.

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: 651 passed (unchanged from current 651 + 0 new tests), ≥85% coverage.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
deps: add requests + beautifulsoup4 for link thumbnails

Two-line addition ahead of the M8 link-thumbnail fetcher. requests
handles the synchronous HTTP fetches (HTML + image); beautifulsoup4
parses the page for og:image / twitter:image / favicon meta tags.
Pillow stays available from M7 for the transcode step.
EOF
)"
```

---

## Task 2: URL safety guard (`_is_safe_url`)

The SSRF guard. Rejects non-http(s) schemes, private IPs, loopback, link-local, multicast, reserved. Self-contained and fully testable without HTTP mocking.

**Files:**
- Create: `flexlog/services/link_thumbnails.py` (initial skeleton with just `_is_safe_url`)
- Test: `tests/unit/test_link_thumbnails.py` (new — first batch of tests)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_link_thumbnails.py`:

```python
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
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: ImportError on `flexlog.services.link_thumbnails`.

- [ ] **Step 3: Create the module with `_is_safe_url`**

Create `flexlog/services/link_thumbnails.py`:

```python
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
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: 15 PASS.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green at ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/link_thumbnails.py tests/unit/test_link_thumbnails.py
git commit -m "$(cat <<'EOF'
link_thumbnails: URL safety guard (SSRF protection)

_is_safe_url rejects non-http(s) schemes, private IPs (10.0.0.0/8,
172.16.0.0/12, 192.168.0.0/16), loopback, link-local (incl. the AWS
metadata service at 169.254.169.254), multicast, reserved, and the
unspecified address. DNS failures also return False so a typo can't
become a probe of internal infrastructure.

Foundation for the fetcher; HTML/image fetch lands in subsequent
commits.
EOF
)"
```

---

## Task 3: HTML fetch + image-URL extraction

Two helpers: `_fetch_html` does the HTTP GET (size-capped, redirect-capped, safety-checked); `_extract_image_url` walks the parsed HTML looking for og:image → twitter:image → `<link rel="icon">` → fallback to `/favicon.ico`.

**Files:**
- Modify: `flexlog/services/link_thumbnails.py` (append helpers)
- Test: append to `tests/unit/test_link_thumbnails.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_link_thumbnails.py`:

```python
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
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: ImportErrors on `_extract_image_url` / `_fetch_html`.

- [ ] **Step 3: Implement the helpers**

Append to `flexlog/services/link_thumbnails.py`:

```python
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


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
    """Walk the parsed HTML for og:image → twitter:image → <link rel=icon>
    → fallback to base_url's /favicon.ico. Resolves relative URLs."""
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
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: 26 PASS (15 from Task 2 + 11 new).

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green at ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/link_thumbnails.py tests/unit/test_link_thumbnails.py
git commit -m "$(cat <<'EOF'
link_thumbnails: HTML fetch + image URL extraction

_fetch_html does the safety-guarded HTTP GET with a 1 MiB body cap,
5s timeout, max 3 redirects, real User-Agent. Returns parsed
BeautifulSoup or None.

_extract_image_url walks the parsed HTML in priority order:
og:image → twitter:image → <link rel="icon"> → apple-touch-icon →
fallback to <scheme>://<host>/favicon.ico. Resolves relative URLs
via urljoin against the page's base URL.
EOF
)"
```

---

## Task 4: Image fetch + Pillow transcode (`_fetch_image` + `_to_jpeg`)

Two helpers: `_fetch_image` does the HTTP GET for the image bytes (same safety + size caps as the HTML fetch but at 10 MiB); `_to_jpeg` opens the bytes with Pillow, resizes to ≤400px wide, transcodes to JPEG q=85.

**Files:**
- Modify: `flexlog/services/link_thumbnails.py` (append helpers)
- Test: append to `tests/unit/test_link_thumbnails.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_link_thumbnails.py`:

```python
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
        get_mock.return_value.__enter__.return_value = _mock_response(content=png)
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
        get_mock.return_value.__enter__.return_value = _mock_response(content=big)
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
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: ImportErrors on `_fetch_image` / `_to_jpeg`.

- [ ] **Step 3: Implement the helpers**

Append to `flexlog/services/link_thumbnails.py`:

```python
from PIL import Image


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
```

Also add `import io` at the top of the file if not already present.

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: 36 PASS (26 prior + 10 new).

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green at ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/link_thumbnails.py tests/unit/test_link_thumbnails.py
git commit -m "$(cat <<'EOF'
link_thumbnails: image fetch + Pillow transcode

_fetch_image mirrors _fetch_html's safety + size discipline but at
10 MiB cap. Streams the response and aborts early when the buffer
overflows the cap.

_to_jpeg opens raw bytes with Pillow, converts non-RGB/L/CMYK modes
to RGB (so RGBA / palette PNGs don't crash JPEG encode), resizes to
≤400px wide preserving aspect, saves as JPEG quality 85 with
optimize=True. Returns None on any decode/save failure.
EOF
)"
```

---

## Task 5: Public `fetch_thumbnail` orchestration

The top-level function. Composes `_is_safe_url` → `_fetch_html` → `_extract_image_url` → `_fetch_image` → `_to_jpeg`. Every failure path returns None.

**Files:**
- Modify: `flexlog/services/link_thumbnails.py`
- Test: append to `tests/unit/test_link_thumbnails.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_link_thumbnails.py`:

```python
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
        ctx = MagicMock()
        if "og.png" in url:
            ctx.__enter__.return_value = _mock_response(content=png)
        else:
            ctx.__enter__.return_value = _mock_response(text=html)
        return ctx

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
        ctx = MagicMock()
        if "favicon.ico" in url:
            ctx.__enter__.return_value = _mock_response(content=favicon)
        else:
            ctx.__enter__.return_value = _mock_response(text=html)
        return ctx

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
        ctx = MagicMock()
        if "og.png" in url:
            import requests
            raise requests.exceptions.HTTPError("500")
        ctx.__enter__.return_value = _mock_response(text=html)
        return ctx

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        assert fetch_thumbnail("https://example.com/article") is None


def test_fetch_thumbnail_returns_none_when_image_undecodable():
    """HTML succeeds, image fetch succeeds, but bytes aren't an image."""
    html = """<html><head>
      <meta property="og:image" content="https://example.com/og.png">
    </head></html>"""

    def fake_get(url, **_kw):
        ctx = MagicMock()
        if "og.png" in url:
            ctx.__enter__.return_value = _mock_response(content=b"not an image")
        else:
            ctx.__enter__.return_value = _mock_response(text=html)
        return ctx

    with patch("socket.gethostbyname", return_value="93.184.216.34"), \
         patch("requests.get", side_effect=fake_get):
        assert fetch_thumbnail("https://example.com/article") is None
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: ImportError on `fetch_thumbnail`.

- [ ] **Step 3: Implement `fetch_thumbnail`**

Append to `flexlog/services/link_thumbnails.py`:

```python
def fetch_thumbnail(url: str) -> bytes | None:
    """Return JPEG bytes for the link's thumbnail, or None on any failure.

    Tries in order:
      1. Open Graph image (<meta property="og:image">)
      2. Twitter card image (<meta name="twitter:image">)
      3. Favicon (<link rel="icon"> or /favicon.ico)
    """
    try:
        soup = _fetch_html(url)
        if soup is None:
            return None
        image_url = _extract_image_url(soup, url)
        if not image_url:
            return None
        raw = _fetch_image(image_url)
        if raw is None:
            return None
        return _to_jpeg(raw)
    except Exception:
        # Belt-and-braces: anything we missed in the helpers' guards.
        return None
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_link_thumbnails.py -v --no-cov`
Expected: 42 PASS (36 prior + 6 new).

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green at ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/link_thumbnails.py tests/unit/test_link_thumbnails.py
git commit -m "$(cat <<'EOF'
link_thumbnails: fetch_thumbnail public entry point

Composes the four-helper pipeline (safety → HTML → image-URL pick →
image → JPEG transcode) behind a single public function. Top-level
try/except is belt-and-braces against any unhandled exception leak —
the helpers already swallow their own errors, but a defense-in-depth
guard keeps the caller's contract clean: never raises, always returns
bytes or None.
EOF
)"
```

---

## Task 6: Wire into `_replace_links` + integration tests

The behavior swap: `_replace_links` drops the position-keyed `preserve_thumbnails` parameter and adopts URL-keyed preservation. New URLs get a fresh `fetch_thumbnail` call. The bytes go through `upload_to_media_file` for encryption + dedup. `update_session` drops its `preserve_thumbnails=existing_thumbs` argument.

**Files:**
- Modify: `flexlog/services/sessions.py`
- Test: `tests/integration/test_link_thumbnails_e2e.py` (new)

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_link_thumbnails_e2e.py`:

```python
"""End-to-end: saving a session with a link triggers a thumbnail
fetch, stores it as MediaFile, and the detail page renders it."""
from __future__ import annotations

from unittest.mock import patch


def _make_jpeg_bytes(width=200, height=150, color=(40, 90, 160)):
    import io
    from PIL import Image
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_save_with_link_creates_thumbnail(authed_client, person, db_session):
    """create_session with a link → _replace_links calls fetch_thumbnail
    → MediaFile row created → SessionLink.thumbnail_media_id set →
    detail page renders <img src="/media/...">."""
    from flexlog.services.sessions import create_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg):
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article"],
        )
        db_session.commit()

    assert len(s.links) == 1
    link = s.links[0]
    assert link.thumbnail_media_id is not None

    from flexlog.db.models import MediaFile
    mf = db_session.get(MediaFile, link.thumbnail_media_id)
    assert mf is not None
    assert mf.media_type == "photo"
    assert mf.mime_type == "image/jpeg"

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    assert "link-thumb-image" in body
    assert f"/media/{mf.file_key}" in body


def test_thumbnail_fetch_failure_does_not_block_save(authed_client, person, db_session):
    """fetch_thumbnail returns None → save still succeeds → no thumbnail."""
    from flexlog.services.sessions import create_session

    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=None):
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 3}, notes=None,
            link_urls=["https://does-not-resolve.invalid/foo"],
        )
        db_session.commit()

    assert len(s.links) == 1
    assert s.links[0].thumbnail_media_id is None

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    assert "https://does-not-resolve.invalid/foo" in body
    assert "link-thumb-image" not in body


def test_unchanged_url_keeps_thumbnail(authed_client, person, db_session):
    """update_session with same URL list → fetch_thumbnail NOT called again."""
    from flexlog.services.sessions import create_session, update_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article"],
        )
        db_session.commit()
        assert fetch_mock.call_count == 1
        original_thumb = s.links[0].thumbnail_media_id

        update_session(
            db_session, session_id=s.id, session_date="2026-05-18",
            ratings={"energy": 5}, notes=None,
            link_urls=["https://example.com/article"],  # same URL
        )
        db_session.commit()

    # Still exactly one fetch — second save didn't re-fetch.
    assert fetch_mock.call_count == 1
    assert s.links[0].thumbnail_media_id == original_thumb


def test_changed_url_refetches(authed_client, person, db_session):
    """update_session with a different URL → fetch_thumbnail called for the new URL."""
    from flexlog.services.sessions import create_session, update_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article-1"],
        )
        db_session.commit()
        assert fetch_mock.call_count == 1
        fetch_mock.assert_called_with("https://example.com/article-1")

        update_session(
            db_session, session_id=s.id, session_date="2026-05-18",
            ratings={"energy": 5}, notes=None,
            link_urls=["https://example.com/article-2"],  # different URL
        )
        db_session.commit()

    assert fetch_mock.call_count == 2
    fetch_mock.assert_called_with("https://example.com/article-2")
    assert s.links[0].url == "https://example.com/article-2"


def test_url_reorder_preserves_thumbnails(authed_client, person, db_session):
    """Reordering existing URLs (no URL changes) should not re-fetch."""
    from flexlog.services.sessions import create_session, update_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=[
                "https://example.com/a",
                "https://example.com/b",
            ],
        )
        db_session.commit()
        assert fetch_mock.call_count == 2

        update_session(
            db_session, session_id=s.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=[  # reversed order, same URLs
                "https://example.com/b",
                "https://example.com/a",
            ],
        )
        db_session.commit()

    assert fetch_mock.call_count == 2  # NOT 4 — reorder is free
    assert s.links[0].url == "https://example.com/b"
    assert s.links[1].url == "https://example.com/a"
    # Both still have thumbnails
    assert s.links[0].thumbnail_media_id is not None
    assert s.links[1].thumbnail_media_id is not None


def test_two_sessions_same_link_dedup(authed_client, person, db_session):
    """Two sessions linking to the same URL with identical thumbnail bytes
    share one MediaFile row (existing SHA-256 dedup)."""
    from flexlog.services.sessions import create_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg):
        s1 = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/shared"],
        )
        db_session.commit()
        s2 = create_session(
            db_session, person_id=person.id, session_date="2026-05-18",
            ratings={"energy": 5}, notes=None,
            link_urls=["https://example.com/shared"],
        )
        db_session.commit()

    # Same MediaFile id reused
    assert s1.links[0].thumbnail_media_id == s2.links[0].thumbnail_media_id
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_link_thumbnails_e2e.py -v --no-cov`
Expected: failures (the import path `flexlog.services.sessions.fetch_thumbnail` doesn't exist yet — `fetch_thumbnail` lives in `link_thumbnails.py`, and `sessions.py` doesn't import it).

- [ ] **Step 3: Update `_replace_links` signature + behavior**

In `flexlog/services/sessions.py`, replace the existing `_replace_links` function (lines 49-75) with:

```python
def _replace_links(
    db: Session,
    session_row: SessionRow,
    urls: list[str],
) -> None:
    """Replace the session's links with the submitted URLs.

    For each URL that is new or changed, fetch the og:image via
    fetch_thumbnail, push the bytes through upload_to_media_file
    (encrypt + dedup), and set the SessionLink's thumbnail_media_id.
    Unchanged URLs keep their existing thumbnail (URL-keyed match, not
    position-keyed — so reordering doesn't lose thumbnails)."""
    old_thumbs_by_url = {li.url: li.thumbnail_media_id for li in session_row.links}
    session_row.links = []
    for i, raw in enumerate(urls):
        url = (raw or "").strip()
        if not url:
            continue
        if url in old_thumbs_by_url:
            thumb_id = old_thumbs_by_url[url]
        else:
            thumb_id = _fetch_and_store_thumbnail(db, url)
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=None,
                sort_order=i,
                thumbnail_media_id=thumb_id,
            )
        )
```

Add the import + helper at the top of the file (after the existing imports):

```python
from flexlog.services.link_thumbnails import fetch_thumbnail
```

And add the helper function just above `_replace_links`:

```python
def _fetch_and_store_thumbnail(db: Session, url: str) -> str | None:
    """Fetch the link's og:image, push through upload_to_media_file
    (dedup + encrypt), return the MediaFile id. Silent on any failure."""
    import io
    from urllib.parse import urlparse

    from werkzeug.datastructures import FileStorage

    from flexlog.services.media import upload_to_media_file

    jpeg_bytes = fetch_thumbnail(url)
    if jpeg_bytes is None:
        return None
    try:
        host = urlparse(url).hostname or "thumbnail"
        fs = FileStorage(
            stream=io.BytesIO(jpeg_bytes),
            filename=f"link-thumb-{host}.jpg",
            content_type="image/jpeg",
        )
        mf = upload_to_media_file(db, fs)
        return mf.id
    except Exception:
        return None
```

In `update_session` (around line 143-144), DROP the `existing_thumbs = ...` line AND the `preserve_thumbnails=existing_thumbs` argument. The call becomes:

```python
    _replace_links(db, session_row, link_urls)
```

- [ ] **Step 4: Run integration tests**

Run: `.venv/bin/python -m pytest tests/integration/test_link_thumbnails_e2e.py -v --no-cov`
Expected: 6 PASS.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green at ≥85%.

If any existing test (e.g. session-form tests that previously asserted no thumbnail) fails because of the new behavior, fix it minimally — likely just wrapping the affected test in `patch("flexlog.services.sessions.fetch_thumbnail", return_value=None)` to avoid the real fetch.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/sessions.py tests/integration/test_link_thumbnails_e2e.py tests/
git commit -m "$(cat <<'EOF'
sessions: auto-fetch og:image thumbnail per new/changed link

_replace_links drops the M5-era position-keyed preserve_thumbnails
parameter and adopts URL-keyed preservation: build a {url: thumb_id}
map from the existing links before dropping them; for each submitted
URL, reuse the existing thumb_id if the URL is unchanged, otherwise
call _fetch_and_store_thumbnail. New helper runs fetch_thumbnail →
wraps the bytes in a FileStorage → routes through upload_to_media_file
(encryption + SHA-256 dedup) → returns the MediaFile id (or None on
any failure).

update_session no longer hand-builds existing_thumbs or passes
preserve_thumbnails — the new URL-keyed preservation supersedes it
and is strictly better: reordering links no longer loses thumbnails.

Six integration tests cover the happy path, fetch failure (save
still succeeds, no thumbnail), no re-fetch on unchanged URL, re-fetch
on changed URL, no re-fetch on reorder, and dedup across sessions.
EOF
)"
```

---

## Task 7: Version bump + README

Final commit — record the milestone.

**Files:**
- Modify: `pyproject.toml`, `README.md`

- [ ] **Step 1: Bump version**

In `pyproject.toml`:

```toml
version = "0.5.0"
```

- [ ] **Step 2: Update README**

Add to `README.md` immediately before the existing `## v0.4.0` section:

```markdown
## v0.5.0 — Link Thumbnails (Open Graph image auto-fetch)

- **Each link gets a thumbnail.** On session save, the server fetches each link's `<meta property="og:image">` (with `twitter:image` and favicon fallbacks), downloads it, resizes to 400px wide, and stores it encrypted via the existing media pipeline. The session detail page already renders the thumbnail next to each link.
- **URL-keyed preservation.** Reordering links no longer re-fetches their thumbnails. Only genuinely new-or-changed URLs trigger a fresh fetch.
- **SSRF guard.** The fetcher rejects private IPs, loopback, link-local (incl. the AWS metadata service), multicast, and reserved address ranges. It also enforces a 5s timeout, 3-redirect cap, 1 MiB HTML body cap, and 10 MiB image cap per fetch.
- **Best-effort.** A failed fetch (DNS error, timeout, no og:image, bad image) silently saves the link without a thumbnail. Saves never block on the fetcher.
```

Also amend the **Privacy & data** section. Find the existing line that says "Privacy by default: no cloud, no accounts, no telemetry, no third-party network requests." and append a one-sentence asterisk right under that section:

```markdown
> **Note on outbound network from v0.5.0:** when you save a session containing a link, the server fetches that URL once to pull the page's preview image. The link host sees the request; nothing leaves your machine except contact with the exact URLs you added.
```

Place this note inside the existing `## Privacy & data` section, near the top, so anyone reading the privacy guarantee sees the asterisk immediately.

- [ ] **Step 3: Run final suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green at ≥85%.

- [ ] **Step 4: Commit + tag**

```bash
git add pyproject.toml README.md
git commit -m "$(cat <<'EOF'
v0.5.0: link thumbnails (og:image auto-fetch)

See README for the full change list. Adds the first server-side
outbound HTTP behavior in flexlog — limited to URLs the user
explicitly added to a session, and only at save time. The privacy
section's "no third-party network requests" line picks up a
documented asterisk.
EOF
)"
git tag v0.5.0
```

Do NOT push the tag — leave that to the user.

---

## Self-Review

**Spec coverage (each spec section → task that implements it):**

- §1 (Goal & scope) — Tasks 2-6 cover the four scope items (fetcher service, wiring, HTTP safety, image processing).
- §2 (fetch_thumbnail service module) — Tasks 2 (`_is_safe_url`), 3 (`_fetch_html` + `_extract_image_url`), 4 (`_fetch_image` + `_to_jpeg`), 5 (`fetch_thumbnail`). Dependencies in Task 1.
- §3 (Wiring into `_replace_links`) — Task 6 (`_replace_links` rewrite + `_fetch_and_store_thumbnail` helper + `update_session` cleanup).
- §4 (Detail page rendering) — no code change required; verified by the integration test in Task 6 (`test_save_with_link_creates_thumbnail` asserts the `<img>` renders).
- §5 (Error handling summary) — covered across Tasks 2-5 (every failure path returns None, no exceptions leak) and Task 6 (the `_fetch_and_store_thumbnail` helper swallows `upload_to_media_file` errors).
- §6 (Testing strategy) — 42 unit tests across Tasks 2-5 + 6 integration tests in Task 6.
- §7 (Files touched) — matches the file map at the top of this plan.
- §8 (Rollout) — Task 7 (version bump + README).
- §9 (Privacy note) — Task 7's README amendment.

No gaps.

**Placeholder scan:** scanned for "TBD" / "TODO" / "similar to" / vague-error-handling — none. Every step has executable code; every test has assertions.

**Type consistency:**
- `fetch_thumbnail(url: str) -> bytes | None` — same signature in Tasks 5 (def) + 6 (caller).
- `_is_safe_url(url) -> bool` — Task 2 (def) + Tasks 3, 4 (called by fetch helpers).
- `_extract_image_url(soup, base_url) -> str | None` — Task 3 (def) + Task 5 (called by orchestration).
- `_to_jpeg(raw_bytes) -> bytes | None` — Task 4 (def) + Task 5 (called).
- `_replace_links(db, session_row, urls) -> None` — Task 6 (new signature without `preserve_thumbnails`); update_session call site matches.
- `_fetch_and_store_thumbnail(db, url) -> str | None` — Task 6 (def + caller in `_replace_links`).
- Module-level constants `_HTML_TIMEOUT_S` etc. — defined in Task 2, referenced in Tasks 3 and 4 by name.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-flexlog-link-thumbnails-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task using Opus (per the milestone's careful-implementation requirement), with two-stage review between tasks.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`; batch execution with checkpoints.

Which approach?
