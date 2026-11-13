"""APScheduler configuration — data-collection jobs for the kernel runtime."""

import logging
import threading
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from scheduler.jobs import (
    job_catalog_sync,
    job_cleanup,
    job_news,
    job_prices,
    job_reminders,
)
from scheduler.settings import (
    get_news_crontab,
    get_prices_crontab,
    set_news_crontab,
    set_prices_crontab,
    validate_crontab,
)

logger = logging.getLogger(__name__)

# Re-export for UI / callers
__all__ = [
    "start_scheduler",
    "stop_scheduler",
    "get_scheduler_status",
    "update_news_crontab",
    "get_news_crontab",
    "update_prices_crontab",
    "get_prices_crontab",
    "job_cron",
    "trigger_job",
    "get_manual_run_status",
    "clear_manual_run_status",
    "JOB_FUNCTIONS",
    "NEWS_JOB_ID",
    "PRICES_JOB_ID",
]

_scheduler: Optional[BackgroundScheduler] = None

JOB_FUNCTIONS: dict[str, Callable] = {
    "prices": job_prices,
    "news": job_news,
    "catalog-sync": job_catalog_sync,
    "reminders": job_reminders,
    "cleanup": job_cleanup,
}

# Track manual trigger runs for the dashboard to poll.
_manual_runs: dict[str, dict] = {}
_manual_runs_lock = threading.Lock()

NEWS_JOB_ID = "news"
NEWS_JOB_NAME = "新闻轮询"
PRICES_JOB_ID = "prices"
PRICES_JOB_NAME = "价格采集"

# 5-field crontab plus the clock timezone for every fixed job.
# News and prices read the persisted scheduler settings instead.
FIXED_JOB_CRONS = {
    "catalog-sync": ("10 6 * * *", "Asia/Shanghai"),
    "reminders": ("*/15 * * * *", "Asia/Shanghai"),
    "cleanup": ("0 3 * * *", "Asia/Shanghai"),
}


def job_cron(job_id: str) -> tuple:
    """Return ``(crontab, timezone)`` for a scheduled job."""
    if job_id == NEWS_JOB_ID:
        return get_news_crontab(), config.APP_TIMEZONE
    if job_id == PRICES_JOB_ID:
        return get_prices_crontab(), config.APP_TIMEZONE
    spec = FIXED_JOB_CRONS.get(job_id)
    if not spec:
        return "", config.APP_TIMEZONE
    return spec


def _fixed_trigger(job_id: str) -> CronTrigger:
    expr, tz = job_cron(job_id)
    return validate_crontab(expr, timezone=tz)


def _news_trigger(crontab: Optional[str] = None) -> CronTrigger:
    expr = crontab if crontab is not None else get_news_crontab()
    return validate_crontab(expr, timezone=config.APP_TIMEZONE)


def _prices_trigger(crontab: Optional[str] = None) -> CronTrigger:
    expr = crontab if crontab is not None else get_prices_crontab()
    return validate_crontab(expr, timezone=config.APP_TIMEZONE)


