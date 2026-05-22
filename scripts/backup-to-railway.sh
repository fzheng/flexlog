#!/bin/bash
# Sync $FLEXLOG_DATA_DIR to $RCLONE_REMOTE/live/, with --backup-dir
# preserving overwritten/deleted files under $RCLONE_REMOTE/archive/<ts>/.
# On success, ping healthchecks.io so silent failures alert after the
# grace period.
#
# Required env (set by com.flexlog.backup.plist):
#   FLEXLOG_DATA_DIR  - the source data dir
#   FLEXLOG_LOG_DIR   - where to write rclone.log
#   RCLONE_REMOTE     - e.g. railway-backup:flexlog-home-backup
#   HEALTHCHECK_URL   - https://hc-ping.com/<uuid>
set -euo pipefail

: "${FLEXLOG_DATA_DIR:?FLEXLOG_DATA_DIR is required}"
: "${FLEXLOG_LOG_DIR:?FLEXLOG_LOG_DIR is required}"
: "${RCLONE_REMOTE:?RCLONE_REMOTE is required (e.g. railway-backup:flexlog-home-backup)}"
: "${HEALTHCHECK_URL:?HEALTHCHECK_URL is required (https://hc-ping.com/<uuid>)}"

LIVE="${RCLONE_REMOTE}/live"
ARCHIVE="${RCLONE_REMOTE}/archive/$(date -u +%Y-%m-%dT%H-%M-%SZ)"
LOG="${FLEXLOG_LOG_DIR}/rclone.log"

mkdir -p "${FLEXLOG_LOG_DIR}"

# Tell healthchecks the run is starting (so the dashboard shows
# "running" while sync is in progress).
curl -fsS --retry 3 --max-time 10 "${HEALTHCHECK_URL}/start" >/dev/null || true

if rclone sync "${FLEXLOG_DATA_DIR}/" "${LIVE}/" \
        --backup-dir "${ARCHIVE}/" \
        --exclude 'uploads/.tmp/**' \
        --log-file "${LOG}" \
        --log-level INFO \
        --transfers 4 \
        --checkers 8 \
        --retries 3 \
        --low-level-retries 10; then
    curl -fsS --retry 3 --max-time 10 "${HEALTHCHECK_URL}" >/dev/null
    exit 0
else
    rc=$?
    # Send the exit code + last 1KB of log so healthchecks dashboard
    # shows a useful error.
    tail -c 1024 "${LOG}" 2>/dev/null | \
        curl -fsS --retry 3 --max-time 10 \
            --data-binary @- \
            "${HEALTHCHECK_URL}/fail" >/dev/null || true
    exit "${rc}"
fi
