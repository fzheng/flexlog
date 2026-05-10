# flexlog — Fake Landing Page + Single-Password Auth — Design

**Status:** Approved 2026-05-09 (post-MVP).

**Goal:** Hide flexlog behind a Google-clone fake landing page. Anyone unauthenticated who visits any URL ends up at a fake search box; typing the admin password (matched by SHA-512 hash) logs the visitor in and reveals the real app; typing anything else 303-redirects to Google search results so the page looks like a generic "I clicked a vanity domain" toy. Sessions expire after 30 minutes of inactivity, on server restart, or on explicit logout.

**Threat model:** the URL gets discovered (typed, leaked in browser history, scanned by a port-scanning bot, etc.). A casual visitor must come away believing the site is a hobby search-redirect page, not a personal database with someone's name, photos, and notes. The password protects against a determined attacker only as well as its entropy — this is not a hardened public-facing system.

**Non-goals:** multi-user auth, RBAC, rate limiting, password reset flows, OAuth, OIDC, 2FA. Single-user local-only stays the rule (PRD §14.5).

---

## Threat model and what this design DOES NOT defend against

- **Brute-force guessing of the password.** No rate limiting in v1. Single-user local-only is the assumption; a public deployment needs additional protection (reverse proxy with fail2ban, a rate-limit middleware, or moving the app off the open internet).
- **Side-channel timing on the wider request.** Hash comparison itself uses `hmac.compare_digest`, but the redirect-to-Google response is shaped differently from the redirect-to-/dashboard response. A precise attacker observing response timing or shape could learn whether a guess was correct without seeing the cookie. The design accepts this — defending against it would require adding artificial delays, which makes the UX worse for the legitimate user without preventing a determined attacker from grinding offline against the hash file anyway (see next point).
- **Compromise of `$FLEXLOG_DATA_DIR/.env`.** The hash is in plaintext at rest; anyone with read access to the data dir can copy the hash and crack it offline. Mode 0600 on `.env` mitigates local-process attacks but does nothing against root, backup leaks, or filesystem snapshots. Choose a strong password.

These limits are deliberate. Listing them keeps the team honest about what we shipped.

---

## Components

### 1. `flexlog/auth.py` (new)

Session helpers + password verification. No Flask blueprint here — keeps the module testable without a request context.

```python
IDLE_TIMEOUT_SEC = 30 * 60  # 30 minutes

def is_authed(session, app_config) -> bool:
    """Return True iff session has a valid auth marker, the epoch matches
    app_config['AUTH_EPOCH'], and last_seen is within IDLE_TIMEOUT_SEC.
    Side effect: refreshes session['last_seen'] if all checks pass."""

def mark_authed(session, app_config) -> None:
    """Set session['authed']=True, ['epoch']=app_config['AUTH_EPOCH'],
    ['last_seen']=time.time(). Flask saves the session cookie at end of
    request — no explicit commit required."""

def mark_unauthed(session) -> None:
    """Pop authed/epoch/last_seen from session."""

def verify_password(typed: str, expected_hash_hex: str) -> bool:
    """Constant-time SHA-512 hex compare via hmac.compare_digest."""
```

### 2. `flexlog/app.py` (modify)

- Load `$FLEXLOG_DATA_DIR/.env` via `python-dotenv` (explicit path; do NOT use the implicit CWD search).
- Validate `FLEXLOG_ADMIN_PASSWORD_SHA512` at startup: must be a 128-char lowercase hex string. Fail loudly with a clear message + reference to `make hash-password` if missing/invalid.
- Generate `app.config['AUTH_EPOCH']` = `secrets.token_hex(16)` once per process. New value on every restart.
- Stash the validated hash on `app.config['ADMIN_PASSWORD_HASH']`.
- Register an `app.before_request` hook that gates every route. Allowlist (no auth needed): the landing endpoint (`landing.index`, GET + POST), the logout endpoint (`auth.logout`), and Flask's static endpoint. Everything else: if not `is_authed(session, app.config)` → 303 → `/`.

### 3. `flexlog/web/landing_bp.py` (new)

Two views on a single URL.

```
GET  /  -> if authed, 303 -> /dashboard
       -> else, render templates/landing/index.html
POST /  -> read form['q']
       -> if verify_password(q, app.config['ADMIN_PASSWORD_HASH']):
              mark_authed(session, app.config)
              return 303 -> /dashboard
       -> else:
              return 303 -> 'https://www.google.com/search?q=' + urlencode(q)
```

The `<form action="/" method="post">` has a CSRF token (Flask-WTF is already enabled). The CSRF cookie is set on the GET; the POST verifies. Empty `q` re-renders the page.

### 4. `flexlog/web/dashboard_bp.py` (modify)

Rename the existing root route from `/` to `/dashboard`. The endpoint name stays `home.home` to avoid breaking `url_for` calls scattered through templates — only the URL changes. Update `url_for('home.home')` consumers if needed (they still work — Flask resolves by endpoint name, not URL).

### 5. `flexlog/web/auth_bp.py` (new)

```
POST /logout -> mark_unauthed(session); 303 -> /
```

CSRF-protected. No GET handler — logout must be intentional, not navigable.

### 6. Templates

