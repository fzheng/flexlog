"""Change-password flow tests."""
from __future__ import annotations


def test_change_password_form_renders(authed_client):
    resp = authed_client.get("/settings")
    body = resp.get_data(as_text=True)
    assert "current_password" in body
    assert "new_password" in body
    assert "Change password" in body or "change_password" in body.lower()


def test_change_password_happy_path(authed_client, admin_password, tmp_data_dir):
    new = "newpass1234"
    resp = authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": new,
        "new_password_confirm": new,
    })
    assert resp.status_code in (302, 303)

    # Verify new password unwraps successfully
    from flexlog.kdf_params import load_kdf_params
    from flexlog.crypto import argon2id_kek, aes_gcm_unwrap, Argon2Params
    kdf = load_kdf_params(tmp_data_dir / "kdf_params.json")
    params = Argon2Params(kdf.argon2_time, kdf.argon2_memory_kib, kdf.argon2_parallelism)
    kek_new = argon2id_kek(new, kdf.kek_salt, params)
    master = aes_gcm_unwrap(kek_new, kdf.kek_nonce, kdf.wrapped_master_key)
    assert len(master) == 32


def test_change_password_old_no_longer_works(authed_client, admin_password, tmp_data_dir):
    new = "newpass1234"
    authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": new,
        "new_password_confirm": new,
    })
    # Old password's KEK no longer unwraps
    from flexlog.kdf_params import load_kdf_params
    from flexlog.crypto import argon2id_kek, aes_gcm_unwrap, Argon2Params, InvalidPassword
    import pytest
    kdf = load_kdf_params(tmp_data_dir / "kdf_params.json")
    params = Argon2Params(kdf.argon2_time, kdf.argon2_memory_kib, kdf.argon2_parallelism)
    kek_old = argon2id_kek(admin_password, kdf.kek_salt, params)
    with pytest.raises(InvalidPassword):
        aes_gcm_unwrap(kek_old, kdf.kek_nonce, kdf.wrapped_master_key)


def test_change_password_wrong_current(authed_client):
    resp = authed_client.post("/settings/change-password", data={
        "current_password": "wrong-old",
        "new_password": "newpass1234",
        "new_password_confirm": "newpass1234",
    }, follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert "incorrect" in body.lower()


def test_change_password_mismatched_confirm(authed_client, admin_password):
    resp = authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": "newpass1234",
        "new_password_confirm": "different5678",
    }, follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert "match" in body.lower()


def test_change_password_too_short(authed_client, admin_password):
    resp = authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": "short",
        "new_password_confirm": "short",
    }, follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert "8" in body or "short" in body.lower()


def test_existing_data_still_readable_after_change_password(
    authed_client, admin_password, db_session
):
    """Master key is unchanged → existing media still readable, existing
    DB rows still queryable."""
    from flexlog.services.people import create_person
    create_person(db_session, alias="Persisted", tag_input="")
    db_session.commit()

    authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": "newpass1234",
        "new_password_confirm": "newpass1234",
    })

    # Dashboard still has the person
    from flexlog.db.models import Person
    db_session.expire_all()
    aliases = [p.alias for p in db_session.query(Person).all()]
    assert "Persisted" in aliases


# ---------------------------------------------------------------- error branches


def test_change_password_too_short(authed_client, admin_password):
    """New password under 8 chars → flash error, no change."""
    resp = authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": "short",
        "new_password_confirm": "short",
    }, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "at least 8 characters" in body or "at least 8" in body


def test_change_password_empty_new(authed_client, admin_password):
    """Empty new_password → flash error."""
    resp = authed_client.post("/settings/change-password", data={
        "current_password": admin_password,
        "new_password": "",
        "new_password_confirm": "",
    }, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "at least 8" in body


def test_change_password_unauthed_403(client):
    """No master key in app.config (unauthed) → 403."""
    resp = client.post("/settings/change-password", data={
        "current_password": "anything",
        "new_password": "newpass1234",
        "new_password_confirm": "newpass1234",
    })
    # Unauthed routes redirect to / via the auth gate (303)
    # before the change_password handler runs. Either 303 (redirected
    # by gate) or 403 (passed gate but no master key) is acceptable —
    # both prove the route refuses unauthed change-password.
    assert resp.status_code in (303, 403)
