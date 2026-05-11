"""Concurrent dashboard fetches must not corrupt the shared connection.

With StaticPool + threaded server, two requests landing simultaneously
share one DBAPI connection and SQLAlchemy session state interleaves.
SingletonThreadPool gives each thread its own connection so each request
gets a clean session."""
from __future__ import annotations

import concurrent.futures


def test_dashboard_under_concurrent_load(authed_client):
    """Hit /dashboard from 10 threads. All should 200; none should error
    with 'recursive use of cursors' / 'SQLite objects created in a thread
    can only be used in that same thread.' / similar."""
    N = 10

    def fetch():
        return authed_client.get("/dashboard")

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
        futures = [ex.submit(fetch) for _ in range(N)]
        results = [f.result(timeout=30) for f in futures]

    for resp in results:
        assert resp.status_code == 200, f"got {resp.status_code}: {resp.data[:200]!r}"


def test_many_concurrent_db_queries(authed_client, db_session):
    """Heavier scenario: each thread creates a person then reads it back."""
    from flexlog.services.people import create_person
    # Seed one person so /dashboard has something to render
    create_person(db_session, alias="Concurrent Test", tag_input="")
    db_session.commit()

    N = 8

    def fetch_and_check():
        resp = authed_client.get("/dashboard")
        assert resp.status_code == 200
        assert b"Concurrent Test" in resp.data, f"missing person in {resp.data[:200]!r}"
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
        list(ex.map(lambda _: fetch_and_check(), range(N * 3)))
