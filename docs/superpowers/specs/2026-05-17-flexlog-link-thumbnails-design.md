# M8 — Link Thumbnails (Open Graph image auto-fetch)

**Status:** Design (draft, awaiting user review)
**Date:** 2026-05-17
**Version target:** v0.5.0
**Branches affected:** main

---

## 1. Goal

When a user saves a session with one or more links, the server fetches each link's Open Graph image (or favicon as fallback), downloads it, stores it encrypted via the existing media pipeline, and associates it with the `SessionLink` via the already-present `thumbnail_media_id` column. The session detail page already renders the thumbnail from that column — the template wiring is unchanged.

The result: link rows on the detail page show a rich preview thumbnail next to the URL, the same way Twitter/Slack/Discord render link cards.

**Scope:**

1. New module `flexlog/services/link_thumbnails.py` with one public function `fetch_thumbnail(url) -> bytes | None`. Pure I/O — fetch the URL, parse the HTML for `<meta property="og:image">` (twitter:image fallback, favicon fallback), download the image, resize + transcode, return JPEG bytes. Returns `None` on any failure.
2. Wire into `_replace_links` in `flexlog/services/sessions.py`: for each new-or-changed URL submitted on save, call `fetch_thumbnail` → push bytes through the existing `upload_to_media_file` pipeline (encrypt + dedup) → set `SessionLink.thumbnail_media_id` to the returned MediaFile id.
3. HTTP safety: 5s timeout per fetch, max 3 redirects, max 10 MB response body, realistic User-Agent string, reject private/loopback/link-local IPs (SSRF guard).
4. Image processing: resize to ≤400px wide (preserve aspect), transcode to JPEG q=85 before storage. Same Pillow stack the HEIC pipeline already uses.

**Out of scope:** async/background fetching, page screenshots, refresh-thumbnail button, automatic backfill for pre-feature links (user re-saves to populate), per-user opt-out toggle.

## 2. `fetch_thumbnail` service module

New module `flexlog/services/link_thumbnails.py`. Pure function — no Flask, no DB, no encryption knowledge. Inputs a URL, returns JPEG bytes or `None`.

```python
def fetch_thumbnail(url: str) -> bytes | None:
    """Return JPEG bytes for the link's thumbnail, or None on any failure.

    Tries in order:
      1. Open Graph image (<meta property="og:image">)
      2. Twitter card image (<meta name="twitter:image">)
      3. Favicon (<link rel="icon"> or /favicon.ico)

    Network constraints:
      - 5s total timeout per fetch (HTML + image, separate budgets)
      - Max 3 redirects
      - Max 10 MB response body
      - Rejects private / loopback / link-local IPs (SSRF guard)
      - Realistic User-Agent string

    Image processing:
      - Resize to max 400px wide, preserve aspect
      - Transcode to JPEG q=85
      - Returns bytes ready for the upload_to_media_file pipeline
    """
```

### Internal pipeline

1. **URL validation** (`_is_safe_url(url) -> bool`): parse with `urllib.parse.urlparse`. Require scheme in `{"http", "https"}`. Resolve hostname via `socket.gethostbyname`. Use `ipaddress.ip_address` to check `is_private`, `is_loopback`, `is_link_local`, `is_multicast`, `is_reserved`. Reject any of those. IPv6 covered by the same `ipaddress` API.
2. **HTML fetch** (`_fetch_html(url) -> BeautifulSoup | None`): `requests.get(url, timeout=5, allow_redirects=True, stream=True)` with `headers={"User-Agent": _UA}` and a guarded redirect chain (max 3, each redirect target re-passed through `_is_safe_url`). Read at most 1 MB of body. Parse with `BeautifulSoup(html, "html.parser")` — no `lxml` dependency.
3. **Image URL extraction** (`_extract_image_url(soup, base_url) -> str | None`): walk in order — og:image → twitter:image → `<link rel="icon">` (or `apple-touch-icon`) → fallback to `<scheme>://<host>/favicon.ico`. Resolve relative URLs against `base_url` via `urllib.parse.urljoin`.
4. **Image fetch** (`_fetch_image(image_url) -> bytes | None`): same safety constraints + max 10 MB body. Streams response; aborts on the first chunk that pushes past the cap.
5. **Image processing** (`_to_jpeg(raw_bytes) -> bytes | None`): `PIL.Image.open(BytesIO(raw_bytes))`. If `img.mode` is not RGB/L/CMYK, convert to RGB. If width > 400, resize to (400, height × 400/width) via `Image.Resampling.LANCZOS`. Save as JPEG q=85, optimize=True. Return the resulting bytes.

### Constants

```python
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
```

### Dependencies

Add to `pyproject.toml`:

```toml
"requests>=2.31,<3.0",
"beautifulsoup4>=4.12,<5.0",
```

