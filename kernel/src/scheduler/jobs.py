"""Scheduler job definitions — data collection only (design §1.2, no LLM).

Cognitive tasks (盘后分析/复盘/记忆压缩) belong to the DSH agent; the kernel
scheduler only collects prices/news/catalog, compares watchlist reminders,
and runs retention cleanup. Every invocation lands in job_runs with a stable
error code; upstream failures never crash the process.
"""

import logging

from db.repository import (
    create_job_run,
    finish_job_run,
    get_open_holdings,
    get_session,
    get_watchlist_items,
)
from memory.context import current_run_id

logger = logging.getLogger(__name__)


def _start_job_run(job_id: str, job_name: str) -> int:
    session = get_session()
    try:
        run_id = create_job_run(session, job_id, job_name).id
        current_run_id.set(run_id)
        return run_id
    finally:
        session.close()


def _finish_job_run(run_id: int, status: str, details: str = None, error_code: str = None):
    session = get_session()
    try:
        finish_job_run(session, run_id, status, details, error_code=error_code)
        return {"status": status, "details": details}
    finally:
        current_run_id.set(None)
        session.close()


def _targets():
    """Unique (market, ticker) pairs from open holdings and the watchlist."""
    session = get_session()
    try:
        targets = {(h.market.upper(), h.ticker.upper()) for h in get_open_holdings(session)}
        targets |= {(w.market.upper(), w.ticker.upper()) for w in get_watchlist_items(session)}
        return sorted(targets)
    finally:
        session.close()


def job_prices():
    from debrief.worker import collect_prices

    run_id = _start_job_run("prices", "价格采集")
    try:
        session = get_session()
        try:
            outcome = collect_prices(session)
        finally:
            session.close()
        if outcome["failed"] and not outcome["saved"]:
            return _finish_job_run(
                run_id, "failed", str(outcome), error_code="DEBRIEF_UPSTREAM_PRICE"
            )
        return _finish_job_run(run_id, "completed", str(outcome))
    except Exception as exc:
        logger.error("price collection failed: %s", exc)
        return _finish_job_run(run_id, "failed", str(exc), error_code="DEBRIEF_UPSTREAM_PRICE")


def job_news():
    from debrief.worker import collect_news

    run_id = _start_job_run("news", "新闻轮询")
    try:
        session = get_session()
        try:
            outcome = collect_news(session)
        finally:
            session.close()
        return _finish_job_run(run_id, "completed", str(outcome))
    except Exception as exc:
        logger.error("news collection failed: %s", exc)
        return _finish_job_run(run_id, "failed", str(exc), error_code="DEBRIEF_UPSTREAM_NEWS")


def job_catalog_sync():
    from debrief.worker import collect_catalog

    run_id = _start_job_run("catalog-sync", "目录同步")
    try:
        session = get_session()
        try:
            outcome = collect_catalog(session)
        finally:
            session.close()
        return _finish_job_run(run_id, "completed", str(outcome))
    except Exception as exc:
        logger.error("catalog sync failed: %s", exc)
        return _finish_job_run(run_id, "failed", str(exc), error_code="DEBRIEF_UPSTREAM_CATALOG")


def job_reminders():
    from debrief.worker import check_reminders

    run_id = _start_job_run("reminders", "提醒比对")
    try:
        session = get_session()
        try:
            outcome = check_reminders(session)
        finally:
            session.close()
        return _finish_job_run(run_id, "completed", str(outcome))
    except Exception as exc:
        logger.error("reminder comparison failed: %s", exc)
        return _finish_job_run(run_id, "failed", str(exc), error_code="DEBRIEF_UPSTREAM_REMINDER")


def job_cleanup():
    from db.repository import engine
    from debrief.retention import cleanup_job_runs

    run_id = _start_job_run("cleanup", "台账清理")
    try:
        outcome = cleanup_job_runs(engine)
        return _finish_job_run(run_id, "completed", str(outcome))
    except Exception as exc:
        logger.error("job_runs cleanup failed: %s", exc)
        return _finish_job_run(run_id, "failed", str(exc), error_code="DEBRIEF_CLEANUP")
