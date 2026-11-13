"""APScheduler data-collection worker — prices/news/catalog/reminders/cleanup.

No LLM calls, no agent imports. Upstream failures never crash the worker:
every run lands in the job_runs ledger with a stable error code.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Holding, NewsArticle, WatchlistItem
from debrief.retention import cleanup_job_runs

logger = logging.getLogger(__name__)

TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Shanghai")
NEWS_CRONTAB = os.environ.get("NEWS_CRONTAB", "0 8-22/2 * * *")


def _prices_crontab() -> str:
    """Prices poll cadence: persisted settings → env default (all-day)."""
    try:
        from scheduler.settings import get_prices_crontab

        return get_prices_crontab()
    except Exception:  # pragma: no cover — settings failure never blocks the worker
        return os.environ.get("PRICES_CRONTAB", "*/30 * * * *")


_adapters_registered = False
_registry = None

# (job id, label, crontab, kind of failure code)
SCHEDULE = [
    # All-market coverage: */30 around the clock (Asia/Shanghai) — see
    # docs/cli.md Decisions. Adapters return the latest available quote for
    # closed markets, so one all-day job covers US/HK/CN/crypto without
    # per-market window logic (holidays and early closes included).
    ("prices", "价格采集", _prices_crontab(), "DEBRIEF_UPSTREAM_PRICE"),
    ("news", "新闻轮询", NEWS_CRONTAB, "DEBRIEF_UPSTREAM_NEWS"),
    ("catalog-sync", "目录同步", "10 6 * * *", "DEBRIEF_UPSTREAM_CATALOG"),
    ("reminders", "提醒比对", "*/15 * * * *", "DEBRIEF_UPSTREAM_REMINDER"),
    ("cleanup", "台账清理", "0 3 * * *", "DEBRIEF_CLEANUP"),
]


def _register_adapters():
    global _adapters_registered, _registry
    if _adapters_registered:
        return _registry
    try:
        from adapters.base import registry
        from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
        from adapters.crypto import CryptoAdapter
        from adapters.us_market import USMarketAdapter
    except ModuleNotFoundError as exc:
        # Slim wheel installs carry the CLI only; the collectors extra needs
        # the full source install for market adapters.
        raise RuntimeError(
            "missing collector module "
            f"'{exc.name}': install portfolio-agent-kernel[collectors] "
            "from the full source checkout (the slim wheel has no adapters/)"
        ) from None

    for market, adapter in (
        ("US", USMarketAdapter()),
        ("CN", CNMarketAdapter()),
        ("HK", HKMarketAdapter()),
        ("CRYPTO", CryptoAdapter()),
    ):
        registry.register(market, adapter)
    _adapters_registered = True
    _registry = registry
    return registry


def _ledger(engine, job_id: str, job_name: str, error_code: str, func):
    """Run one collection task inside a job_runs ledger row; never raise."""

    def run():
        from db.repository import create_job_run, finish_job_run

        session = Session(engine)
        try:
            run_id = create_job_run(session, job_id, job_name).id
        finally:
            session.close()
        try:
            session = Session(engine)
            try:
                outcome = func(session)
            finally:
                session.close()
            details = json.dumps(outcome, ensure_ascii=False, default=str)[:1000]
            session = Session(engine)
            try:
                finish_job_run(session, run_id, "succeeded", details=details)
            finally:
                session.close()
            logger.info("%s done: %s", job_id, details[:200])
        except Exception as exc:
            logger.exception("%s failed", job_id)
            session = Session(engine)
            try:
                finish_job_run(
                    session,
                    run_id,
                    "failed",
                    details=str(exc)[:1000],
                    error_code=error_code,
                )
            finally:
                session.close()

    return run


def collect_prices(session: Session) -> dict:
    """Fetch quotes for open holdings + watchlist and upsert daily snapshots."""
    from db.repository import upsert_price

    registry = _register_adapters()
    targets = set()
    for holding in session.scalars(
        select(Holding).where(Holding.status == "open")
    ).all():
        targets.add((holding.market.upper(), holding.ticker.upper()))
    for item in session.scalars(
        select(WatchlistItem).where(WatchlistItem.status != "archived")
    ).all():
        targets.add((item.market.upper(), item.ticker.upper()))

    ok, failed = 0, []
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for market, ticker in sorted(targets):
        adapter = registry.get(market)
        try:
            quote = adapter.get_price(ticker)
        except Exception as exc:
            failed.append(f"{market}:{ticker}:{type(exc).__name__}")
            continue
        price = quote.get("price") if isinstance(quote, dict) else None
        if price is None:
            failed.append(f"{market}:{ticker}:no-price")
            continue
        try:
            upsert_price(
                session,
                ticker,
                market,
                today,
                float(price),
                source=quote.get("source", "") or "adapter",
            )
            ok += 1
        except Exception:
            failed.append(f"{market}:{ticker}:persist-error")
    return {"saved": ok, "failed": failed}


def collect_news(session: Session) -> dict:
    from adapters.news import WallStreetCNAdapter
    from db.repository import save_news_article

    adapter = WallStreetCNAdapter()
    items = adapter.get_latest_news(limit=20)
    known = {headline for (headline,) in session.execute(select(NewsArticle.headline))}
    saved = 0
    for item in items:
        if not item.get("title") or item["title"] in known:
            continue
        save_news_article(
            session,
            headline=item["title"],
            source="wallstreetcn",
            url=item.get("url"),
            published_at=_parse_published(item.get("published_at")),
            summary=item.get("summary"),
        )
        known.add(item["title"])
        saved += 1
    return {"fetched": len(items), "saved": saved}


def _parse_published(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def collect_catalog(session: Session) -> dict:
    from debrief import catalog

    return catalog.sync_stock_catalog(session)


def check_reminders(session: Session) -> dict:
    """Compare watchlist targets against latest prices; no LLM involved."""
    from debrief.kernel import _two_closes

    alerts = []
    for item in session.scalars(
        select(WatchlistItem).where(WatchlistItem.status != "archived")
    ).all():
        last, _ = _two_closes(session, item.ticker, item.market.upper())
        if last is None:
            continue
        low = item.target_price_low
        high = item.target_price_high
        if low is not None and last <= low:
            alerts.append(f"{item.name or item.ticker} 现价 {last:.2f} ≤ 关注价 {low:.2f}")
        if high is not None and last >= high:
            alerts.append(f"{item.name or item.ticker} 现价 {last:.2f} ≥ 关注价 {high:.2f}")
    notified = False
    if alerts:
        try:
            from notifier.telegram import notify

            notified = bool(notify("🔔 提醒比对\n\n" + "\n".join(alerts)))
        except Exception:
            notified = False
    return {"alerts": len(alerts), "details": alerts, "notified": notified}


def build_scheduler(engine) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone=TIMEZONE,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600},
    )
    for job_id, job_name, crontab, error_code in SCHEDULE:
        func = {
            "prices": collect_prices,
            "news": collect_news,
            "catalog-sync": collect_catalog,
            "reminders": check_reminders,
            "cleanup": lambda session: cleanup_job_runs(engine),
        }[job_id]
        scheduler.add_job(
            _ledger(engine, job_id, job_name, error_code, func),
            trigger=CronTrigger.from_crontab(crontab, timezone=TIMEZONE),
            id=job_id,
            name=job_name,
        )
    return scheduler


def schedule_table() -> dict:
    return {
        "timezone": TIMEZONE,
        "jobs": [
            {"id": job_id, "kind": job_name, "crontab": crontab}
            for job_id, job_name, crontab, _ in SCHEDULE
        ],
    }


def run_worker(dry_run: bool, db_path: Optional[Path] = None) -> dict:
    from debrief.context import open_engine

    engine = open_engine(db_path, migrate=True)
    if dry_run:
        return {"dryRun": True, "schedule": schedule_table()}
    scheduler = build_scheduler(engine)
    scheduler.start()
    logger.info("debrief worker started with %d jobs", len(SCHEDULE))
    stop = threading.Event()
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown(wait=False)
    return {"stopped": True, "schedule": schedule_table()}
