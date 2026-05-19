"""OpenAPI 3.0 spec drift detection.

The spec at `docs/openapi.yaml` is the source of truth for flexlog's
HTTP API surface. These tests:

1. Parse the spec and validate it against the OpenAPI 3.0 schema.
2. Compare the spec to Flask's `app.url_map` and fail on any drift —
   route added without docs, route removed but doc stale, HTTP method
   changed, auth annotation wrong.
3. Surface deprecated routes so the changelog can pick them up.

When a test fails, the fix is almost always to edit `docs/openapi.yaml`
before merging your route change. The spec lives alongside the code
precisely so this kind of drift can't ship.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "openapi.yaml"


# Routes that intentionally exist in app.url_map but are NOT user-facing
# API endpoints. Excluded from the coverage comparison.
_NON_API_ENDPOINTS = {
    "static",  # Framework-provided static serving — not a flexlog API.
}


# Routes documented as public (no session auth required). The test
# verifies these have `security: []` on every operation in the spec
# AND that they're in flexlog/auth.py's ALLOWED_UNAUTH_ENDPOINTS.
_EXPECTED_PUBLIC_ENDPOINTS = {
    "landing.index",
    "landing.submit",
    "setup.set_password_form",
    "setup.set_password",
    "setup.recover",
    "auth.logout",  # POST while unauthed is a harmless no-op — gate allows.
}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def spec() -> dict:
    """Parsed openapi.yaml as a dict. Module-scoped so the 50KB file
    parses once for the whole suite."""
    import yaml
    with SPEC_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def app_routes(tmp_path_factory) -> list[dict]:
    """Every Flask route as a list of {rule, methods, endpoint} dicts.
    Methods exclude HEAD/OPTIONS (auto-added by Flask for GET handlers).
    Static endpoint is filtered out.

    Uses a module-scoped MonkeyPatch context so FLEXLOG_DATA_DIR is set
    *and* reverted properly. The previous version of this fixture used
    `os.environ.setdefault(...)` which:
      a) was a no-op if the developer's shell already had the env set
         (could point flexlog at a real data dir), and
      b) leaked into other tests via `os.environ` mutation.
    """
    tmp_dir = tmp_path_factory.mktemp("openapi_app_routes")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FLEXLOG_DATA_DIR", str(tmp_dir))
        from flexlog.app import create_app
        app = create_app()
        out = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint in _NON_API_ENDPOINTS:
                continue
            methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
            out.append({
                "rule": rule.rule,
                "endpoint": rule.endpoint,
                "methods": methods,
            })
        return out


def _flask_rule_to_openapi_path(rule: str) -> str:
    """Translate Flask's `/people/<person_id>` syntax to OpenAPI's
    `/people/{person_id}` braces. Also normalises `<path:file_key>`
    (Flask's catch-all converter) to `{file_key}`."""
    # Handle `<converter:name>` and `<name>` both → `{name}`
    return re.sub(r"<(?:[^>:]+:)?([^>]+)>", r"{\1}", rule)


# ─────────────────────────────────────────────────────────────────────
# 1. Spec validity
# ─────────────────────────────────────────────────────────────────────


def test_openapi_spec_file_exists():
    assert SPEC_PATH.exists(), f"Missing OpenAPI spec at {SPEC_PATH}"


def test_openapi_spec_is_valid_openapi_3(spec):
    """Validate against the OpenAPI 3.0 schema. Catches malformed
    schemas, missing required fields, type errors."""
    from openapi_spec_validator import validate
    # Raises OpenAPIValidationError on failure; pytest surfaces it.
    validate(spec)


def test_openapi_spec_declares_version(spec):
    """The info.version field is what consumers pin against. Should
    match the pyproject.toml version."""
    import re
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m, "pyproject.toml has no version line"
    pyproject_version = m.group(1)
    assert spec["info"]["version"] == pyproject_version, (
        f"openapi.yaml info.version ({spec['info']['version']!r}) does "
        f"not match pyproject.toml version ({pyproject_version!r}). "
        f"Bump openapi.yaml when you tag a new release."
    )


# ─────────────────────────────────────────────────────────────────────
# 2. Coverage: spec ⊇ url_map (every route is documented)
# ─────────────────────────────────────────────────────────────────────


def test_every_flask_route_appears_in_spec(spec, app_routes):
    """A route in app.url_map without a corresponding entry in the spec
    is a doc gap. Fix by adding the path to docs/openapi.yaml."""
    spec_paths = set(spec.get("paths", {}).keys())
    undocumented = []
    for r in app_routes:
        openapi_path = _flask_rule_to_openapi_path(r["rule"])
        if openapi_path not in spec_paths:
            undocumented.append(
                f"  {'|'.join(r['methods']):8s}  {r['rule']}  -> {r['endpoint']}"
            )
    assert not undocumented, (
        "Routes exist in Flask's url_map but are NOT documented in "
        "docs/openapi.yaml. Add an entry per route before merging:\n"
        + "\n".join(undocumented)
    )


def test_every_method_on_route_is_documented(spec, app_routes):
    """A path is in the spec, but a method on it isn't. Common case:
    added POST to an existing GET-only route without updating the spec."""
    spec_paths = spec.get("paths", {})
    method_drift = []
    for r in app_routes:
        openapi_path = _flask_rule_to_openapi_path(r["rule"])
        path_item = spec_paths.get(openapi_path, {})
        for method in r["methods"]:
            spec_op = path_item.get(method.lower())
            if spec_op is None:
                method_drift.append(
                    f"  {method:7s} {openapi_path}  (endpoint {r['endpoint']})"
                )
    assert not method_drift, (
        "Methods exist on Flask routes but not in the spec. Add a "
        "section per missing method in docs/openapi.yaml:\n"
        + "\n".join(method_drift)
    )


# ─────────────────────────────────────────────────────────────────────
# 3. No-stale: url_map ⊇ spec (every documented path is real)
# ─────────────────────────────────────────────────────────────────────


def test_no_stale_paths_in_spec(spec, app_routes):
    """A path in the spec that no Flask route serves. Common case:
    removed a route but forgot to clean up the spec entry."""
    real_paths = {_flask_rule_to_openapi_path(r["rule"]) for r in app_routes}
    stale = []
    for spec_path in spec.get("paths", {}).keys():
        if spec_path not in real_paths:
            stale.append(f"  {spec_path}")
    assert not stale, (
        "Paths documented in docs/openapi.yaml have no matching Flask "
        "route. Remove these spec entries (or restore the route):\n"
        + "\n".join(stale)
    )


def test_no_stale_methods_in_spec(spec, app_routes):
    """A method documented under a path that the Flask route doesn't
    actually serve. Catches GET-removed-but-still-in-spec drift."""
    real_route_methods: dict[str, set[str]] = {}
    for r in app_routes:
        openapi_path = _flask_rule_to_openapi_path(r["rule"])
        real_route_methods.setdefault(openapi_path, set()).update(r["methods"])

    _OPENAPI_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
    stale = []
    for spec_path, path_item in spec.get("paths", {}).items():
        real_methods = real_route_methods.get(spec_path, set())
        for key in path_item.keys():
            if key.lower() not in _OPENAPI_METHODS:
                continue  # `parameters`, `summary`, etc. — skip non-method keys
            if key.upper() not in real_methods:
                stale.append(f"  {key.upper():7s} {spec_path}")
    assert not stale, (
        "Operations documented under paths that Flask doesn't actually "
        "serve. Remove the operation from docs/openapi.yaml or restore "
        "the handler:\n" + "\n".join(stale)
    )


# ─────────────────────────────────────────────────────────────────────
# 4. Auth annotations
# ─────────────────────────────────────────────────────────────────────


def test_public_endpoints_have_no_security(spec):
    """Routes documented as public (security: []) must match the
    ALLOWED_UNAUTH_ENDPOINTS allowlist exactly. Any drift here is a
    real security concern: a route that should be authed but is in
    the allowlist, OR a route that needs auth but is documented as
    public."""
    documented_public = set()
    for spec_path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            sec = op.get("security")
            if sec == []:  # explicit empty list = no auth required
                opid = op.get("operationId")
                if opid:
                    documented_public.add(opid)

    # Compare with the expected set + the runtime allowlist.
    extra = documented_public - _EXPECTED_PUBLIC_ENDPOINTS
    missing = _EXPECTED_PUBLIC_ENDPOINTS - documented_public
    assert not extra, (
        f"Operations marked `security: []` in the spec but not in the "
        f"expected public set: {sorted(extra)}. Either add to "
        f"_EXPECTED_PUBLIC_ENDPOINTS (and confirm they SHOULD be public) "
        f"or remove `security: []` from the operation."
    )
    assert not missing, (
        f"Operations expected to be public but missing `security: []` "
        f"in spec: {sorted(missing)}. Add `security: []` or update "
        f"the expected set."
    )


def test_public_endpoints_match_runtime_allowlist(spec):
    """Routes the spec says are public must also be in
    flexlog/auth.py's ALLOWED_UNAUTH_ENDPOINTS (or be `setup.*` which
    is allowlisted by prefix). Otherwise the auth gate will redirect
    them — the spec lies to consumers."""
    from flexlog.auth import ALLOWED_UNAUTH_ENDPOINTS

    public_in_spec = set()
    for path_item in spec.get("paths", {}).values():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            if op.get("security") == []:
                opid = op.get("operationId")
                if opid:
                    public_in_spec.add(opid)

    for endpoint in public_in_spec:
        # `setup.*` is allowed by prefix in the auth gate
        if endpoint.startswith("setup."):
            continue
        assert endpoint in ALLOWED_UNAUTH_ENDPOINTS, (
            f"Endpoint {endpoint!r} is marked public in openapi.yaml but "
            f"isn't in ALLOWED_UNAUTH_ENDPOINTS. The auth gate will "
            f"redirect requests away from it."
        )


def test_runtime_allowlist_endpoints_documented_as_public(spec, app_routes):
    """Inverse of the above: every endpoint in ALLOWED_UNAUTH_ENDPOINTS
    must be documented with `security: []` in the spec. This catches
    the case where a route is publicly reachable at runtime but the
    spec misleadingly claims it requires auth — the original drift
    test was unidirectional and missed this."""
    from flexlog.auth import ALLOWED_UNAUTH_ENDPOINTS

    # Endpoints in the allowlist that ALSO show up in url_map (skip
    # any allowlist entries for prefix-matched endpoints we don't
    # actually register, like a hypothetical `static`).
    real_endpoints = {r["endpoint"] for r in app_routes}
    allowlisted_and_routed = ALLOWED_UNAUTH_ENDPOINTS & real_endpoints

    # Build map: operationId -> security setting from spec.
    op_security: dict[str, object] = {}
    for path_item in spec.get("paths", {}).values():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            opid = op.get("operationId")
            if opid:
                op_security[opid] = op.get("security")  # None / [] / [...]

    missing_security = []
    for endpoint in sorted(allowlisted_and_routed):
        sec = op_security.get(endpoint)
        if sec != []:
            missing_security.append(
                f"  {endpoint}  (spec security: {sec!r})"
            )
    assert not missing_security, (
        "Endpoints in flexlog/auth.py:ALLOWED_UNAUTH_ENDPOINTS are "
        "publicly reachable at runtime but the spec does NOT mark "
        "them with `security: []`. Either update the spec to declare "
        "them public, or remove them from ALLOWED_UNAUTH_ENDPOINTS:\n"
        + "\n".join(missing_security)
    )


# ─────────────────────────────────────────────────────────────────────
# 5. operationId consistency
# ─────────────────────────────────────────────────────────────────────


def test_every_operation_has_unique_operation_id(spec):
    """operationId is the stable identifier — used by code generators
    and by these drift tests. Must be unique across the whole spec."""
    seen = {}
    for spec_path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            opid = op.get("operationId")
            assert opid, f"{method.upper()} {spec_path}: missing operationId"
            assert opid not in seen, (
                f"Duplicate operationId {opid!r}: "
                f"{seen[opid]} and {method.upper()} {spec_path}"
            )
            seen[opid] = f"{method.upper()} {spec_path}"


def test_operation_ids_match_flask_endpoints(spec, app_routes):
    """Each documented operationId should equal the Flask endpoint name
    of the matching route. Cheap drift check — renaming a handler
    surfaces here."""
    real_endpoints_by_path_method: dict[tuple[str, str], str] = {}
    for r in app_routes:
        openapi_path = _flask_rule_to_openapi_path(r["rule"])
        for m in r["methods"]:
            real_endpoints_by_path_method[(openapi_path, m.lower())] = r["endpoint"]

    mismatches = []
    for spec_path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            opid = op.get("operationId")
            expected = real_endpoints_by_path_method.get((spec_path, method))
            if expected and opid != expected:
                mismatches.append(
                    f"  {method.upper()} {spec_path}: "
                    f"operationId={opid!r}, Flask endpoint={expected!r}"
                )
    assert not mismatches, (
        "operationId(s) in openapi.yaml don't match Flask endpoint "
        "names. Rename one or the other:\n" + "\n".join(mismatches)
    )


# ─────────────────────────────────────────────────────────────────────
# 6. Deprecated-route surface (informational; doesn't fail the suite)
# ─────────────────────────────────────────────────────────────────────


def test_deprecated_operations_have_removal_version(spec):
    """If an operation is marked `deprecated: true`, it must also
    carry `x-removal-version: "X.Y.Z"` so the changelog can pick up
    the planned removal. (No operations are currently deprecated;
    this test is a forward-looking guard.)"""
    missing_removal_version = []
    for spec_path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            if op.get("deprecated"):
                if "x-removal-version" not in op:
                    missing_removal_version.append(
                        f"  {method.upper()} {spec_path}"
                    )
    assert not missing_removal_version, (
        "Operations marked deprecated must carry `x-removal-version: "
        "\"X.Y.Z\"` so the deprecation has a planned removal:\n"
        + "\n".join(missing_removal_version)
    )


# ─────────────────────────────────────────────────────────────────────
# 7. Tag hygiene
# ─────────────────────────────────────────────────────────────────────


def test_every_operation_has_at_least_one_tag(spec):
    """Tags group operations in tooling (Swagger UI, ReDoc). Every
    operation should declare at least one."""
    untagged = []
    for spec_path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            if not op.get("tags"):
                untagged.append(f"  {method.upper()} {spec_path}")
    assert not untagged, (
        "Operations missing `tags`:\n" + "\n".join(untagged)
    )


def test_all_used_tags_are_declared(spec):
    """Every tag referenced by an operation must have a definition in
    the top-level `tags:` list. Catches typos like `sesions` vs.
    `sessions`."""
    declared = {t["name"] for t in spec.get("tags", [])}
    referenced: set[str] = set()
    for path_item in spec.get("paths", {}).values():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue
            referenced.update(op.get("tags", []))
    undeclared = referenced - declared
    assert not undeclared, (
        f"Tags used by operations but missing a top-level `tags:` "
        f"declaration: {sorted(undeclared)}"
    )
