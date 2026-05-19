"""Status-bar metrics: total storage usage + last session save.

Pure-ish service: takes a SQLAlchemy Session + a Path to the data dir,
returns a StatusSnapshot. No Flask imports — the context processor
`_inject_status_snapshot` in `flexlog/app.py` wires it into the request
lifecycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flexlog.db.models import Session as SessionRow

logger = logging.getLogger("flexlog.status")


@dataclass(frozen=True)
class StatusSnapshot:
    storage_bytes: int
    last_session_at: datetime | None


def compute_status(db: Session, data_dir: Path) -> StatusSnapshot:
    """One SQL query + one filesystem walk. Cheap enough to run on
    every page render for a single-user app."""
    return StatusSnapshot(
        storage_bytes=_sum_dir_size(data_dir),
        last_session_at=_max_session_updated_at(db),
    )


def _sum_dir_size(data_dir: Path) -> int:
    total = 0
    for p in data_dir.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except (OSError, PermissionError):
            # Individual file we can't read — skip it. Total is
            # understated by that file's size; never crashes.
            continue
    return total


def _max_session_updated_at(db: Session) -> datetime | None:
    """SessionRow.updated_at is stored as an ISO-8601 UTC string
    (microsecond precision, with +00:00 offset). MAX() over the column
    works correctly under ISO-8601 lexicographic ordering. Returns a
    tz-aware datetime or None."""
    raw: str | None = db.execute(
        select(func.max(SessionRow.updated_at))
    ).scalar_one_or_none()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning(
            "malformed session.updated_at value %r (expected ISO-8601); "
            "treating as None for status bar. DB corruption suspected.",
            raw,
        )
        return None


_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def humanize_bytes(n: int) -> str:
    """1024-based units, 1 decimal place for KB and up. 0 returns "0 B".

    Examples:
      0 -> "0 B"
      1 -> "1 B"
      1023 -> "1023 B"
      1024 -> "1.0 KB"
      int(2.4 * 1024**3) -> "2.4 GB"
    """
    if n < 1024:
        return f"{n} B"
    value = float(n)
    unit_index = 0
    while value >= 1024 and unit_index < len(_UNITS) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.1f} {_UNITS[unit_index]}"
