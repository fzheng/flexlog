"""Rate limit: 5/hour/IP on POST /. The 6th attempt returns 429."""
from __future__ import annotations

import pytest


@pytest.fixture
def rate_limited_app(monkeypatch, tmp_data_dir):
    """Spin up a fresh app with rate limiting enabled."""
    monkeypatch.setenv("FLEXLOG_RATE_LIMIT", "1")
    # Clear any prior limiter state from earlier tests in the session
    from flexlog.web.rate_limit import _reset_for_testing
    _reset_for_testing()
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    yield app
    _reset_for_testing()


def test_post_root_rate_limit_kicks_at_6th_attempt(rate_limited_app):
    client = rate_limited_app.test_client()
    # 5 attempts should all succeed (303/200 on wrong password — not 429)
    for i in range(5):
        resp = client.post("/", data={"q": "wrong-password-x" + str(i)})
        assert resp.status_code != 429, f"attempt {i+1} hit rate limit early"
    # 6th attempt: 429
    resp = client.post("/", data={"q": "wrong-password-6"})
    assert resp.status_code == 429


def test_rate_limit_off_by_default(client):
    """With FLEXLOG_RATE_LIMIT unset, the existing test fixture's app
    has no Limiter — POST / 10 times in a row, none return 429."""
    for i in range(10):
        resp = client.post("/", data={"q": "wrong-password-" + str(i)})
        assert resp.status_code != 429
