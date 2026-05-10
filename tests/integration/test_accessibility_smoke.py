"""Lightweight regression tests for accessibility basics."""
from __future__ import annotations
import re


def test_skip_to_content_link_present(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert 'class="skip-link"' in body
    assert 'href="#main"' in body
    assert 'id="main"' in body


def test_dashboard_sort_select_has_label(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    # The sort select must have a label associated by `for="sort"`.
    assert re.search(r'<label[^>]+for="sort"', body)
    assert 'name="sort"' in body


def test_visually_hidden_class_defined(app):
    css_path = app.static_folder + "/css/main.css"
    with open(css_path) as f:
        css = f.read()
    assert ".visually-hidden" in css
    assert ".skip-link" in css
