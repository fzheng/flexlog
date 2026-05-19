"""After set-password, the encrypted DB must not contain a vestigial
`auth` table. Earlier versions created one with no reader; M5 removes it."""
from __future__ import annotations


def test_setup_does_not_create_auth_table(csrf_authed_client, csrf_db_session):
    """The conftest `csrf_authed_client` fixture goes through the same
    set_password path that production uses. Verify the dead table is
    gone from the schema."""
    from sqlalchemy import text
    rows = csrf_db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='auth'")
    ).all()
    assert rows == [], (
        "Expected no `auth` table in fresh setup DB, but found one. "
        "M5 should have removed the CREATE TABLE in setup_bp.set_password."
    )