`Pillow` is already a dep (M7 HEIC support).

### Error handling

Every failure path returns `None`. No exceptions propagate to the caller. Specific paths:

| Path | Result |
|---|---|
| URL parse error / unsupported scheme | `None` |
| DNS lookup failure | `None` |
| Private / loopback / link-local IP | `None` |
| Connection refused / timeout | `None` |
| HTTP 4xx / 5xx | `None` |
| HTML > 1 MB | `None` (truncate-then-fail; the page is likely garbage) |
| No image found in HTML AND no /favicon.ico | `None` |
| Image > 10 MB | `None` |
| Pillow can't decode image | `None` |
| Any unhandled `Exception` | `None` (try/except guards the whole pipeline) |

The point is: a failed thumbnail must NEVER break a session save.

## 3. Wiring into `_replace_links`

Current behavior in `flexlog/services/sessions.py`:

```python
def _replace_links(
    db: Session, session_row: SessionRow, urls: list[str],
    preserve_thumbnails: list[str | None] | None = None,
) -> None:
    ...
```

The `preserve_thumbnails` parameter is a relic from M5's manual-upload UI. M6+ never passes it from the route handlers. **Remove it.**

New signature + behavior:

```python
def _replace_links(db: Session, session_row: SessionRow, urls: list[str]) -> None:
    """Replace the session's links with the submitted URLs. For each URL
    that's new or changed, fetch its og:image and store as MediaFile.
    Unchanged URLs keep their existing thumbnail."""
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

Callers `create_session` and `update_session` invoke `_replace_links`. `create_session` already calls it as `_replace_links(db, session_row, link_urls)` and needs no change. **`update_session` currently passes `preserve_thumbnails=existing_thumbs`** (a hand-built position-keyed list) — drop that argument; the new URL-keyed preservation inside `_replace_links` supersedes it. Also delete the `existing_thumbs = [...]` line above the call since it's no longer used.

This is a strict UX improvement: the old position-keyed preservation lost thumbnails when the user reordered links, because positions shifted. URL-keyed preservation correctly keeps each thumbnail attached to its URL across reorders.

### `_fetch_and_store_thumbnail` helper

```python
def _fetch_and_store_thumbnail(db: Session, url: str) -> str | None:
    """Fetch the link's og:image, push through upload_to_media_file
    (dedup + encrypt), return the MediaFile id. Silent on any failure."""
    from flexlog.services.link_thumbnails import fetch_thumbnail
    from flexlog.services.media import upload_to_media_file
    from werkzeug.datastructures import FileStorage
    from urllib.parse import urlparse
    import io

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
        # Encryption / disk / DB error — swallow; the link saves without
        # a thumbnail rather than failing the whole session save.
        return None
```

### Dedup

`upload_to_media_file` already short-circuits on SHA-256 match. If two sessions link to the same article and the page's og:image bytes are identical, the second save reuses the existing MediaFile row. Free of charge.

### URL-change semantics

Editing a link's URL counts as a new URL — its old thumbnail is no longer associated. The new URL gets a fresh fetch. The old thumbnail's MediaFile may become orphan; the existing library orphan-cleanup handles it.

## 4. Detail page rendering

**No template changes.** `flexlog/templates/_partials/link_row_display.html` already renders:

```jinja
{% if link.thumbnail_media_id and link_thumbnails and link.id in link_thumbnails %}
  <img class="link-thumb-image"
       src="{{ url_for('media.serve', file_key=link_thumbnails[link.id].file_key) }}"
       alt="" loading="lazy">
{% endif %}
```

`sessions_bp.detail` already builds the `link_thumbnails` dict.

### CSS

Verify `.link-thumb-image` styling renders sensibly. Expected: ~80px × 60px, inline left of the link text, rounded corners. If the existing CSS doesn't deliver this, append:

```css
.link-display { display: flex; align-items: center; gap: 0.6rem; }
.link-display .link-thumb-image {
  width: 80px; height: 60px; object-fit: cover;
  border-radius: 4px; flex-shrink: 0;
}
```

(Adjust only if the live page looks broken; if existing CSS already handles it, leave alone.)

## 5. Error handling summary

| Scenario | Behavior |
|---|---|
| DNS failure / timeout / 4xx-5xx during fetch | `fetch_thumbnail` returns `None`; link saves without thumbnail |
| Private IP / SSRF attempt | Rejected in `_is_safe_url`; returns `None` |
| HTML has no og:image and no favicon | Returns `None` |
| Image fetch succeeds but Pillow can't decode | Returns `None` |
| Image > 10 MB | Returns `None` (streaming check aborts mid-fetch) |
| `upload_to_media_file` raises (disk full, etc.) | `_fetch_and_store_thumbnail` swallows; link saves without thumbnail |
| User saves N links, K fail to fetch | Save succeeds; (N-K) thumbnails populated |

No flash messages. No error pages. Best-effort. A failed thumbnail must never break a session save.

## 6. Testing strategy

≥85% coverage gate stays enforced.

### New unit tests (`tests/unit/test_link_thumbnails.py`)

Mock `requests.get` entirely (no real network calls):

- `test_extracts_og_image` — HTML with `<meta property="og:image">` returns a fetch URL → image bytes → JPEG out.
- `test_twitter_image_fallback` — HTML with `<meta name="twitter:image">` but no og:image → returns Twitter image.
- `test_favicon_fallback_link_rel` — HTML with `<link rel="icon" href="/favicon.png">` but no og:image / twitter:image.
- `test_favicon_fallback_default` — HTML with no image meta at all → fetches `<scheme>://<host>/favicon.ico`.
- `test_returns_none_when_no_image_anywhere` — HTML has nothing AND /favicon.ico 404s.
- `test_rejects_private_ip` — URL resolves to 192.168.1.5 → returns None without ANY HTTP call.
- `test_rejects_loopback` — `http://127.0.0.1/foo` → None.
- `test_rejects_link_local` — `http://169.254.169.254/foo` → None (AWS metadata service).
- `test_rejects_non_http_scheme` — `file:///etc/passwd`, `ftp://...`, `data:...` → None.
- `test_timeout_returns_none` — mock raises `requests.Timeout` → None.
- `test_oversized_html_truncated` — mocked response yields > 1 MB → None.
- `test_oversized_image_truncated` — mocked image response > 10 MB → None.
- `test_pillow_decode_failure` — image bytes are garbage → None.
- `test_resizes_wide_image` — input PNG 2000×1000 → output JPEG ≤ 400 wide preserving aspect (≤400×200).
- `test_preserves_small_image` — input 200×150 → output 200×150 (no upscale).

