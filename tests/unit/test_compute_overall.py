"""compute_overall: weighted-average math, edge cases, return-None paths."""
from __future__ import annotations

import json

from flexlog.config_loader import RatingDimension
from flexlog.services.sessions import compute_overall


def _dim(rid, weight, enabled=True):
    return RatingDimension(
        id=rid, label=rid.title(), description=None,
        enabled=enabled, sortable=True, weight=weight,
    )


def test_compute_overall_weighted_average():
    dims = [_dim("a", 0.5), _dim("b", 0.3), _dim("c", 0.2)]
    stored = json.dumps({"a": 4, "b": 5, "c": 3})
    # 4*0.5 + 5*0.3 + 3*0.2 = 2.0 + 1.5 + 0.6 = 4.1
    assert compute_overall(stored, dims) == 4.1


def test_compute_overall_single_dim():
    dims = [_dim("a", 1.0)]
    stored = json.dumps({"a": 5})
    assert compute_overall(stored, dims) == 5.0


def test_compute_overall_missing_value_treated_as_zero():
    """A new session is required to set every dim, but legacy / partial
    data treats missing as 0 so the overall is well-defined."""
    dims = [_dim("a", 0.5), _dim("b", 0.5)]
    stored = json.dumps({"a": 4})  # b missing
    # 4 * 0.5 + 0 * 0.5 = 2.0
    assert compute_overall(stored, dims) == 2.0


def test_compute_overall_clamps_out_of_range_values():
    """A value > 5 (impossible via the star UI but possible via hand-edited
    data) clamps to 5 rather than producing an overall > 5."""
    dims = [_dim("a", 1.0)]
    stored = json.dumps({"a": 99})
    assert compute_overall(stored, dims) == 5.0


def test_compute_overall_clamps_negative_to_zero():
    dims = [_dim("a", 1.0)]
    stored = json.dumps({"a": -3})
    assert compute_overall(stored, dims) == 0.0


def test_compute_overall_disabled_dims_excluded():
    dims = [_dim("a", 0.7), _dim("b", 0.3), _dim("c", 0.5, enabled=False)]
    stored = json.dumps({"a": 4, "b": 5, "c": 1})  # c value present but disabled
    # Only a + b count
    assert compute_overall(stored, dims) == 4 * 0.7 + 5 * 0.3


def test_compute_overall_returns_none_for_empty_json():
    dims = [_dim("a", 1.0)]
    assert compute_overall(None, dims) is None
    assert compute_overall("", dims) is None


def test_compute_overall_returns_none_for_no_enabled_dims():
    dims = [_dim("a", 1.0, enabled=False)]
    stored = json.dumps({"a": 4})
    assert compute_overall(stored, dims) is None


def test_compute_overall_returns_none_for_malformed_json():
    dims = [_dim("a", 1.0)]
    assert compute_overall("not json", dims) is None
    assert compute_overall(json.dumps([1, 2, 3]), dims) is None  # not a dict


def test_compute_overall_ignores_non_int_values():
    """Stored value of a wrong type contributes 0 rather than crashing."""
    dims = [_dim("a", 0.5), _dim("b", 0.5)]
    stored = json.dumps({"a": "garbage", "b": 4})
    assert compute_overall(stored, dims) == 4 * 0.5
