"""Worker tests: schedule, fault tolerance, ledger error codes (no network)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from debrief.worker import (
    SCHEDULE,
    build_scheduler,
    check_reminders,
    collect_catalog,
    collect_prices,
)


@pytest.fixture
def engine(tmp_path):
    from debrief.context import open_engine

    engine = open_engine(tmp_path / "worker.db")
    yield engine
    engine.dispose()


class FakeAdapter:
    def __init__(self, fail=False):
        self.fail = fail

    def get_price(self, ticker):
        if self.fail:
            raise ConnectionError("upstream down")
        return {"ticker": ticker, "price": 123.45, "currency": "USD", "source": "fake"}


def seed_holding(session, ticker="AAPL", market="US"):
    from db.repository import create_holding

    return create_holding(session, ticker, market, shares=10, cost_basis=100.0)


def test_news_ledger_succeeds_when_outcome_holds_orm_rows(engine, monkeypatch):
    """Regression: _ledger used to json.dumps() the outcome AFTER the session
    closed; collect_news returns ORM NewsArticle rows, so every news poll hit
    DetachedInstanceError and landed in the ledger as failed with
    DEBRIEF_UPSTREAM_NEWS even though the fetch succeeded."""
    import debrief.worker as worker
    from db.models import JobRun
    from sqlalchemy import select

    class FakeNewsAdapter:
        def get_latest_news(self, limit=10):
            return [
                {
                    "title": "标题一",
                    "url": "https://example.com/1",
                    "published_at": "2026-11-18T12:00:00+08:00",
                    "summary": "摘要",
                }
            ]

    monkeypatch.setattr("adapters.news.WallStreetCNAdapter", FakeNewsAdapter)
    worker._ledger(engine, "news", "新闻轮询", "DEBRIEF_UPSTREAM_NEWS", worker.collect_news)()

    with Session(engine) as db:
        row = db.scalars(select(JobRun)).one()
        assert row.status == "succeeded"
        assert row.error_code is None


def test_dry_run_schedule_table(tmp_path, monkeypatch):
    import importlib

    import debrief.worker as worker

    monkeypatch.setattr("scheduler.settings.SETTINGS_PATH", tmp_path / "s.json")
    monkeypatch.setattr("scheduler.settings.config.DEFAULT_PRICES_CRONTAB", "*/30 * * * *")
    module = importlib.reload(worker)
    table = module.schedule_table()
    assert table["timezone"]
    assert {job["id"] for job in table["jobs"]} == {job_id for job_id, *_ in SCHEDULE}
    assert len(table["jobs"]) == 5
    prices = next(job for job in table["jobs"] if job["id"] == "prices")
    # All-market coverage: every 30 minutes around the clock (Asia/Shanghai).
    assert prices["crontab"] == "*/30 * * * *"


def test_prices_crontab_follows_persisted_settings(tmp_path, monkeypatch):
    """The worker resolves the prices cadence from scheduler settings."""
    import importlib

    import debrief.worker as worker

    monkeypatch.setattr(
        "scheduler.settings.SETTINGS_PATH", tmp_path / "scheduler_settings.json"
    )
    monkeypatch.setattr(
        "scheduler.settings.config.DEFAULT_PRICES_CRONTAB", "*/30 * * * *"
    )
    module = importlib.reload(worker)
    assert module._prices_crontab() == "*/30 * * * *"

    from scheduler.settings import set_prices_crontab

    set_prices_crontab("*/15 1-5 * * *")
    module = importlib.reload(worker)
    assert module._prices_crontab() == "*/15 1-5 * * *"
    prices = next(entry for entry in module.SCHEDULE if entry[0] == "prices")
    assert prices[2] == "*/15 1-5 * * *"


def test_build_scheduler_registers_all_jobs(engine):
    scheduler = build_scheduler(engine)
    try:
        scheduler.start()
        jobs = scheduler.get_jobs()
        assert {job.id for job in jobs} == {job_id for job_id, *_ in SCHEDULE}
    finally:
        scheduler.shutdown(wait=False)


def test_collect_prices_upserts_and_tolerates_failure(engine, monkeypatch):
    from debrief import worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr(
        "debrief.worker._register_adapters",
        lambda: _fake_registry(),
    )

    with Session(engine) as session:
        seed_holding(session, "AAPL", "US")
        seed_holding(session, "NVDA", "US")
        result = collect_prices(session)
    # US holdings (2) + CRYPTO benchmark fallback (BTC, ETH) since CRYPTO has
    # no holdings/watchlist targets.
    assert result["saved"] == 4
    assert result["failed"] == []

    from db.models import PriceCache

    with Session(engine) as session:
        rows = session.scalars(select(PriceCache)).all()
        assert len(rows) == 4
        assert all(row.close == 123.45 for row in rows)


def test_collect_prices_collects_benchmark_tickers_for_empty_market(engine, monkeypatch):
    """Regression: a market with no positions/watchlist (e.g. CRYPTO after the
    strategic exit) still gets its benchmark tickers cached each cycle, so the
    after-market package has fresh quotes instead of an empty list."""
    from debrief import worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr("debrief.worker._register_adapters", _fake_registry)

    with Session(engine) as session:
        result = collect_prices(session)
    assert result["saved"] == 2
    assert result["failed"] == []

    from db.models import PriceCache

    with Session(engine) as session:
        symbols = {row.ticker for row in session.scalars(select(PriceCache)).all()}
        assert symbols == {"BTC", "ETH"}


def test_collect_prices_skips_benchmarks_when_market_has_targets(engine, monkeypatch):
    """A market that already has holdings/watchlist targets must not double up
    with benchmark tickers."""
    from debrief import worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr("debrief.worker._register_adapters", _fake_registry)

    with Session(engine) as session:
        seed_holding(session, "BTC", "CRYPTO")
        result = collect_prices(session)
    assert result["saved"] == 1

    from db.models import PriceCache

    with Session(engine) as session:
        symbols = {row.ticker for row in session.scalars(select(PriceCache)).all()}
        assert symbols == {"BTC"}


def _fake_registry():
    from adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    registry.register("US", FakeAdapter())
    registry.register("CN", FakeAdapter(fail=True))
    registry.register("HK", FakeAdapter(fail=True))
    registry.register("CRYPTO", FakeAdapter())
    return registry


def test_collect_prices_failure_never_raises(engine, monkeypatch):
    from debrief import worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr("debrief.worker._register_adapters", _fake_registry)

    with Session(engine) as session:
        seed_holding(session, "600519", "CN")
        result = collect_prices(session)
    # CN adapter fails; CRYPTO benchmark fallback (BTC, ETH) still succeeds.
    assert result["saved"] == 2
    assert any("600519" in failure for failure in result["failed"])


def test_ledger_records_error_code_on_failure(engine, monkeypatch):
    from debrief.worker import _ledger

    def boom(session):
        raise RuntimeError("upstream timeout")

    with Session(engine) as session:
        seed_holding(session)
    wrapped = _ledger(engine, "prices", "价格采集", "DEBRIEF_UPSTREAM_PRICE", boom)
    wrapped()  # never raises

    from db.models import JobRun

    with Session(engine) as session:
        run = session.scalars(select(JobRun)).one()
        assert run.status == "failed"
        assert run.error_code == "DEBRIEF_UPSTREAM_PRICE"
        assert "upstream timeout" in run.details


def test_ledger_records_success_details(engine):
    from debrief.worker import _ledger

    def fine(session):
        return {"saved": 3, "failed": []}

    wrapped = _ledger(engine, "catalog-sync", "目录同步", "DEBRIEF_UPSTREAM_CATALOG", fine)
    wrapped()

    from db.models import JobRun

    with Session(engine) as session:
        run = session.scalars(select(JobRun)).one()
        assert run.status == "succeeded"
        assert '"saved": 3' in run.details


def test_catalog_sync_falls_back_partially(engine, monkeypatch):
    from debrief import catalog

    monkeypatch.setattr(catalog, "_akshare_rows", lambda *a, **k: [])
    monkeypatch.setattr(
        catalog,
        "sync_coin_list",
        lambda session, limit=2000: catalog._upsert_rows(
            session,
            [
                {"market": "CC", "symbol": "BTC", "name": "Bitcoin", "currency": "USD", "asset_class": "crypto", "pinyin_alias": None},
                {"market": "CC", "symbol": "ETH", "name": "Ethereum", "currency": "USD", "asset_class": "crypto", "pinyin_alias": None},
            ],
        ),
    )
    with Session(engine) as session:
        stats = collect_catalog(session)
    assert stats["crypto"] == 2
    assert isinstance(stats["cn_stock"], int)

    from debrief.catalog import catalog_counts

    with Session(engine) as session:
        assert catalog_counts(session)["CC"] == 2


def _watch(engine, ticker="SPCX", market="US", price=125.0, target=132.0, name=None, alert=True):
    """Seed one watchlist item plus a price row; returns nothing (DB is source of truth)."""
    from db.repository import create_watchlist_item, upsert_price

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(engine) as session:
        item = create_watchlist_item(
            session, ticker, market, name=name or ticker, target_price_low=target
        )
        if not alert:
            item.alert_enabled = 0
        upsert_price(session, ticker, market, today, close=price, source="seed")
        session.commit()


def _set_price(engine, ticker, market, price):
    from db.repository import upsert_price

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(engine) as session:
        upsert_price(session, ticker, market, today, close=price, source="seed")
        session.commit()


def _et(hour, minute=0):
    return datetime(2026, 11, 25, hour, minute, tzinfo=ZoneInfo("America/New_York"))


def test_check_reminders_compares_targets_inside_the_session(engine):
    _watch(engine, "00700", "HK", price=370.0, target=380.0, name="腾讯控股")
    hk_morning = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    with Session(engine) as session:
        result = check_reminders(session, now=hk_morning)
    assert result["alerts"] == 1
    assert any("00700" in detail or "腾讯" in detail for detail in result["details"])


def test_check_reminders_only_pushes_inside_the_market_session(engine):
    _watch(engine)
    with Session(engine) as session:
        premarket = check_reminders(session, now=_et(8, 0))
        assert premarket["alerts"] == 0
        assert premarket["outsideSession"] == 1
        after_close = check_reminders(session, now=_et(16, 30))
        assert after_close["alerts"] == 0
        regular = check_reminders(session, now=_et(10, 0))
    assert regular["alerts"] == 1
    assert regular["notified"] is False  # Telegram unconfigured in tests


def test_check_reminders_throttles_repeats_within_the_cooldown(engine):
    _watch(engine)
    with Session(engine) as session:
        first = check_reminders(session, now=_et(10, 0))
        second = check_reminders(session, now=_et(11, 0))
        third = check_reminders(session, now=_et(12, 0))
    assert first["alerts"] == 1
    assert second["alerts"] == 0
    assert second["suppressed"] == 1
    assert third["alerts"] == 1


def test_check_reminders_fresh_cross_alerts_immediately_after_recovery(engine):
    _watch(engine)
    with Session(engine) as session:
        assert check_reminders(session, now=_et(10, 0))["alerts"] == 1
    _set_price(engine, "SPCX", "US", 140.0)  # recovered above target
    with Session(engine) as session:
        recovered = check_reminders(session, now=_et(10, 15))
    assert recovered["alerts"] == 0
    _set_price(engine, "SPCX", "US", 131.0)  # dips back under the target
    with Session(engine) as session:
        fresh = check_reminders(session, now=_et(10, 30))
    assert fresh["alerts"] == 1


def test_check_reminders_crypto_is_always_in_session(engine):
    _watch(engine, "BTC", "CRYPTO", price=90000.0, target=95000.0, name="Bitcoin")
    with Session(engine) as session:
        result = check_reminders(session, now=datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc))
    assert result["alerts"] == 1


def test_check_reminders_skips_disabled_alert(engine):
    _watch(engine, alert=False)
    with Session(engine) as session:
        result = check_reminders(session, now=_et(10, 0))
    assert result["alerts"] == 0


def test_check_reminders_formats_groups_and_cooldown(engine, monkeypatch):
    sent = {}
    import notifier.telegram as telegram

    monkeypatch.setattr(
        telegram, "notify", lambda message: sent.setdefault("text", message) and True
    )
    _watch(engine, "SPCX", "US", price=125.0, target=132.0, name="SpaceX")
    _watch(engine, "BTC", "CRYPTO", price=90000.0, target=95000.0, name="Bitcoin")
    with Session(engine) as session:
        result = check_reminders(session, now=_et(10, 0))
    assert result["notified"] is True
    text = sent["text"]
    assert text.startswith("🔔 关注价提醒")
    assert "【美股】" in text and "【加密】" in text
    assert "- SpaceX 现价 125.00 ≤ 关注价 132.00" in text
    assert "每 2 小时最多提醒一次" in text


def test_reminder_name_trims_share_class_suffix():
    from debrief.worker import _reminder_name

    class Item:
        name = "Duolingo, Inc. - Class A Common Stock"
        ticker = "DUOL"

    assert _reminder_name(Item()) == "Duolingo, Inc."
