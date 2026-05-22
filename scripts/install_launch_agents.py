#!/usr/bin/env python3
"""Install the three flexlog launchd user agents on macOS.

Renders the templates under scripts/launchd-templates/ with per-user
paths, writes them to ~/Library/LaunchAgents/, and loads each with
launchctl bootstrap.

Usage:
    python scripts/install_launch_agents.py            # interactive
    HEALTHCHECK_URL=https://... RCLONE_REMOTE=... \\
        python scripts/install_launch_agents.py        # non-interactive
"""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_DIR / "scripts" / "launchd-templates"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def render_template(template_path: Path, **values: str) -> str:
    """Read template_path and substitute every {{KEY}} with values[KEY].

    Raises KeyError if a template contains a placeholder for which no
    value was provided. This is intentional — silent fallthrough would
    leave a literal {{KEY}} in the rendered plist and break launchd."""
    text = Path(template_path).read_text(encoding="utf-8")
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return values[key]

    rendered = _PLACEHOLDER_RE.sub(_sub, text)
    if missing:
        raise KeyError(
            f"template {template_path.name} needs values for: "
            f"{sorted(set(missing))}"
        )
    return rendered


def _prompt_if_unset(env_var: str, prompt: str, default: str | None = None) -> str:
    """Read env_var, otherwise prompt. If a default is given and the user
    hits enter, use the default."""
    val = os.environ.get(env_var, "").strip()
    if val:
        return val
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    if not val and default:
        return default
    if not val:
        print(f"error: {env_var} is required", file=sys.stderr)
        sys.exit(2)
    return val


def _data_dir_default() -> str:
    return str(Path.home() / "Library" / "Application Support" / "flexlog")


def _log_dir_default() -> str:
    return str(Path.home() / "Library" / "Logs" / "flexlog")


def _install_one(name: str, rendered: str, dry_run: bool) -> Path:
    """Write rendered plist to LAUNCH_AGENTS_DIR/<name>.plist and load it.
    Returns the path written."""
    # Validate it parses BEFORE writing, so we never write garbage to
    # ~/Library/LaunchAgents (which launchd will then refuse).
    try:
        plistlib.loads(rendered.encode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"{name}: rendered plist is not valid: {e}") from e

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = LAUNCH_AGENTS_DIR / f"{name}.plist"
    if dry_run:
        print(f"  [dry-run] would write {dst}")
        return dst

    dst.write_text(rendered, encoding="utf-8")
    dst.chmod(0o644)
    print(f"  wrote {dst}")

    # If already loaded, bootout first so bootstrap doesn't error.
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(dst)],
        check=False, capture_output=True,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(dst)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"launchctl bootstrap {name} failed: "
            f"{result.stderr or result.stdout}"
        )
    print(f"  loaded {name}")
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Render templates + validate; don't write or load",
    )
    args = parser.parse_args()

    print("flexlog launchd installer")
    print(f"  repo:          {REPO_DIR}")

    data_dir = _prompt_if_unset(
        "FLEXLOG_DATA_DIR", "FLEXLOG_DATA_DIR", default=_data_dir_default(),
    )
    log_dir = _prompt_if_unset(
        "FLEXLOG_LOG_DIR", "FLEXLOG_LOG_DIR", default=_log_dir_default(),
    )
    healthcheck_url = _prompt_if_unset(
        "HEALTHCHECK_URL",
        "healthchecks.io ping URL (https://hc-ping.com/<uuid>)",
    )
    rclone_remote = _prompt_if_unset(
        "RCLONE_REMOTE",
        "rclone remote target (e.g. railway-backup:flexlog-home-backup)",
    )

    print(f"  data dir:      {data_dir}")
    print(f"  log dir:       {log_dir}")
    print(f"  healthcheck:   {healthcheck_url}")
    print(f"  rclone remote: {rclone_remote}")

    # Ensure data + log dirs exist before launchd tries to write to them
    if not args.dry_run:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        Path(log_dir).mkdir(parents=True, exist_ok=True)

    common = dict(
        FLEXLOG_REPO_DIR=str(REPO_DIR),
        FLEXLOG_DATA_DIR=data_dir,
        FLEXLOG_LOG_DIR=log_dir,
    )
    backup_extras = dict(
        HEALTHCHECK_URL=healthcheck_url,
        RCLONE_REMOTE=rclone_remote,
    )

    print("\nrendering + installing agents:")
    _install_one(
        "com.flexlog.app",
        render_template(TEMPLATES_DIR / "com.flexlog.app.plist.template", **common),
        args.dry_run,
    )
    _install_one(
        "com.flexlog.backup",
        render_template(
            TEMPLATES_DIR / "com.flexlog.backup.plist.template",
            **common, **backup_extras,
        ),
        args.dry_run,
    )
    _install_one(
        "com.flexlog.backup-prune",
        render_template(
            TEMPLATES_DIR / "com.flexlog.backup-prune.plist.template",
            FLEXLOG_REPO_DIR=str(REPO_DIR),
            FLEXLOG_LOG_DIR=log_dir,
            RCLONE_REMOTE=rclone_remote,
        ),
        args.dry_run,
    )

    print("\ndone. verify with: launchctl list | grep flexlog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
