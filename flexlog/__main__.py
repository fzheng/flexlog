"""Command-line entry point: `python -m flexlog` or the `flexlog` console script."""

from __future__ import annotations

import os
import sys

from flexlog.app import create_app

DEFAULT_PORT = 5050


def main() -> None:
    port_raw = os.environ.get("FLEXLOG_PORT", str(DEFAULT_PORT))
    try:
        port = int(port_raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        print(
            f"FLEXLOG_PORT={port_raw!r} is not a valid TCP port number (1..65535)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    app = create_app()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=app.debug)


if __name__ == "__main__":
    main()
