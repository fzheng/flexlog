"""M3 regression: session cookie must carry HttpOnly + SameSite=Lax."""

def test_session_cookie_httponly_and_samesite(client):
    """Hit any endpoint that issues a session cookie and inspect the
    Set-Cookie header."""
    resp = client.get("/")
    # Flask's test client exposes Set-Cookie via resp.headers
    set_cookies = resp.headers.getlist("Set-Cookie")
    assert any("session=" in c for c in set_cookies), \
        f"no session cookie issued: {set_cookies}"
    session_line = next(c for c in set_cookies if "session=" in c)
    lower = session_line.lower()
    assert "httponly" in lower, f"session cookie missing HttpOnly: {session_line}"
    assert "samesite=lax" in lower, f"session cookie missing SameSite=Lax: {session_line}"


def test_session_cookie_config_set(app):
    """Belt and braces: the Flask config values are explicitly set."""
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is False