def start_scheduler():
    """Start the background scheduler with all collection jobs configured."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running.")
        return

    _scheduler = BackgroundScheduler(
        # Allow short server restarts without silently losing a scheduled run.
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600},
    )

    _scheduler.add_job(
        job_prices,
        trigger=_prices_trigger(),
        id=PRICES_JOB_ID,
        name=PRICES_JOB_NAME,
    )
    logger.info("Prices poll crontab: %s (%s)", get_prices_crontab(), config.APP_TIMEZONE)
    _scheduler.add_job(
        job_catalog_sync,
        trigger=_fixed_trigger("catalog-sync"),
        id="catalog-sync",
        name="目录同步",
    )
    _scheduler.add_job(
        job_reminders,
        trigger=_fixed_trigger("reminders"),
        id="reminders",
        name="提醒比对",
    )
    _scheduler.add_job(
        job_cleanup,
        trigger=_fixed_trigger("cleanup"),
        id="cleanup",
        name="台账清理",
    )

    news_cron = get_news_crontab()
    _scheduler.add_job(
        job_news,
        trigger=_news_trigger(news_cron),
        id=NEWS_JOB_ID,
        name=NEWS_JOB_NAME,
    )
    logger.info("News poll crontab: %s (%s)", news_cron, config.APP_TIMEZONE)

    _scheduler.start()
    logger.info("Scheduler started with %d collection jobs.", len(JOB_FUNCTIONS))


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped.")


def get_scheduler_status() -> list[dict]:
    """Return status of all scheduled jobs for the dashboard."""
    if not _scheduler:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        expr, tz = job_cron(job.id)
        entry = {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time,
            "crontab": expr,
            "timezone": tz,
        }
        jobs.append(entry)
    return jobs


def update_news_crontab(expr: str) -> str:
    """Validate, persist, and live-reschedule the news poll job.

    Returns the cleaned crontab expression.
    Raises ValueError if the expression is invalid.
    """
    cleaned = set_news_crontab(expr)
    if _scheduler is not None:
        _scheduler.reschedule_job(NEWS_JOB_ID, trigger=_news_trigger(cleaned))
        logger.info("Rescheduled %s to crontab: %s", NEWS_JOB_ID, cleaned)
    return cleaned


def update_prices_crontab(expr: str) -> str:
    """Validate, persist, and live-reschedule the prices poll job.

    Returns the cleaned crontab expression.
    Raises ValueError if the expression is invalid.
    """
    cleaned = set_prices_crontab(expr)
    if _scheduler is not None:
        _scheduler.reschedule_job(PRICES_JOB_ID, trigger=_prices_trigger(cleaned))
        logger.info("Rescheduled %s to crontab: %s", PRICES_JOB_ID, cleaned)
    return cleaned


def trigger_job(job_id: str) -> bool:
    """Start one manual run, or acknowledge the existing run of this job.

    True means the request is handled. Repeated clicks from another browser
    cannot start a second manual run while the first is still running.
    """
    func = JOB_FUNCTIONS.get(job_id)
    if not func:
        logger.warning("Unknown job_id for manual trigger: %s", job_id)
        return False

    with _manual_runs_lock:
        if _manual_runs.get(job_id, {}).get("status") == "running":
            return True
        state = {"status": "running", "started_at": None, "error": None}
        _manual_runs[job_id] = state

    def _wrapper():
        from datetime import datetime, timezone

        from common.time import format_display_time

        with _manual_runs_lock:
            state["started_at"] = format_display_time(
                datetime.now(timezone.utc),
                fmt="%Y-%m-%d %H:%M:%S",
            )
        try:
            outcome = func()
            status = (
                outcome.get("status", "completed") if isinstance(outcome, dict) else "completed"
            )
            with _manual_runs_lock:
                state["status"] = status
                if status == "failed":
                    state["error"] = outcome.get("details") or "Unknown error"
        except Exception as exc:
            logger.exception("Manual trigger %s failed", job_id)
            with _manual_runs_lock:
                state.update(status="failed", error=str(exc))

    thread = threading.Thread(target=_wrapper, daemon=True, name=f"manual-{job_id}")
    try:
        thread.start()
    except Exception as exc:
        with _manual_runs_lock:
            state.update(status="failed", error=str(exc))
        logger.exception("Could not start manual job %s", job_id)
    return True


def get_manual_run_status(job_id: str) -> Optional[dict]:
    """Return a snapshot so rendering cannot observe a partially updated state."""
    with _manual_runs_lock:
        state = _manual_runs.get(job_id)
        return dict(state) if state else None


def clear_manual_run_status(job_id: str):
    """Dismiss a finished status; an active run remains protected."""
    with _manual_runs_lock:
        if _manual_runs.get(job_id, {}).get("status") != "running":
            _manual_runs.pop(job_id, None)
