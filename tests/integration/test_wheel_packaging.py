"""Built wheels must ship every Jinja template the app references.

The previous package-data glob `templates/*.html` was non-recursive and
silently omitted nested templates (landing/, people/, sessions/, setup/,
errors/, _partials/). Anyone installing flexlog via the wheel got a
broken app — first render hit TemplateNotFound."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.slow
def test_built_wheel_contains_every_template(tmp_path):
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    # Build a wheel into tmp_path/dist
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", str(REPO_ROOT), "-w", str(out_dir)],
        check=True,
        capture_output=True,
    )
    wheels = list(out_dir.glob("flexlog-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    wheel = wheels[0]

    # Names in the wheel
    with zipfile.ZipFile(wheel) as zf:
        wheel_files = set(zf.namelist())

    # Every *.html in flexlog/templates/ on disk must be in the wheel
    src_templates = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "flexlog" / "templates").rglob("*.html")
    )
    assert src_templates, "sanity: source tree has templates"

    missing = [t for t in src_templates if t not in wheel_files]
    assert not missing, (
        f"wheel is missing these templates:\n  "
        + "\n  ".join(missing)
    )
