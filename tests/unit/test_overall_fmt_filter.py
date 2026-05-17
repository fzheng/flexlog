"""Jinja filters: overall_fmt formats floats to 1 decimal (None → ''),
star_fill returns '★' * n + '☆' * (5 - n) for an int n in [0, 5]."""
from __future__ import annotations

from flexlog.web.filters import overall_fmt, star_fill


def test_overall_fmt_one_decimal():
    assert overall_fmt(4.32) == "4.3"
    assert overall_fmt(4.0) == "4.0"
    assert overall_fmt(0.05) == "0.1"  # rounded


def test_overall_fmt_none_returns_empty():
    assert overall_fmt(None) == ""


def test_overall_fmt_zero():
    assert overall_fmt(0.0) == "0.0"


def test_overall_fmt_five():
    assert overall_fmt(5.0) == "5.0"


def test_star_fill_zero():
    assert star_fill(0) == "☆☆☆☆☆"


def test_star_fill_three():
    assert star_fill(3) == "★★★☆☆"


def test_star_fill_five():
    assert star_fill(5) == "★★★★★"


def test_star_fill_clamps_out_of_range():
    assert star_fill(-1) == "☆☆☆☆☆"
    assert star_fill(7) == "★★★★★"


def test_star_fill_non_int_returns_all_empty():
    assert star_fill(None) == "☆☆☆☆☆"
    assert star_fill("not a number") == "☆☆☆☆☆"