### New integration tests (`tests/integration/test_link_thumbnails_e2e.py`)

Monkey-patch `flexlog.services.sessions.fetch_thumbnail` (NOT `requests`) so we can inject deterministic JPEG bytes:

- `test_save_with_link_creates_thumbnail` — POST a session with one link → MediaFile row exists with media_type='photo' → SessionLink.thumbnail_media_id is set → detail page renders `<img src="/media/...">`.
- `test_thumbnail_fetch_failure_does_not_block_save` — `fetch_thumbnail` returns None → save still succeeds → SessionLink.thumbnail_media_id is None → detail page renders link without `<img>`.
- `test_unchanged_url_keeps_thumbnail` — Save a session with link X → update_session with same link X → fetch_thumbnail NOT called again → MediaFile unchanged.
- `test_changed_url_refetches` — Save link X → update_session changes it to link Y → fetch_thumbnail called for Y, NOT for X.
- `test_two_sessions_same_link_dedup` — Save session A with link L → save session B with link L → same MediaFile row reused (one file on disk).

## 7. Files touched

**New:**
- `flexlog/services/link_thumbnails.py` — the fetcher.
- `tests/unit/test_link_thumbnails.py` — unit tests (mock requests).
- `tests/integration/test_link_thumbnails_e2e.py` — end-to-end via `fetch_thumbnail` monkey-patch.

**Modified:**
- `flexlog/services/sessions.py` — `_replace_links` signature change (drop `preserve_thumbnails`), new `_fetch_and_store_thumbnail` helper, wired into both `create_session` and `update_session` flows (which already call `_replace_links`).
- `pyproject.toml` — add `requests` + `beautifulsoup4`, bump version to 0.5.0.
- `flexlog/static/css/main.css` — `.link-display` + `.link-thumb-image` styles (if not already adequate).
- `README.md` — v0.5.0 changelog + add a privacy asterisk to "no third-party network requests" noting that link-thumbnail fetches contact each linked host once.

**Deleted:** none.

## 8. Rollout

- Ships as v0.5.0.
- No DB migration. No config schema change.
- README v0.5.0 section documents the new outbound-network behavior.
- Pre-feature links (saved before this ships) stay un-thumbnailed until the user re-saves their session.

## 9. Privacy note

The README's "no third-party network requests" promise was about the FRONTEND not pulling CDN assets. M8 introduces SERVER-side outbound HTTP — but only to hosts the user explicitly added to a session, and only at save time. The same site that hosts the link can already see when the user CLICKS the link in a browser; M8 also lets it see when the user saves a session containing it.

For deployments behind Tailscale Funnel or a similar tunnel, the link host sees the home/Pi's egress IP, not the user's location. For a fully local deployment, the link host sees the user's home IP. Document both cases in the README.

## 10. Open questions

None. All decisions are pinned.