**`flexlog/templates/landing/index.html`** — fake search page. Centered brand mark ("flexlog" or whatever the app's `labels.app_name` says), single `<input name="q">`, two buttons: "Search" (submit) and "I'm Feeling Lucky" (submit; same handler — Google's behaviour but ours is identical for both, hides that the second button is decorative). Includes the CSRF token. Uses a dedicated `landing.css` (loaded via `{% block head %}`) so the fake page doesn't pull in any flexlog-specific styling that might give away the app's identity to a casual inspector.

**`flexlog/templates/_base.html`** — add Logout `<form>` button to the nav, only rendered when authed. The auth flag flows in via a `@app.context_processor` that returns `{'is_authed': True/False}`.

### 7. CSS

**`flexlog/static/css/landing.css`** — Google-clone styling. Centered viewport-height layout, big logo, single rounded input, two short grey buttons. No mention of "flexlog", "guest", "session", or any other app-specific noun in the rendered HTML beyond the brand mark in the title.

### 8. Makefile

`hash-password` target:

```makefile
hash-password:
	@$(BIN)/python -c 'import getpass, hashlib; print("FLEXLOG_ADMIN_PASSWORD_SHA512=" + hashlib.sha512(getpass.getpass("password: ").encode()).hexdigest())'
```

User runs it, types the password (no echo), copies the line into `$FLEXLOG_DATA_DIR/.env`.

### 9. `pyproject.toml`

Add `python-dotenv>=1.0,<2` to runtime dependencies.

### 10. `.gitignore`

Add a defensive `.env` entry. Even though the canonical location is `$FLEXLOG_DATA_DIR/.env` (outside the repo), this protects against developers accidentally creating one in the repo root.

### 11. `tests/conftest.py`

Add fixtures:

- `admin_password` — a static known plaintext, e.g. `"hunter2"`.
- `admin_password_hash` — its SHA-512 hex.
- Existing `tmp_data_dir` writes a `.env` containing `FLEXLOG_ADMIN_PASSWORD_SHA512=<admin_password_hash>` so `create_app()` picks it up.
- `authed_client(client)` — calls `client.post("/", data={"q": admin_password, "csrf_token": ...})` once, returns the same client now bearing the auth cookie.

---

## Session lifecycle (concrete)

| Event | Effect on session |
|---|---|
| Anonymous GET `/` | Cookie may be set for CSRF; no auth keys present |
| Correct password POST `/` | `session['authed']=True`, `['epoch']=AUTH_EPOCH`, `['last_seen']=now()` |
| Authed request | `is_authed()` checks all three; if pass, refresh `last_seen` |
| 30+ min idle | `is_authed()` clears session and returns False; user 303s to `/` |
| Server restart | New `AUTH_EPOCH`. Old cookies' epoch no longer matches → unauthed |
| POST `/logout` | `mark_unauthed()` pops all auth keys |

---

## Test plan (10 tests, `tests/integration/test_auth.py`)

1. **Fake landing renders for anonymous.** GET `/` → 200, contains the fake brand, contains a `<form action="/" method="post">` with a CSRF token. Body does NOT contain "Guests", "Add Interview", "Settings", or any other app noun.
2. **Wrong-password POST redirects to Google.** POST `/` with `q="hello world"` → 303, Location starts with `https://www.google.com/search?q=hello`.
3. **Empty `q` re-renders landing.** POST `/` with `q=""` → 200, fake page.
4. **Correct-password POST logs in.** POST `/` with `q=<admin_password>` → 303 to `/dashboard`. Follow it: 200, real dashboard.
5. **Protected route redirects when unauthed.** GET `/people/new` (no auth) → 303 → `/`.
6. **Protected route works when authed.** authed_client GET `/people/new` → 200.
7. **Idle expiration.** authed_client; monkeypatch `time.time()` to 31 min later; GET `/dashboard` → 303 → `/`.
8. **Restart epoch mismatch invalidates.** authed_client; mutate `app.config['AUTH_EPOCH']` to a new random value; GET `/dashboard` → 303 → `/`.
9. **Logout clears session.** authed_client POST `/logout` → 303 → `/`. Subsequent GET `/dashboard` → 303 → `/`.
10. **Missing env var fails startup.** delete `FLEXLOG_ADMIN_PASSWORD_SHA512` from env; `create_app()` raises with a clear message that mentions `make hash-password`.

Plus a unit test in `tests/unit/test_auth.py` for `verify_password` (correct password returns True; wrong returns False; constant-time path uses `hmac.compare_digest`).

---

## Existing test migration

About 30 integration test files use the `client` fixture and POST to protected routes. Each needs `client` → `authed_client` for the route-exercising calls (typically 1–10 lines per file).

The `authed_client` fixture handles the auth flow once. Two implementation choices:

1. **Real flow:** the fixture POSTs `/` with the correct password, asserts the redirect, and yields the now-authed client. Most realistic but slowest.
2. **Bypass via session helper:** the fixture opens a `client.session_transaction()` and writes the auth keys directly. Faster but doesn't exercise the login path.

We use **(2) bypass via session_transaction** for speed; the auth flow itself is covered by tests 1–4 of the dedicated test_auth.py. Total test runtime should stay under 10 seconds.

---

## Risk and rollback

**Risk:** medium. This change is pervasive — every existing route gains an auth gate, every existing test changes fixture. A bug here either locks the user out of their own app (unlikely but recoverable by editing the env) or quietly leaves a route unprotected (caught by tests; we add a "no test should access a protected route without authed_client" reviewer comment as a guard).

**Rollback:** `git revert` the implementation commits. Auth lives in three new modules + a startup check; reverting them returns the app to its pre-auth state. No data migration involved.

---

## Out of scope (deliberately)

- Rate limiting, lockout, fail2ban integration. Add when deploying public.
- Password rotation UX. Set new env, restart.
- Forgot-password / reset flow. Single-user; reset = edit the env.
- Multiple sessions / device list. Single-user; one cookie at a time is fine.
- Remember-me on the cookie. Strong session expiry is the point — opt-out would defeat it.
- "Show password while typing" toggle on the landing form. Would compromise the fake-page disguise.

---

## Estimated diff

~400 LOC new + ~80 LOC test churn across ~30 files. 4–5 commits, each of ~80 LOC except the bulk test migration commit.

---

**End of design.**
