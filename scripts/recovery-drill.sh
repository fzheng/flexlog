#!/bin/bash
# Quarterly recovery drill: materialize the latest live backup into
# a temp dir + start a test flexlog instance against it on port 5151,
# so you can verify the backup is actually usable.
#
# Run this from another machine, OR from the same Mac at a time when
# the real flexlog instance won't conflict.
#
# Required env:
#   RCLONE_REMOTE  - e.g. railway-backup:flexlog-home-backup
#
# Optional env:
#   FLEXLOG_REPO_DIR  - defaults to the repo containing this script
#   DRILL_PORT        - defaults to 5151
set -euo pipefail

: "${RCLONE_REMOTE:?RCLONE_REMOTE is required (e.g. railway-backup:flexlog-home-backup)}"

REPO_DIR="${FLEXLOG_REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PORT="${DRILL_PORT:-5151}"
TEMP_DIR=$(mktemp -d -t flexlog-drill-XXXXXX)

cleanup() {
    if [ -n "${FLEXLOG_PID:-}" ]; then
        kill "${FLEXLOG_PID}" 2>/dev/null || true
    fi
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT INT TERM

echo "Recovery drill"
echo "  repo:       ${REPO_DIR}"
echo "  rclone:     ${RCLONE_REMOTE}"
echo "  temp dir:   ${TEMP_DIR}"
echo "  test port:  ${PORT}"
echo

echo "Step 1: pulling latest live backup..."
rclone copy "${RCLONE_REMOTE}/live/" "${TEMP_DIR}/" --progress

echo
echo "Step 2: starting flexlog against the restored data..."
echo "  (this will run in foreground; Ctrl-C when done verifying)"
echo "  open: http://127.0.0.1:${PORT}/"
echo

cd "${REPO_DIR}"
FLEXLOG_DATA_DIR="${TEMP_DIR}" \
    FLEXLOG_PORT="${PORT}" \
    .venv/bin/python -m flexlog &
FLEXLOG_PID=$!

# Wait for flexlog to actually be up (poll the port).
for _ in $(seq 1 30); do
    if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
        echo "flexlog is up. Open http://127.0.0.1:${PORT}/ + log in to verify."
        break
    fi
    sleep 1
done

# Wait for user to be done.
echo
read -r -p "Press Enter when done verifying (will tear down + clean temp dir)..." _
