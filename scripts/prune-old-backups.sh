#!/bin/bash
# Delete archive entries older than 30 days, keeping the rolling
# window manageable. Live/ mirror is never touched.
#
# Required env (set by com.flexlog.backup-prune.plist):
#   FLEXLOG_LOG_DIR  - where to write rclone.log
#   RCLONE_REMOTE    - e.g. railway-backup:flexlog-home-backup
set -euo pipefail

: "${FLEXLOG_LOG_DIR:?FLEXLOG_LOG_DIR is required}"
: "${RCLONE_REMOTE:?RCLONE_REMOTE is required (e.g. railway-backup:flexlog-home-backup)}"

LOG="${FLEXLOG_LOG_DIR}/prune.log"
mkdir -p "${FLEXLOG_LOG_DIR}"

rclone delete --min-age 30d "${RCLONE_REMOTE}/archive/" \
    --log-file "${LOG}" --log-level INFO

# Clean up now-empty archive subdirs so listings stay tidy.
rclone rmdirs --leave-root "${RCLONE_REMOTE}/archive/" \
    --log-file "${LOG}" --log-level INFO
