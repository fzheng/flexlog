#!/usr/bin/env python3
"""Uninstall the flexlog launchd user agents.

Bootouts each agent and removes its plist from ~/Library/LaunchAgents.
Does NOT touch the data dir, log dir, or any rclone state — purely
about the launch-agent registration."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
AGENT_NAMES = (
    "com.flexlog.app",
    "com.flexlog.backup",
    "com.flexlog.backup-prune",
)


def main() -> int:
    uid = os.getuid()
    any_action = False
    for name in AGENT_NAMES:
        plist = LAUNCH_AGENTS_DIR / f"{name}.plist"
        if not plist.exists():
            print(f"  skipped {name} (not installed)")
            continue
        # bootout — exit code is non-zero if not currently loaded; that's fine
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(plist)],
            check=False, capture_output=True,
        )
        plist.unlink()
        print(f"  removed {plist}")
        any_action = True
    if not any_action:
        print("nothing to uninstall.")
    else:
        print("\ndone. verify with: launchctl list | grep flexlog (should be empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
