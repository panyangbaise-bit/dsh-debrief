"""APScheduler data-collection worker — prices/news/catalog/reminders/cleanup.

No LLM calls, no agent imports. Upstream failures never crash the worker:
every run lands in the job_runs ledger with a stable error code.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from config import config
from db.models import Holding, NewsArticle, PriceCache, WatchlistItem
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


SUPPORTED_MARKETS = ("US", "CN", "HK", "CRYPTO")


def _register_adapters(markets=None):
    """Register market adapters, importing collector modules only when needed.

    `markets` narrows the import set on purpose: the CN/HK adapters pull in
    akshare + pandas (≈3 s of imports cold), so a dashboard that only needs a
    US quote must never import them. Omitting `markets` registers every
    supported market (the scheduled worker's behaviour).
    """
    global _adapters_registered, _registry
    wanted = {str(market).upper() for market in markets} if markets else set(SUPPORTED_MARKETS)
    wanted &= set(SUPPORTED_MARKETS)
    if _adapters_registered and wanted <= set(_registry.markets):
        return _registry
    try:
        from adapters.base import registry

        if "US" in wanted and "US" not in registry.markets:
            from adapters.us_market import USMarketAdapter

            registry.register("US", USMarketAdapter())
        if (wanted & {"CN", "HK"}) - set(registry.markets):
            from adapters.cn_market import CNMarketAdapter, HKMarketAdapter

            if "CN" in wanted and "CN" not in registry.markets:
                registry.register("CN", CNMarketAdapter())
            if "HK" in wanted and "HK" not in registry.markets:
                registry.register("HK", HKMarketAdapter())
        if "CRYPTO" in wanted and "CRYPTO" not in registry.markets:
            from adapters.crypto import CryptoAdapter

            registry.register("CRYPTO", CryptoAdapter())
    except ModuleNotFoundError as exc:
        # Slim wheel installs carry the CLI only; the collectors extra needs
        # the full source install for market adapters.
        raise RuntimeError(
            "missing collector module "
            f"'{exc.name}': install portfolio-agent-kernel[collectors] "
            "from the full source checkout (the slim wheel has no adapters/)"
        ) from None

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
                # Serialize while the session is still open: several tasks
                # return ORM rows inside the outcome, and repr/dumps on a
                # detached instance raises DetachedInstanceError, which used
                # to fail the whole ledger row after a successful collection.
                details = json.dumps(outcome, ensure_ascii=False, default=str)[:1000]
            finally:
                session.close()
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

    # Benchmark fallback: markets with no holdings/watchlist targets still get
    # their benchmark tickers cached every cycle (e.g. CRYPTO → BTC/ETH), so
    # the after-market input package reads fresh quotes without a live fetch.
    from debrief.commands import MARKET_BENCHMARK_TICKERS

    covered = {market for market, _ in targets}
    for market, tickers in MARKET_BENCHMARK_TICKERS.items():
        if market in covered:
            continue
        for ticker in tickers:
            targets.add((market, ticker.upper()))

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
    from config import config
    from db.repository import save_news_article

    adapter = WallStreetCNAdapter()
    items = adapter.get_latest_news(limit=20)
    known = {headline for (headline,) in session.execute(select(NewsArticle.headline))}
    saved = 0
    saved_articles = []
    for item in items:
        if not item.get("title") or item["title"] in known:
            continue
        article = save_news_article(
            session,
            headline=item["title"],
            source="wallstreetcn",
            url=item.get("url"),
            published_at=_parse_published(item.get("published_at")),
            summary=item.get("summary"),
        )
        known.add(item["title"])
        saved += 1
        saved_articles.append(article)
    notified = False
    if saved and config.TELEGRAM_NEWS_PUSH:
        try:
            from notifier.telegram import is_configured, notify_news_digest

            if is_configured():
                notified = bool(notify_news_digest(saved_articles, count=saved))
        except Exception:
            notified = False
    return {
        "fetched": len(items),
        "saved": saved,
        "notified": notified,
        "items": saved_articles,
    }


def refresh_stale_prices(session: Session, targets, force: bool = False) -> dict:
    """Refresh quotes for stale or forced (market, ticker) targets.

    Adapter calls run in worker threads (Session is not thread-safe — each
    thread only calls the adapter); upserts happen sequentially in the
    caller's thread afterwards. Never raises: a missing collectors install
    degrades to cached prices (available=False).
    """
    from concurrent.futures import ThreadPoolExecutor

    from config import config
    from db.repository import upsert_price

    targets = sorted({(str(m).upper(), str(t).upper()) for m, t in targets})
    if not targets:
        return {"refreshed": 0, "failed": [], "available": True}

    # SQLite returns naive datetimes — compare against naive UTC.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=config.PRICE_STALE_SECONDS
    )
    stale_targets = []
    for market, ticker in targets:
        if force:
            stale_targets.append((market, ticker))
            continue
        latest = session.scalars(
            select(PriceCache)
            .where(PriceCache.market == market, PriceCache.ticker == ticker)
            .order_by(desc(PriceCache.date), desc(PriceCache.id))
            .limit(1)
        ).first()
        # No row at all → also stale (a freshly added holding must get its
        # first live quote on the next read, not wait for the cron job).
        if latest is None or latest.fetched_at is None or latest.fetched_at < cutoff:
            stale_targets.append((market, ticker))

    # Nothing to fetch: return before importing any collector module. The
    # dashboard hits this path on every view inside PRICE_STALE_SECONDS, and
    # akshare/yfinance imports are the single most expensive thing in it.
    if not stale_targets:
        return {"refreshed": 0, "failed": [], "available": True}

    try:
        registry = _register_adapters({market for market, _ in stale_targets})
    except (ModuleNotFoundError, ImportError, RuntimeError):
        return {"refreshed": 0, "failed": [], "available": False}

    def fetch(market_ticker):
        market, ticker = market_ticker
        try:
            adapter = registry.get(market)
            quote = adapter.get_price(ticker)
        except Exception as exc:
            return (market, ticker, None, "", f"{market}:{ticker}:{type(exc).__name__}")
        price = quote.get("price") if isinstance(quote, dict) else None
        if price is None:
            return (market, ticker, None, "", f"{market}:{ticker}:no-price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            return (market, ticker, None, "", f"{market}:{ticker}:bad-price")
        return (market, ticker, price, quote.get("source", "") or "adapter", None)

    results = []
    if stale_targets:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(fetch, stale_targets))

    refreshed, failed = 0, []
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fetched_now = datetime.now(timezone.utc)
    for market, ticker, price, source, error in results:
        if error:
            failed.append(error)
            continue
        try:
            upsert_price(
                session,
                ticker,
                market,
                today,
                price,
                source=source,
                fetched_at=fetched_now,
            )
            refreshed += 1
        except Exception:
            failed.append(f"{market}:{ticker}:persist-error")
    return {"refreshed": refreshed, "failed": failed, "available": True}


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


REMINDER_MARKET_LABELS = {"US": "美股", "CN": "A股", "HK": "港股", "CRYPTO": "加密"}


def _reminder_price(value: float) -> str:
    """Two decimals above 1, four below (crypto can be sub-dollar)."""
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"


def _reminder_name(item: WatchlistItem) -> str:
    name = (item.name or item.ticker).strip()
    # Catalog names are often full legal names; trim at the share-class suffix:
    # "Duolingo, Inc. - Class A Common Stock" -> "Duolingo, Inc."
    name = name.split(" - ")[0].strip() or item.ticker
    return name if len(name) <= 32 else name[:31].rstrip() + "…"


def _reminder_cooldown_label(minutes: int) -> str:
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return f"{minutes} 分钟"


def _format_reminder(alerts: list, now: datetime, cooldown_minutes: int) -> str:
    from common.time import format_display_time

    lines = [f"🔔 关注价提醒 · {format_display_time(now, fmt='%m-%d %H:%M')}"]
    for market, label in REMINDER_MARKET_LABELS.items():
        group = [alert for alert in alerts if alert["market"] == market]
        if not group:
            continue
        lines.append("")
        lines.append(f"【{label}】")
        lines.extend(f"- {alert['text']}" for alert in group)
    lines.append("")
    lines.append(
        f"（仅交易时段推送；同一标的每 {_reminder_cooldown_label(cooldown_minutes)}最多提醒一次）"
    )
    return "\n".join(lines)


def check_reminders(session: Session, now: Optional[datetime] = None) -> dict:
    """Compare watchlist targets against latest prices; no LLM involved.

    Reminder policy (user request 2026-11-25):
    * only push inside the instrument's own regular market session — US/CN/HK
      exchange hours, crypto is 24/7 — so a target hit no longer pings at
      21:00 Beijing time (US pre-market) or on weekends;
    * at most one push per instrument per ``REMINDER_COOLDOWN_MINUTES``
      (default 2h) while the target zone stays hit;
    * leaving the zone resets the state, so the next fresh cross alerts
      immediately instead of waiting out the cooldown.
    """
    from common.market_hours import is_market_open
    from debrief.kernel import _two_closes

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    # DB timestamps are naive UTC (SQLite drops the offset); keep the stored
    # reminder state in the same convention so cooldown math is timezone-safe.
    now_stored = now.replace(tzinfo=None)
    cooldown = timedelta(minutes=config.REMINDER_COOLDOWN_MINUTES)

    alerts = []
    suppressed = 0
    outside_session = 0
    dirty = False
    for item in session.scalars(
        select(WatchlistItem).where(WatchlistItem.status != "archived")
    ).all():
        if not getattr(item, "alert_enabled", 1):
            continue
        market = (item.market or "").upper()
        if not is_market_open(market, now):
            outside_session += 1
            continue
        last, _ = _two_closes(session, item.ticker, market)
        if last is None:
            continue
        low = item.target_price_low
        high = item.target_price_high
        hit_low = low is not None and last <= low
        hit_high = high is not None and last >= high
        if not (hit_low or hit_high):
            if item.alert_active:
                item.alert_active = 0
                dirty = True
            continue
        last_alert_at = item.last_alert_at
        if last_alert_at is not None and last_alert_at.tzinfo is not None:
            last_alert_at = last_alert_at.astimezone(timezone.utc).replace(tzinfo=None)
        if (
            item.alert_active
            and last_alert_at is not None
            and now_stored - last_alert_at < cooldown
        ):
            suppressed += 1
            continue

        name = _reminder_name(item)
        if hit_low:
            alerts.append(
                {
                    "market": market,
                    "symbol": item.ticker,
                    "text": f"{name} 现价 {_reminder_price(last)} ≤ 关注价 {_reminder_price(low)}",
                }
            )
        if hit_high:
            alerts.append(
                {
                    "market": market,
                    "symbol": item.ticker,
                    "text": f"{name} 现价 {_reminder_price(last)} ≥ 关注价 {_reminder_price(high)}",
                }
            )
        item.alert_active = 1
        item.last_alert_at = now_stored
        dirty = True
    if dirty:
        session.commit()

    notified = False
    if alerts:
        try:
            from notifier.telegram import notify

            notified = bool(
                notify(
                    _format_reminder(
                        alerts, now, cooldown_minutes=config.REMINDER_COOLDOWN_MINUTES
                    )
                )
            )
        except Exception:
            notified = False
    return {
        "alerts": len(alerts),
        "details": [alert["text"] for alert in alerts],
        "notified": notified,
        "suppressed": suppressed,
        "outsideSession": outside_session,
    }


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
