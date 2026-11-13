"""job_runs retention cleanup (design §3.1): batch DELETE + incremental_vacuum."""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

JOB_RUN_RETENTION_DAYS = int(os.environ.get("JOB_RUN_RETENTION_DAYS", "365"))
CLEANUP_BATCH_SIZE = 500


def cleanup_job_runs(
    engine: Engine, retention_days: int = None, batch_size: int = None
) -> dict:
    """Delete job_runs rows older than the retention window, never running ones.

    Returns {deleted, cutoff, seconds} for observability; the caller records a
    job_runs row for the cleanup itself.
    """
    days = JOB_RUN_RETENTION_DAYS if retention_days is None else int(retention_days)
    batch = CLEANUP_BATCH_SIZE if batch_size is None else int(batch_size)
    started = datetime.now(timezone.utc)
    cutoff = started - timedelta(days=days)
    deleted = 0
    with engine.begin() as conn:
        while True:
            result = conn.execute(
                text(
                    """
                    DELETE FROM job_runs WHERE id IN (
                        SELECT id FROM job_runs
                        WHERE started_at < :cutoff AND status != 'running'
                        LIMIT :batch
                    )
                    """
                ),
                {"cutoff": cutoff, "batch": batch},
            )
            deleted += result.rowcount or 0
            if not result.rowcount or result.rowcount < batch:
                break
        try:
            conn.execute(text("PRAGMA incremental_vacuum(1000)"))
        except Exception:
            pass
    return {
        "deleted": deleted,
        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
    }
