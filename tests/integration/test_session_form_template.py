"""Smoke checks on the rewritten session form template."""
from __future__ import annotations


def test_new_form_has_csrf_meta_tag(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    assert '<meta name="csrf-token"' in body


def test_new_form_renders_per_kind_pending_lists(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    assert 'data-kind="photo"' in body
    assert 'data-kind="audio"' in body
    assert 'data-kind="video"' in body
    # Single-textbox link UI
    assert 'name="new_link_url"' in body
    # No legacy overall_score input
    assert 'name="overall_score"' not in body


def test_new_form_renders_rating_inputs_from_enabled_dims(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    # Default config has the energy dimension
    assert 'name="rating_energy"' in body


def test_session_form_js_is_served(authed_client):
    resp = authed_client.get("/static/js/session_form.js")
    assert resp.status_code == 200
    assert b"uploadOne" in resp.data
