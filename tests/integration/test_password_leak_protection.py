"""Wrong-password POSTs whose `q` looks like PII (password / SSN / credit
card) must redirect to Google's homepage rather than google.com/search?q=...
The latter would leak the typed value to the URL bar, browser history,
Referer headers, and Google's logs."""
from __future__ import annotations

import pytest


def _post(client, q: str):
    """POST `q` to / and return the response without following redirects."""
    return client.post("/", data={"q": q})


# ----------------------------------------------------------- sensitive → homepage

@pytest.mark.parametrize("q", [
    "hunter2",                       # password-shape
    "Tr0ub4dor&3",                   # password-shape (symbols + mixed case)
    "iphone16",                      # password-shape (acceptable false positive)
    "123-45-6789",                   # SSN
    "123456789",                     # 9-digit SSN form
    "4111 1111 1111 1111",           # Visa test (Luhn-valid)
    "5500000000000004",              # Mastercard test (Luhn-valid)
])
def test_sensitive_q_redirects_to_google_homepage(client, q):
    resp = _post(client, q)
    assert resp.status_code == 303
    loc = resp.headers["Location"]
    assert loc == "https://www.google.com/", (
        f"sensitive q={q!r} leaked to Google search instead of homepage: {loc}"
    )


# ----------------------------------------------------------- non-sensitive → search

@pytest.mark.parametrize("q", [
    "pasta recipes",
    "weather",
    "best italian restaurants nyc",
    "how to make sourdough bread",
])
def test_nonsensitive_q_redirects_to_google_search(client, q):
    resp = _post(client, q)
    assert resp.status_code == 303
    loc = resp.headers["Location"]
    assert loc.startswith("https://www.google.com/search?"), (
        f"non-sensitive q={q!r} should hit /search?q=, got: {loc}"
    )
    # And the typed value appears in the query string (urlencoded)
    from urllib.parse import urlencode
    assert urlencode({"q": q}).split("=", 1)[1] in loc.split("?", 1)[1]
